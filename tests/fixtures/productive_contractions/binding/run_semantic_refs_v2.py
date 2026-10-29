# SPDX-License-Identifier: MIT
"""동결된 의미 참조를 단일 네이티브 증명 API에 결속한다."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unicodedata

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REFS = HERE.parent
GOLD_MANIFEST_SHA256 = "53eb135e3e83f0c156c175a4ed1f9e3858d405f9d63acb9be540d48edddb6dce"
FINAL_API_SHA256 = "f119fbb3c9fe135b2b294337c471c83f122e8cc3f5dd2938501cc50d7154023a"
R40A = "맞춤법.40.격음축약"
R40D = "맞춤법.40.붙임2.하탈락"
R39 = "맞춤법.39.지않축약"
RECIPES = {
    "N01": ("39",), "N02": ("40a", "39"), "N03": ("40a",),
    "N04": ("40a",), "N05": ("40d",), "N06": ("40d",),
    "N07": ("40d", "39"), "N08": ("40a",),
    "P01": ("40a",), "P02": ("40a",), "P03": ("40a",),
    "P04": ("40a", "39"), "P05": ("40a", "39"),
    "P06": ("40d", "39"), "P07": ("40d", "39"),
    "P08": ("40d", "39"), "P09": ("39",),
    "P10": ("40a", "39"), "P11": ("40d",), "P12": ("40d",),
}
NEGATIVES = set("G01 G02 G03 G04 G05 G06 G07 G10 G11 G19 G20 G27 G28".split())
UNBOUND = {
    "G12": "원시 범위 없는 약한 표기 bool만으로 다른 규칙과 39·40항의 경로를 구별할 공개 trace가 없다.",
    "G13": "호환 자모 어미의 다른 규칙과 39·40항 경로를 구별할 공개 trace가 없다.",
    "G17": "표면 solver에 외부 파생 문법의 거부 결과를 주입하는 훅이 없다.",
}
CLOSURE = {
    "g2p_ko.analysis_features": "g2p_ko/analysis_features.py",
    "g2p_ko.model": "g2p_ko/model.py",
    "g2p_ko.korean.hangul": "g2p_ko/korean/hangul.py",
    "g2p_ko.korean.word_grammar": "g2p_ko/korean/word_grammar.py",
    "g2p_ko.korean.surface_proof": "g2p_ko/korean/surface_proof.py",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_gold():
    manifest_path = REFS / "manifest.json"
    if sha(manifest_path) != GOLD_MANIFEST_SHA256:
        raise ValueError("독립 참조 manifest 해시가 동결값과 다릅니다.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if sha(REFS / item["file"]) != item["sha256"]:
            raise ValueError("동결 참조 파일 해시 불일치: " + item["file"])
    ledger = json.loads((REFS / "Expected_Facts_KO.json").read_text(encoding="utf-8"))
    rows = {row["사례"]: row for row in ledger["사례"]}
    if len(rows) != 48:
        raise ValueError("동결 사례 수 또는 식별자가 다릅니다.")
    covered = set(RECIPES) | NEGATIVES | set(UNBOUND) | set(
        "G08 G09 G14 G15 G16 G18 G21 G22 G23 G24 G25 G26".split())
    if covered != set(rows):
        raise ValueError("결속 계획이 동결된 48개 식별자를 정확히 덮지 않습니다.")
    return rows


def role(jamo):
    value = ord(jamo)
    if 0x1100 <= value <= 0x1112:
        return "onset"
    if 0x1161 <= value <= 0x1175:
        return "vowel"
    if 0x11A8 <= value <= 0x11C2:
        return "coda"
    raise ValueError("정규 한글 원자가 아닙니다: " + repr(jamo))


def parts(row):
    return tuple((p["공급_원형"], p["공급_품사"]) for p in row["공급_출현"])


def spans(row):
    items = row["공급_출현"]
    if not items or any("원시_구간_주장" not in p for p in items):
        return ()
    return tuple(tuple(p["원시_구간_주장"]) for p in items)


def original_groups(ps):
    groups = []
    for occurrence, (form, _) in enumerate(ps):
        group = []
        for offset, char in enumerate(form):
            for jamo in unicodedata.normalize("NFD", char):
                group.append((jamo, frozenset({(occurrence, offset, role(jamo), jamo)})))
        groups.append(group)
    return groups


def atom_obj(key):
    return SimpleNamespace(occurrence=key[0], source_offset=key[1], role=key[2], jamo=key[3])


def source_key(atom):
    return (atom.occurrence, atom.source_offset, atom.role, atom.jamo)


def node_obj(node, offset):
    return SimpleNamespace(jamo=node[0], offset=offset, role=role(node[0]),
                           origins=tuple(atom_obj(k) for k in sorted(node[1])))


def semantic_projection(row, recipe, start=0):
    """동결 사실의 원자 의미를 구성하며 구현의 검색·분기 알고리즘을 호출하지 않는다."""
    ps, raw_spans = parts(row), spans(row)
    groups = original_groups(ps)
    originals = [list(group) for group in groups]
    steps = []
    for operation in recipe:
        if operation.startswith("40"):
            h = next(i for i, (form, _) in enumerate(ps) if form.endswith("하"))
            e = h + 1
            ha = groups[h][-2:]
            if [n[0] for n in ha] != ["ᄒ", "ᅡ"]:
                raise ValueError("동결 기대의 하 위치 불일치")
            if operation == "40a":
                original_onset = groups[e][0]
                aspirate = {"ᄀ": "ᄏ", "ᄃ": "ᄐ", "ᄌ": "ᄎ"}[original_onset[0]]
                changed = (aspirate, ha[0][1] | original_onset[1])
                before, after, deleted = ha + [original_onset], [changed], ha[1][1]
                groups[h] = groups[h][:-2]
                groups[e][0] = changed
                rule_id = R40A
            else:
                before, after = ha, []
                deleted = ha[0][1] | ha[1][1]
                groups[h] = groups[h][:-2]
                rule_id = R40D
            boundary = (h, e)
        else:
            j = next(i for i, part in enumerate(ps) if part == ("지", "EC"))
            a = j + 1
            if ps[a] != ("않", "VX"):
                raise ValueError("동결 기대의 지/않 경계 불일치")
            jnodes, anodes = groups[j], groups[a]
            before = jnodes + anodes
            after = [jnodes[0], ("ᅡ", jnodes[1][1] | anodes[1][1]), anodes[2]]
            deleted = anodes[0][1]
            groups[j], groups[a] = after, []
            boundary, rule_id = (j, a), R39
        steps.append(SimpleNamespace(
            boundary=boundary, rule_id=rule_id,
            inputs=tuple(n[0] for n in before), outputs=tuple(n[0] for n in after),
            before_origins=tuple(tuple(atom_obj(k) for k in sorted(n[1])) for n in before),
            after_origins=tuple(tuple(atom_obj(k) for k in sorted(n[1])) for n in after),
            deleted=tuple(atom_obj(k) for k in sorted(deleted))))
    final_nodes = [node for group in groups for node in group]
    raw = "".join(n[0] for n in final_nodes)
    surface = unicodedata.normalize("NFC", raw)
    if surface != row["관측_표면"] or unicodedata.normalize("NFD", surface) != raw:
        raise ValueError("동결 기대 투영과 관측 표면 불일치: " + row["사례"])
    atoms, cursor = [], 0
    for offset, char in enumerate(surface, start):
        for _ in unicodedata.normalize("NFD", char):
            atoms.append(node_obj(final_nodes[cursor], offset))
            cursor += 1
    ranges = []
    for i in range(len(ps)):
        offsets = [a.offset for a in atoms if any(o.occurrence == i for o in a.origins)]
        ranges.append((min(offsets), max(offsets) + 1) if offsets else None)
    deleted_occurrences = []
    for i, span in enumerate(ranges):
        if span is not None:
            continue
        own = frozenset(k for _, origins in originals[i] for k in origins)
        witness = next(s for s in steps if own <= set(source_key(a) for a in s.deleted))
        if not raw_spans or raw_spans[i][0] != raw_spans[i][1]:
            raise ValueError("완전 삭제의 공급 경계가 빠졌습니다.")
        deleted_occurrences.append(SimpleNamespace(
            index=i, offset=raw_spans[i][0], boundary=witness.boundary,
            rule_id=witness.rule_id, atoms=tuple(atom_obj(k) for k in sorted(own))))
    return SimpleNamespace(start=start, end=start + len(surface), parts=ps,
        morpheme_spans=raw_spans, occurrences=tuple(SimpleNamespace(
            index=i, form=form, tag=tag, raw_span=raw_spans[i] if raw_spans else None)
            for i, (form, tag) in enumerate(ps)),
        regenerated_spans=tuple(ranges), atoms=tuple(atoms), steps=tuple(steps),
        deleted_occurrences=tuple(deleted_occurrences))


def add_check(checks, label, actual, expected):
    ok = actual == expected
    checks.append({"check": label, "ok": ok,
                   **({} if ok else {"expected": expected, "actual": actual})})
    return ok


def graph_checks(proof, expected):
    """네이티브 필드를 한 가지 방식으로 읽어 의미·회계만 비교한다."""
    checks = []
    if not add_check(checks, "정확한_증명_존재", proof is not None, True):
        return checks
    for name in ("start", "end", "parts", "morpheme_spans", "regenerated_spans"):
        add_check(checks, name, getattr(proof, name), getattr(expected, name))
    pack = lambda p: tuple((o.index, o.form, o.tag, o.raw_span) for o in p.occurrences)
    add_check(checks, "원형_출현과_원시_주장", pack(proof), pack(expected))
    signature = lambda p: tuple((a.jamo, a.offset, a.role, tuple(sorted(source_key(o) for o in a.origins)))
                                for a in p.atoms)
    add_check(checks, "출력_자모별_정확_유래", signature(proof), signature(expected))
    add_check(checks, "규칙_순서", tuple(s.rule_id for s in proof.steps),
              tuple(s.rule_id for s in expected.steps))
    add_check(checks, "원래_경계", tuple(s.boundary for s in proof.steps),
              tuple(s.boundary for s in expected.steps))
    deleted = lambda p: tuple(tuple(sorted(source_key(a) for a in s.deleted)) for s in p.steps)
    add_check(checks, "단계별_삭제_원자", deleted(proof), deleted(expected))
    canonical = {key for group in original_groups(expected.parts) for _, origins in group for key in origins}
    living = [source_key(o) for a in proof.atoms for o in a.origins]
    removed = [source_key(o) for s in proof.steps for o in s.deleted]
    add_check(checks, "생존_원자_중복_없음", len(living), len(set(living)))
    add_check(checks, "삭제_원자_중복_없음", len(removed), len(set(removed)))
    add_check(checks, "생존과_삭제_배타", set(living) & set(removed), set())
    add_check(checks, "전체_원형_원자_회계", set(living) | set(removed), canonical)
    for i, step in enumerate(proof.steps):
        before = [source_key(a) for group in step.before_origins for a in group]
        after = [source_key(a) for group in step.after_origins for a in group]
        gone = {source_key(a) for a in step.deleted}
        valid_shape = (len(step.inputs) == len(step.before_origins)
                       and len(step.outputs) == len(step.after_origins)
                       and all(step.before_origins) and all(step.after_origins))
        add_check(checks, f"단계{i}_자모와_유래_수", bool(valid_shape), True)
        add_check(checks, f"단계{i}_입력_중복_없음", len(before), len(set(before)))
        add_check(checks, f"단계{i}_출력_중복_없음", len(after), len(set(after)))
        add_check(checks, f"단계{i}_국소_원자_회계", set(before), set(after) | gone)
        add_check(checks, f"단계{i}_삭제와_출력_배타", set(after) & gone, set())
        add_check(checks, f"단계{i}_정규_원형_신원", set(before) | set(after) | gone <= canonical, True)
        if i < len(expected.steps):
            expected_step = expected.steps[i]
            native_nodes = lambda text, origins: {(j, frozenset(source_key(a) for a in group))
                                                  for j, group in zip(text, origins)}
            add_check(checks, f"단계{i}_필수_입력_자모와_유래",
                native_nodes(expected_step.inputs, expected_step.before_origins) <=
                native_nodes(step.inputs, step.before_origins), True)
            add_check(checks, f"단계{i}_필수_출력_자모와_유래",
                native_nodes(expected_step.outputs, expected_step.after_origins) <=
                native_nodes(step.outputs, step.after_origins), True)
    if expected.steps:
        # 새 규칙의 증명에는 완전 삭제 목록의 정확성도 요구한다. 직접 연결 기반 API는 그대로 쓴다.
        pack_deleted = lambda p: tuple((d.index, d.offset, d.boundary, d.rule_id,
            tuple(sorted(source_key(a) for a in d.atoms))) for d in p.deleted_occurrences)
        add_check(checks, "완전_삭제_출현의_정체와_유일_경계",
                  pack_deleted(proof), pack_deleted(expected))
    return checks


class IsolatedFinder(importlib.abc.MetaPathFinder):
    """프로젝트 패키지의 승인된 다섯 파일만 불러온다."""

    def __init__(self, src):
        self.src = src

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("g2p_ko."):
            if fullname not in CLOSURE:
                raise ImportError("승인 지원 폐쇄 밖의 프로젝트 import: " + fullname)
            return importlib.util.spec_from_file_location(fullname, self.src / CLOSURE[fullname])
        return None


def load_runtime(src):
    if any(n == "g2p_ko" or n.startswith("g2p_ko.") for n in sys.modules):
        raise RuntimeError("기존 프로젝트 import가 있는 프로세스에서는 실행하지 않습니다.")
    src = src.resolve()
    for relative in CLOSURE.values():
        required = src / relative
        if not required.resolve().is_relative_to(src):
            raise RuntimeError("지원 파일의 실제 경로가 지정 소스 밖에 있습니다.")
        if not required.exists() or not required.is_file():
            raise FileNotFoundError("필수 지원 파일이 없습니다: " + str(required))
    # 해시 계산의 실제 파일 읽기로 지원 파일 접근을 import 전에 확인한다.
    inventory = {name: {"path": relative, "sha256": sha(src / relative)}
                 for name, relative in CLOSURE.items()}
    for name, path in (("g2p_ko", src / "g2p_ko"), ("g2p_ko.korean", src / "g2p_ko/korean")):
        namespace = ModuleType(name)
        namespace.__path__ = [str(path)]
        sys.modules[name] = namespace
    finder = IsolatedFinder(src)
    sys.meta_path.insert(0, finder)
    model = importlib.import_module("g2p_ko.model")
    grammar = importlib.import_module("g2p_ko.korean.word_grammar")
    surface = importlib.import_module("g2p_ko.korean.surface_proof")
    for name, item in inventory.items():
        module = sys.modules.get(name)
        if module is None or Path(module.__file__).resolve() != (src / item["path"]).resolve():
            raise RuntimeError("소스 격리 검증 실패: " + name)
    return SimpleNamespace(Token=model.AnalysisToken, surface=surface, grammar=grammar,
                           source=str(src), inventory=inventory)


def make_token(api, row, start=0):
    ps = parts(row)
    return api.Token(row["관측_표면"], "+".join(t for _, t in ps), start,
                     start + len(row["관측_표면"]), morphemes=ps, morpheme_spans=spans(row))


def local_row(row, first, last, start, end):
    return {**row, "관측_표면": row["관측_표면"][start:end],
            "공급_출현": row["공급_출현"][first:last]}


def diagnostic_rows():
    # 아래 자모 대응은 G26의 동결 사실을 추상 한 음절 조건으로 결속한 것이다.
    finals = (None, "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
              "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
              "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")
    groups = {"vowel": [None], "ㄱ": ["ㄱ", "ㄲ", "ㅋ"],
              "ㄷ": ["ㄷ", "ㅅ", "ㅆ", "ㅈ", "ㅊ", "ㅌ"],
              "ㅂ": ["ㅂ", "ㅍ"], "ㄴ": ["ㄴ"], "ㄹ": ["ㄹ"], "ㅁ": ["ㅁ"], "ㅇ": ["ㅇ"]}
    return [(chr(0xAC00 + finals.index(coda)), answer)
            for answer, codas in groups.items() for coda in codas]


def bind_case(api, row, rows):
    cid = row["사례"]
    checks, missing = [], []
    scope = "abstract_condition" if cid in {"G14", "G15", "G26"} else "actual_or_packaging"
    observations = {}
    if cid in RECIPES:
        expected = semantic_projection(row, RECIPES[cid])
        add_check(checks, "약한_표기_가능성", api.surface.licensed_spelling(parts(row), row["관측_표면"]), True)
        checks += graph_checks(api.surface.verified_token_surface(make_token(api, row)), expected)
    elif cid in NEGATIVES:
        add_check(checks, "잘못된_표면의_약한_인증_거부",
                  api.surface.licensed_spelling(parts(row), row["관측_표면"]), False)
        add_check(checks, "정확_인증_없음",
                  api.surface.verified_token_surface(make_token(api, row)) is None, True)
    elif cid in UNBOUND:
        missing.append(UNBOUND[cid])
    elif cid in {"G08", "G09"}:
        split = ((0, 2, 0, 4), (2, 4, 5, 7)) if cid == "G08" else ((0, 2, 0, 2), (2, 4, 3, 5))
        for first, last, start, end in split:
            region = local_row(row, first, last, start, end)
            checks += graph_checks(api.surface.verified_token_surface(make_token(api, region, start)),
                                   semantic_projection(region, (), start))
        add_check(checks, "장벽_포함_전체를_준말로_인증하지_않음",
                  api.surface.licensed_spelling(parts(row), row["관측_표면"]), False)
        add_check(checks, "외부_원문_구간_보존",
                  "".join(row["관측_표면"][i:i+1] for i in range(len(row["관측_표면"]))),
                  row["관측_표면"])
    elif cid in {"G14", "G15", "G26"}:
        diagnostic = getattr(api.surface, "_pre_ha_sound", None)
        if diagnostic is None:
            missing.append("선언된 순수 내부 진단 _pre_ha_sound가 이 소스에 없어 추상 조건은 미결속이다.")
        elif cid == "G26":
            for character, expected in diagnostic_rows():
                add_check(checks, "추상_단순_받침_" + character, diagnostic(character), expected)
        else:
            character = "갉" if cid == "G14" else "갛"
            add_check(checks, "추상_미해결_종성", diagnostic(character), None)
    elif cid == "G16":
        add_check(checks, "앞_소유_음절_없는_40_표기_거부",
                  api.surface.licensed_spelling(parts(row), row["관측_표면"]), False)
    elif cid == "G18":
        result = api.grammar.parse_parts(parts(row), fragment=True, allow_auxiliary=False)
        add_check(checks, "보조_문법_차단", (result.lexical_status, result.reason),
                  ("unresolved", "auxiliary_structure_unavailable"))
        missing.append("거부된 외부 문법 결과를 표면 solver에 주입하는 공개 훅은 없다.")
    elif cid == "G21":
        proof = api.surface.verified_token_surface(make_token(api, row))
        observations["certificate_returned"] = proof is not None
        if proof is None:
            add_check(checks, "영폭만으로_증명_발행하지_않음", True, True)
        else:
            checks += graph_checks(proof, semantic_projection(row, ("40d",)))
    elif cid == "G22":
        add_check(checks, "범위_없는_약한_표기",
                  api.surface.licensed_spelling(parts(row), row["관측_표면"]), True)
        add_check(checks, "범위_없는_정확_소유_미인증",
                  api.surface.verified_token_surface(make_token(api, row)) is None, True)
    elif cid == "G23":
        alternatives = []
        for alternative in row["공급_대안"]:
            local = {**row, "공급_출현": alternative["출현"]}
            expected = semantic_projection(local, ("40d",))
            proof = api.surface.verified_token_surface(make_token(api, local))
            checks += graph_checks(proof, expected)
            alternatives.append(expected)
        add_check(checks, "대안별_출현과_원자_증거_상이",
                  (alternatives[0].parts, alternatives[0].regenerated_spans) !=
                  (alternatives[1].parts, alternatives[1].regenerated_spans), True)
        missing.append("복수 분석 후보를 수신·선택하는 공개 API가 없으므로 외부 유일성 결정은 미결속이다.")
    elif cid == "G24":
        for first, last, start, end in ((0, 3, 0, 4), (3, 6, 5, 9)):
            region = local_row(row, first, last, start, end)
            checks += graph_checks(api.surface.verified_token_surface(make_token(api, region, start)),
                                   semantic_projection(region, ("40d",), start))
        labels = [o["출현"] for o in row["공급_출현"]]
        add_check(checks, "외부_출현_식별자_중복_없음", len(labels), len(set(labels)))
        add_check(checks, "지역_삭제_절대_위치", (spans(row)[1], spans(row)[4]), ((2, 2), (7, 7)))
    elif cid == "G25":
        region = local_row(row, 0, 6, 1, 6)
        checks += graph_checks(api.surface.verified_token_surface(make_token(api, region, 1)),
                               semantic_projection(region, ("40a", "39"), 1))
        add_check(checks, "외부_인쇄부호와_원시_위치",
                  tuple((tuple(o["구간"]), row["관측_표면"][o["구간"][0]:o["구간"][1]])
                        for o in row["외부_포장"]),
                  (((0, 1), "«"), ((6, 7), "!"), ((7, 8), "»")))
    else:
        raise ValueError("계획에 없는 사례: " + cid)
    failed = any(not c["ok"] for c in checks)
    status = ("partial_fail" if failed else "partial_pass") if missing and checks else (
        "unbound" if missing else ("fail" if failed else "pass"))
    return {"id": cid, "scope": scope, "status": status, "checks": checks,
            "unbound_facts": missing, "observations": observations}


def json_default(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(type(value).__name__)


def preflight(rows):
    """실제 소스를 불러오지 않고 증명 검사기의 변조 검출을 확인한다."""
    tests = []
    for cid, recipe in RECIPES.items():
        proof = semantic_projection(rows[cid], recipe)
        checks = graph_checks(proof, proof)
        tests.append({"name": cid + "_합성_유효_증명", "ok": all(c["ok"] for c in checks)})
    base = semantic_projection(rows["P06"], RECIPES["P06"])
    mutations = []
    changed = copy.deepcopy(base); changed.deleted_occurrences = (); mutations.append(("삭제_출현_누락", changed))
    changed = copy.deepcopy(base); changed.deleted_occurrences[0].offset += 1; mutations.append(("삭제_위치_변조", changed))
    changed = copy.deepcopy(base); changed.deleted_occurrences[0].boundary = (0, 1); mutations.append(("삭제_경계_변조", changed))
    changed = copy.deepcopy(base); changed.deleted_occurrences[0].atoms = (); mutations.append(("삭제_원자_누락", changed))
    changed = copy.deepcopy(base); rr = list(changed.regenerated_spans); rr[1] = (2, 2); changed.regenerated_spans = tuple(rr); mutations.append(("살아있는_영폭_범위_위조", changed))
    changed = copy.deepcopy(base); changed.steps = tuple(reversed(changed.steps)); mutations.append(("39_40_순서_역전", changed))
    changed = copy.deepcopy(base); changed.steps[0].deleted = (); mutations.append(("삭제_단계_누락", changed))
    changed = copy.deepcopy(base); changed.atoms[0].offset += 1; mutations.append(("절대_출력_위치_변조", changed))
    changed = copy.deepcopy(base); changed.atoms[0].origins += (changed.steps[0].deleted[0],); mutations.append(("삭제원자의_생존_소유_중복", changed))
    changed = copy.deepcopy(base); changed.atoms[0].origins += changed.atoms[0].origins; mutations.append(("출력_유래_중복", changed))
    changed = copy.deepcopy(base); changed.steps[0].after_origins = changed.steps[0].before_origins; mutations.append(("단계_삭제_회계_위조", changed))
    changed = copy.deepcopy(base); changed.occurrences[1].raw_span = (0, 0); mutations.append(("원시_경계_변조", changed))
    changed = copy.deepcopy(base); changed.steps[1].outputs = ("ᄀ",) + changed.steps[1].outputs[1:]; mutations.append(("단계_출력_자모_변조", changed))
    for name, changed in mutations:
        tests.append({"name": name, "ok": any(not c["ok"] for c in graph_checks(changed, base))})
    tests.append({"name": "48개_결속_계획_닫힘", "ok": len(rows) == 48})
    tests.append({"name": "추상_진단_조건_별도", "ok": len(diagnostic_rows()) == 16})
    tests.append({"name": "프로젝트_import_없음", "ok": not any(n == "g2p_ko" or n.startswith("g2p_ko.") for n in sys.modules)})
    return {"schema": "r43-semantic-preflight-1", "synthetic_only": True,
            "runner_sha256": sha(Path(__file__)), "gold_manifest_sha256": GOLD_MANIFEST_SHA256,
            "runtime_imported": False, "phone_gold": 0, "tests": tests,
            "passed": sum(t["ok"] for t in tests), "total": len(tests),
            "all_passed": all(t["ok"] for t in tests)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(HERE) or out == HERE:
        parser.error("--out은 이 binding 디렉터리 아래의 새 보고서 디렉터리여야 합니다.")
    if out.exists():
        parser.error("--out이 이미 존재합니다. 새 경로를 지정해야 합니다.")
    if args.preflight == bool(args.src):
        parser.error("--preflight 또는 --src 중 정확히 하나를 지정해야 합니다.")
    rows = read_gold()
    if args.preflight:
        report = preflight(rows)
    else:
        api = load_runtime(args.src)
        results = []
        for row in rows.values():
            try:
                results.append(bind_case(api, row, rows))
            except Exception as exc:
                results.append({"id": row["사례"], "status": "error",
                    "scope": "abstract_condition" if row["사례"] in {"G14", "G15", "G26"} else "actual_or_packaging",
                    "checks": [], "unbound_facts": [],
                    "error": type(exc).__name__ + ": " + str(exc)})
        report = {"schema": "r43-semantic-provenance-1",
            "created_utc": datetime.now(timezone.utc).isoformat(), "source": api.source,
            "source_support_closure": api.inventory, "gold_manifest_sha256": GOLD_MANIFEST_SHA256,
            "documented_api_sha256": FINAL_API_SHA256, "runner_sha256": sha(Path(__file__)),
            "phone_gold": 0, "pronunciation_accuracy_claimed": False,
            "case_counts": {"total_semantic": 48, "abstract_conditions": 3,
                            "actual_or_packaging": 45},
            "statuses": dict(Counter(r["status"] for r in results)),
            "scope_statuses": {scope: dict(Counter(r["status"] for r in results if r["scope"] == scope))
                              for scope in ("abstract_condition", "actual_or_packaging")},
            "cases": results}
    out.mkdir(parents=True, exist_ok=False)
    path = out / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=json_default) + "\n",
                    encoding="utf-8", newline="\n")
    summary = {"report": str(path), "phone_gold": 0}
    if args.preflight:
        summary.update(passed=report["passed"], total=report["total"], synthetic_only=True)
        code = 0 if report["all_passed"] else 1
    else:
        summary["statuses"] = report["statuses"]
        code = 1 if any(r["status"] in {"fail", "partial_fail", "error"} for r in report["cases"]) else 0
    print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
