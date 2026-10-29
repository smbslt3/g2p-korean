# SPDX-License-Identifier: MIT
"""동결된 독립 참조를 기존 표면 증명 API에 연결하는 유한 검사기다."""

from __future__ import annotations

import argparse
import builtins
from collections import Counter
import hashlib
import importlib.machinery
import json
from pathlib import Path
import sys
import types
import unicodedata


# 최종 R44 공개 API만 확인했으며 후보 구현과 실행 결과는 읽지 않았다.
BINDING_FROZEN = True
FROZEN_REFERENCES_SHA256 = "c1789243a9d98af8041a96d68d0b8c61be35e786b0ca14d23485a5ab4e74724a"
ABSTRACT_IDS = frozenset(f"A{i:02}" for i in range(1, 8))
ROLE = {"L": "onset", "V": "vowel", "T": "coda"}
COMPAT = {
    "L": "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ",
    "V": "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ",
    "T": "ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ",
}
NFD_START = {"L": 0x1100, "V": 0x1161, "T": 0x11A8}
RULE_IDS = frozenset({"맞춤법.18.5.ㄷ교체", "맞춤법.18.2.ㅅ탈락"})
FILES = (
    ("analysis_features", "g2p_ko/analysis_features.py"),
    ("model", "g2p_ko/model.py"),
    ("korean.hangul", "g2p_ko/korean/hangul.py"),
    ("korean.word_grammar", "g2p_ko/korean/word_grammar.py"),
    ("korean.surface_proof", "g2p_ko/korean/surface_proof.py"),
)


def nfd_jamo(value, slot):
    """호환 자모를 원래 역할에 맞는 정규 자모 하나로 바꾼다."""
    return chr(NFD_START[slot] + COMPAT[slot].index(value))


def load_native(src):
    """실제 읽은 다섯 파일만 별도 패키지 이름으로 불러온다."""
    src = Path(src).resolve()
    payloads = []
    audit = []
    for suffix, relative in FILES:
        path = (src / relative).resolve()
        path.relative_to(src)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        payloads.append((suffix, path, data))
        audit.append({"path": relative, "sha256": digest})
    prefix = "_r44_independent_native"
    def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
        # 프로젝트의 절대 가져오기나 설치본으로 우회하는 경로를 열지 않는다.
        if not level and name.partition(".")[0] not in sys.stdlib_module_names:
            raise ImportError("다섯 파일 밖의 가져오기를 지원하지 않습니다: " + name)
        return builtins.__import__(name, globals, locals, fromlist, level)
    isolated_builtins = dict(vars(builtins), __import__=isolated_import)
    for name in (prefix, prefix + ".korean"):
        package = types.ModuleType(name)
        package.__package__ = name
        package.__path__ = []
        package.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        sys.modules[name] = package
    modules = {}
    for suffix, path, data in payloads:
        name = prefix + "." + suffix
        module = types.ModuleType(name)
        module.__package__ = name.rpartition(".")[0]
        module.__file__ = str(path)
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
        module.__dict__["__builtins__"] = isolated_builtins
        sys.modules[name] = module
        exec(compile(data, str(path), "exec"), module.__dict__)
        modules[suffix] = module
    return modules["model"], modules["korean.word_grammar"], modules["korean.surface_proof"], audit


def native_sources(ref, proof_api):
    """출력에서 원형을 역추정하지 않고 동결된 원형 원자만 연결한다."""
    occurrence_indices = {part["occurrence"]: i for i, part in enumerate(ref["input"]["canonical"])}
    sources = {}
    for part in ref["input"]["canonical"]:
        for atom in part["atoms"]:
            occurrence, offset, slot = atom["id"].split(".")
            sources[atom["id"]] = proof_api.SourceAtom(
                occurrence_indices[occurrence], int(offset), ROLE[slot], nfd_jamo(atom["jamo"], slot)
            )
    return occurrence_indices, sources


def expected_proven_atoms(ref, sources, start):
    positions = []
    for offset, character in enumerate(ref["expect"]["full_regeneration"], start):
        for jamo in unicodedata.normalize("NFD", character):
            positions.append((jamo, offset))
    expected = []
    if len(positions) != len(ref["expect"]["output_atoms"]):
        raise ValueError("동결 참조의 표면·원자 길이가 다릅니다.")
    for atom, (jamo, offset) in zip(ref["expect"]["output_atoms"], positions):
        slot = atom["owner"].rsplit(".", 1)[1]
        if nfd_jamo(atom["jamo"], slot) != jamo:
            raise ValueError("동결 참조의 표면·원자가 다릅니다.")
        expected.append((jamo, offset, ROLE[slot], (sources[atom["owner"]],)))
    return tuple(expected)


def verify_proof(ref, token, proof, proof_api, grammar):
    """공개 자료의 정확한 원형·범위·원자·규칙을 함께 확인한다."""
    occurrence_indices, sources = native_sources(ref, proof_api)
    errors = []
    parts = token.morphemes
    if (proof.start, proof.end, proof.parts, proof.morpheme_spans) != (
        token.normalized_start, token.normalized_end, parts, token.morpheme_spans
    ):
        errors.append("토큰_원형_범위")
    expected_occurrences = tuple((i, form, tag, token.morpheme_spans[i]) for i, (form, tag) in enumerate(parts))
    observed_occurrences = tuple((o.index, o.form, o.tag, o.raw_span) for o in proof.occurrences)
    if observed_occurrences != expected_occurrences or proof.regenerated_spans != token.morpheme_spans:
        errors.append("출현_신원_재생성범위")
    expected_atoms = expected_proven_atoms(ref, sources, token.normalized_start)
    observed_atoms = tuple((a.jamo, a.offset, a.role, a.origins) for a in proof.atoms)
    if observed_atoms != expected_atoms:
        errors.append("표면_원자_소유_절대좌표")
    raw = "".join(a.jamo for a in proof.atoms)
    if (unicodedata.normalize("NFC", raw) != token.form
            or unicodedata.normalize("NFD", token.form) != raw
            or token.form != ref["expect"]["full_regeneration"]):
        errors.append("전체_재생성")
    live = [origin for atom in proof.atoms for origin in atom.origins]
    deleted = [origin for step in proof.steps for origin in step.deleted]
    expected_deleted = [sources[identity] for identity in ref["expect"]["deleted"]]
    if (Counter(deleted) != Counter(expected_deleted)
            or len(live) != len(set(live)) or len(deleted) != len(set(deleted))
            or set(live) & set(deleted) or set(live) | set(deleted) != set(sources.values())):
        errors.append("원래_원자_생존_삭제_회계")
    expected_steps = ref["expect"]["steps"]
    expected_after = {sources[atom["owner"]]: nfd_jamo(atom["jamo"], atom["owner"].rsplit(".", 1)[1])
                      for atom in ref["expect"]["output_atoms"]}
    if len(proof.steps) != len(expected_steps):
        errors.append("규칙_적용횟수")
    for observed, expected in zip(proof.steps, expected_steps):
        boundary = tuple(occurrence_indices[value] for value in expected["boundary"])
        before = {origin for group in observed.before_origins for origin in group}
        after = {origin for group in observed.after_origins for origin in group}
        if (observed.rule_id != expected["rule"] or observed.rule_id not in RULE_IDS
                or observed.boundary != boundary
                or Counter(observed.deleted) != Counter(sources[value] for value in expected["deleted"])
                or sources[expected["input_atom"]] not in before
                or not before <= set(sources.values())
                or before != after | set(observed.deleted) or after & set(observed.deleted)):
            errors.append("규칙_원래경계_전후유래")
        if (any(len(group) != 1 for group in observed.before_origins + observed.after_origins)
                or len(observed.inputs) != len(observed.before_origins)
                or len(observed.outputs) != len(observed.after_origins)):
            errors.append("규칙_입출력_원자형식")
        else:
            if observed.inputs != tuple(group[0].jamo for group in observed.before_origins):
                errors.append("규칙_입력_원래자모")
            if observed.outputs != tuple(expected_after.get(group[0]) for group in observed.after_origins):
                errors.append("규칙_출력_보존교체자모")
        if not grammar.boundaries[boundary[1]].inflection:
            errors.append("공유문법_활용허가")
    if proof.deleted_occurrences:
        errors.append("종성탈락을_전체출현삭제로_오인")
    for identity in ref["expect"]["ending_and_tail_atoms"]:
        origin = sources[identity]
        if sum(atom.origins == (origin,) and atom.jamo == origin.jamo for atom in proof.atoms) != 1:
            errors.append("어미_꼬리_보존")
            break
    return errors


def inspect_semantic(ref, model, grammar_api, proof_api):
    parts = tuple((part["form"], part["tag"]) for part in ref["input"]["canonical"])
    surface = ref["input"]["surface"]
    weak = proof_api.licensed_spelling(parts, surface)
    expected_weak = ref["expect"]["weak_spelling"] == "성공"
    grammar = grammar_api.parse_parts(parts, fragment=True)
    row = {"id": ref["id"], "weak": weak, "expected_weak": expected_weak,
           "weak_pass": weak == expected_weak, "grammar_reason": grammar.reason, "strong": []}
    # 길이가 다른 부정 사례에 가짜 원시 범위를 만들지 않는다.
    if sum(len(form) for form, _ in parts) != len(surface):
        row["strong_status"] = "원시범위_미연결_철자길이불일치"
        return row
    for start in (0, 7):
        cursor = start
        spans = []
        for form, _ in parts:
            spans.append((cursor, cursor + len(form)))
            cursor += len(form)
        token = model.AnalysisToken(surface, "+".join(tag for _, tag in parts), start, start + len(surface),
                                    morphemes=parts, morpheme_spans=tuple(spans))
        proof = proof_api.verified_token_surface(token)
        expected_strong = ref["expect"]["strong_token_proof"] != "거부"
        errors = []
        if proof is not None:
            errors = verify_proof(ref, token, proof, proof_api, grammar)
        row["strong"].append({"start": start, "present": proof is not None,
                              "expected_present": expected_strong, "errors": errors,
                              "pass": (proof is not None) == expected_strong and not errors})
    row["strong_status"] = "연결됨"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, help="g2p_ko를 포함하는 승인된 src 디렉터리")
    parser.add_argument("--out", required=True, help="프로젝트 안의 검사 보고서 디렉터리")
    args = parser.parse_args()
    if not BINDING_FROZEN:
        parser.error("공개 API 연결이 아직 동결되지 않았습니다.")
    project_root = Path(__file__).resolve().parents[3]
    references = Path(__file__).resolve().parent.parent / "independent_refs/references.jsonl"
    data = references.read_bytes()
    if hashlib.sha256(data).hexdigest() != FROZEN_REFERENCES_SHA256:
        raise ValueError("동결 참조 해시가 다릅니다.")
    refs = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    if len(refs) != 32 or {r["id"] for r in refs if r["binding"] == "abstract_unbound"} != ABSTRACT_IDS:
        raise ValueError("동결 참조의 유한 범위가 다릅니다.")
    out = Path(args.out).resolve()
    out.relative_to(project_root)
    if out == project_root or out.is_relative_to(references.parent):
        raise ValueError("동결 참조와 프로젝트 루트에는 보고서를 쓰지 않습니다.")
    model, grammar_api, proof_api, source_files = load_native(args.src)
    rows = [inspect_semantic(ref, model, grammar_api, proof_api) for ref in refs if ref["id"] not in ABSTRACT_IDS]
    report = {"scope": "유한_의미참조_연결검사", "source_root": str(Path(args.src).resolve()),
              "source_files": source_files, "phone_gold": 0,
              "semantic_records": len(rows), "abstract_unbound": sorted(ABSTRACT_IDS), "records": rows,
              "weak_failures": sum(not row["weak_pass"] for row in rows),
              "strong_failures": sum(not case["pass"] for row in rows for case in row["strong"]),
              "strong_unbound": [row["id"] for row in rows if row["strong_status"] != "연결됨"]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("semantic_records", "weak_failures", "strong_failures", "strong_unbound", "abstract_unbound")}, ensure_ascii=False))
    return int(bool(report["weak_failures"] or report["strong_failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
