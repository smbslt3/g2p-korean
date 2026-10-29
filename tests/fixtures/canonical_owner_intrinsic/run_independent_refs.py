"""원본 독립 참조를 선택 소스 하나와 실제 원본 분석에 연결한다."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
# native 원자는 역할별 정규 NFD다: 종성 U+11AE, 초성 U+110B, 중성 U+1175.
NATIVE_JAMO = {"coda": "\u11ae", "onset": "\u110b", "vowel": "\u1175"}


def jsonable(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [jsonable(v) for v in value]
    return value


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(jsonable(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def sha256(path):
    """체크아웃의 줄바꿈 차이만 제거한 지원 파일 해시를 계산한다."""
    return hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()


def source_digest(src):
    """선택 패키지 전체의 digest를 실행당 한 번만 계산한다."""
    digest = hashlib.sha256()
    files = sorted((src / "g2p_ko").rglob("*.py"))
    for path in files:
        digest.update(path.relative_to(src).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return {"sha256": digest.hexdigest(), "file_count": len(files)}


def verify_modules(src):
    paths = {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
             if (name == "g2p_ko" or name.startswith("g2p_ko.")) and getattr(module, "__file__", None)}
    if any(not Path(path).is_relative_to(src) for path in paths.values()):
        raise RuntimeError("선택 source 밖의 프로젝트 모듈을 가져왔습니다.")
    return paths


def prepare_runtime(src, counts):
    versions = {name: importlib.metadata.version(name) for name in ("kiwipiepy", "kiwipiepy_model")}
    if versions != {"kiwipiepy": "0.24.1", "kiwipiepy_model": "0.24.0"}:
        raise RuntimeError("허용된 Kiwi/model 배포 버전과 다릅니다.")
    if any(name == "g2p_ko" or name.startswith("g2p_ko.") for name in sys.modules):
        raise RuntimeError("프로젝트 모듈이 이미 로드되어 있습니다.")
    sys.path.insert(0, str(src))
    modules = {name: importlib.import_module("g2p_ko" + suffix) for name, suffix in
               (("package", ""), ("analyzer", ".analyzer"), ("model", ".model"),
                ("engine", ".korean.engine"), ("morphology", ".korean.morphology"),
                ("roles", ".korean.word_roles"), ("proof", ".korean.surface_proof"),
                ("consumer", ".korean.boundary_consumers"))}
    verify_modules(src)
    from kiwipiepy import Kiwi

    class CountedKiwi:
        """계측 외에는 실제 모델의 원본 결과를 그대로 보존한다."""
        def __init__(self):
            counts["model_constructors"] += 1
            self.inner = Kiwi(model_type="cong")
        def tokenize(self, *args, **kwargs):
            counts["kiwi_tokenize"] += 1
            return self.inner.tokenize(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(self.inner, name)

    modules["analyzer"]._runtime_kiwi = CountedKiwi()
    return modules, {**versions, "model_type": "cong"}


def row(record, route):
    """실제·구성·추상 참조에 같은 결과 스키마를 사용한다."""
    return {"ref_id": record["id"], "scope": record["scope"], "route": route,
            "binding_status": "unbound", "reason": None,
            "input": {"text": record["input"]["text"], "analysis_before": [], "analysis_after": [], "controls": {}},
            "observed": {"full_output": None, "g2p_result": None, "boundaries": [], "events": [], "duplicate_events": [], "repeat_events": []},
            "checks": {"full_phone": None, "intrinsic_event": None, "source_authority": None,
                       "input_preserved": None, "single_consumption": None}}


def score_full(record, actual):
    gold = record["expected"]["full_output"]["phones"]
    return None if gold is None else actual == gold


def same_analysis(before, after):
    return before == after


def owner_matches(parts, required_raw_tag=None):
    return (bool(parts) and parts[0][0] == "곧이듣" and parts[0][1] in {"VV", "VV-I", "VV-R"}
            and (required_raw_tag is None or parts[0][1] == required_raw_tag))


def intrinsic_events(events):
    return [e for e in events if e["boundary"].get("source") == "intrinsic_lexical" and e["changed"]]


def check_authority(event, wanted, parts):
    boundary = event["boundary"]
    fact = boundary.get("intrinsic_fact") or {}
    donor = boundary.get("donor_origin") or {}
    recipients = boundary.get("recipient_origins") or []
    return (
        boundary["pair"] == [wanted["absolute_boundary"] - 1, wanted["absolute_boundary"]]
        and boundary["parts"] == parts
        and boundary.get("role") == "intrinsic_palatalization"
        and boundary.get("relation") == "intrinsic_lexical_property"
        and boundary.get("source") == "intrinsic_lexical" and boundary.get("article") == "17"
        and boundary.get("lexical_fact") is None
        and boundary.get("intrinsic_mapping") in {"surface_proof", "direct_outside_first_inflection"}
        and boundary.get("canonical_owner_occurrence") == 0
        and fact.get("canonical_owner") == wanted["canonical_owner"]
        and set(fact.get("owner_pos", [])) == {"VV"}
        and fact.get("boundary_offset") == wanted["canonical_boundary_offset"]
        and fact.get("property") == wanted["property"] and fact.get("source_ids") == wanted["source_ids"]
        and donor.get("occurrence") == 0 and donor.get("source_offset") == 0 and donor.get("role") == "coda"
        and donor.get("jamo") == NATIVE_JAMO["coda"]
        and len(recipients) == 2 and {x.get("role") for x in recipients} == {"onset", "vowel"}
        and all(x.get("occurrence") == 0 and x.get("source_offset") == 1 for x in recipients)
        and all(x.get("jamo") == NATIVE_JAMO[x["role"]] for x in recipients)
        and event.get("rule_ids") == (["ko.palatalization"] if event["changed"] else [])
    )


def conditional_authority(record, events, analysis_calls):
    """실제로 관측한 내재 유래만 검사하며 사건의 부재를 통과로 세지 않는다."""
    observed = [event for event in events if event["boundary"].get("source") == "intrinsic_lexical"]
    if not observed:
        return None
    sites = record["expected"]["intrinsic"]["sites"]
    for event in observed:
        boundary = event["boundary"]
        wanted = next((site for site in sites if boundary["pair"] == [site["absolute_boundary"] - 1, site["absolute_boundary"]]), None)
        if wanted is None:
            return False
        originals = []
        for call in analysis_calls:
            if call["text"] == record["input"]["text"]:
                parts = [list(part) for token in call["before"] for part in
                         (token["morphemes"] or [[token["form"], token["tag"]]])]
                originals.append(parts)
        if not originals:
            return None
        if boundary["parts"] not in originals:
            return False
        if not owner_matches(boundary["parts"]) or boundary["word_span"] != [0, len(record["input"]["text"])] or not check_authority(event, wanted, boundary["parts"]):
            return False
    return True


def observe_pipeline(modules, counts):
    """실제 반환값을 바꾸지 않고 공개 변환 안의 분석과 경계 사건만 관측한다."""
    state = {"enabled": False, "analysis": [], "boundaries": [], "events": []}
    original_analyze = modules["analyzer"].KiwiAnalyzer.analyze
    original_apply = modules["consumer"].apply_rule_boundaries

    def analyze(self, text, *args, **kwargs):
        tokens = original_analyze(self, text, *args, **kwargs)
        if state["enabled"]:
            counts["pipeline_analyze"] += 1
            state["analysis"].append({"text": text, "before": jsonable(tokens), "tokens": tokens})
        return tokens

    def apply(boundaries, units, rewrites):
        events = original_apply(boundaries, units, rewrites)
        if state["enabled"]:
            counts["pipeline_apply"] += 1
            state["boundaries"].extend(boundaries)
            state["events"].extend(events)
        return events

    modules["analyzer"].KiwiAnalyzer.analyze = analyze
    for name in ("consumer", "engine", "morphology"):
        if getattr(modules[name], "apply_rule_boundaries", None) is original_apply:
            modules[name].apply_rule_boundaries = apply
    return state


def segments_for(text, modules, control=None):
    model = modules["model"]
    cuts = [(0, 1), (1, len(text))] if control in {"hard", "protected"} else [(0, len(text))]
    return tuple(model.OutputSegment(
        text[a:b], (model.SourceSpan.from_source(text, a, b),),
        model.Handler.PROTECTED if control == "protected" and a == 0 else model.Handler.KOREAN,
        "독립 참조의 원문 소유",
        boundary_before=model.Boundary.HARD if control == "hard" and a == 1 else model.Boundary.MORPHEME,
        boundary_after=model.Boundary.HARD if control == "hard" and b == 1 else model.Boundary.MORPHEME,
    ) for a, b in cuts)


def native_premises(text, annotation, sites, modules, counts, record):
    """출력과 무관하게 원본 분석·기존 문법·대상 직접 대응을 확인한다."""
    segments = segments_for(text, modules)
    units = modules["engine"]._build_units(segments, trace=True)
    certificates = []
    for site in sites:
        start = site["absolute_boundary"] - site["canonical_boundary_offset"]
        first = annotation.starting_at(start)
        counts["word_certify"] += 1
        certificate = modules["roles"].certify_word(annotation, start, units, segments, ())
        certificates.append(certificate)
        if first is None or certificate.lexical_status != "eligible" or certificate.grammar_status != "eligible":
            return False, "원본 분석의 전체 문법·소유 전제가 미충족", certificates
        analysis_facts = record["input"]["analysis_facts"]
        required_raw_tag = analysis_facts.get("raw_owner_tag") if analysis_facts is not None else None
        if not owner_matches(certificate.parts, required_raw_tag) or certificate.prefixed or certificate.derived:
            return False, "동결된 정확 원형·원태그 전제가 미충족", certificates
        if text[start:start + 2] != "곧이" or not first.normalized_start == start < start + 2 <= first.normalized_end:
            return False, "대상 두 문자의 단일 실제 token 직접 대응이 미충족", certificates
        if first.morpheme_spans and not (first.morpheme_spans[0][0] == start and first.morpheme_spans[0][1] >= start + 2):
            return False, "원본 공급 범위가 대상 직접 대응을 증명하지 못함", certificates
        proof = modules["proof"].verified_token_surface(first)
        if proof is not None:
            for physical, role, local in ((start, "coda", 0), (start + 1, "onset", 1), (start + 1, "vowel", 1)):
                jamo = NATIVE_JAMO[role]
                atoms = [atom for atom in proof.atoms if atom.offset == physical and atom.role == role]
                if len(atoms) != 1 or atoms[0].jamo != jamo or len(atoms[0].origins) != 1:
                    return False, "기존 표면 증명의 대상 단독 소유가 미입증", certificates
                origin = atoms[0].origins[0]
                if (origin.occurrence, origin.source_offset, origin.role, origin.jamo) != (0, local, role, jamo):
                    return False, "기존 표면 증명의 대상 원형 대응이 미입증", certificates
        if proof is None and certificate.legacy_kind not in {"licensed_spelling", "simple_inflection", "bare_first_inflection", "opaque_auxiliary"}:
            return False, "기존의 허용된 대응 경로를 제공하지 않음", certificates
        if proof is None:
            cursor, first_part = start, True
            while cursor < certificate.end:
                token = annotation.starting_at(cursor)
                if token is None or not token.morpheme_spans:
                    return False, "제한 불투명 경로의 원래 공급 범위가 없음", certificates
                for begin, end in token.morpheme_spans:
                    if not first_part and begin < start + 2 and end > start:
                        return False, "다른 원형 출현이 대상 두 문자와 공동 범위를 가짐", certificates
                    first_part = False
                cursor = token.normalized_end
        if record["id"] == "R45-IREF-07" and first.normalized_end != certificate.end:
            return False, "동결된 한 덩어리 표현을 원본 분석이 제공하지 않음", certificates
    return True, None, certificates


def native_run(record, binding, modules, counts, token_cache, references):
    result = row(record, "native_event")
    carrier = references[binding["carrier_ref"]]
    text = record["input"]["text"] or carrier["input"]["text"]
    sites = record["expected"]["intrinsic"]["sites"] or carrier["expected"]["intrinsic"]["sites"]
    result["input"]["text"] = text
    if text not in token_cache:
        counts["native_analysis"] += 1
        token_cache[text] = modules["analyzer"].KiwiAnalyzer().analyze_components(text)
    tokens = token_cache[text]
    before = jsonable(tokens)
    result["input"]["analysis_before"] = before
    annotation = modules["morphology"]._Annotation.from_tokens(tokens, text)
    ready, reason, certificates = native_premises(text, annotation, sites, modules, counts, record)
    result["input"]["analysis_after"] = jsonable(tokens)
    result["checks"]["input_preserved"] = same_analysis(before, result["input"]["analysis_after"])
    if not ready:
        result["binding_status"], result["reason"] = "partial", reason
        return result
    control = binding["control"]
    segments = segments_for(text, modules, control)
    units = modules["engine"]._build_units(segments, trace=True)
    pauses = (1,) if control == "pause" else (3,) if control == "nonlocal" else ()
    relations = {(0, 1): "ordinary_liaison"} if control == "read" else {(2, 3): "ordinary_liaison"} if control == "nonlocal" else {}
    result["input"]["controls"] = {"segment_control": control, "pause_boundaries": list(pauses), "reading_relations": [[list(k), v] for k, v in relations.items()]}
    counts["native_certify"] += 1
    decisions = modules["consumer"].certify_rule_boundaries(annotation, units, segments, pauses, reading_relations=relations)
    counts["native_apply"] += 1
    events = modules["consumer"].apply_rule_boundaries(decisions, units, [])
    result["observed"]["boundaries"] = jsonable(decisions)
    result["observed"]["events"] = jsonable(events)
    changed = intrinsic_events(result["observed"]["events"])
    expected = record["expected"]["intrinsic"]
    result["binding_status"] = "bound"
    result["checks"]["intrinsic_event"] = len(changed) == expected["count"]
    if expected["count"]:
        result["checks"]["source_authority"] = (
            len(changed) == len(sites) and all(
                check_authority(event, site, jsonable(certificate.parts))
                and event["boundary"]["word_span"] == [certificate.start, certificate.end]
                for event, site, certificate in zip(sorted(changed, key=lambda e: e["boundary"]["pair"]), sites, certificates)))
    else:
        result["checks"]["source_authority"] = not changed
    if control == "repeat":
        initial = [e for e in jsonable(events) if e["changed"] and e["boundary"]["pair"] == [0, 1] and e["rule_ids"] == ["ko.palatalization"]]
        if not initial:
            result["binding_status"], result["reason"] = "partial", "실제로 이미 소비한 정당한 사건이 없어 반복 전제가 미충족"
            result["checks"]["intrinsic_event"] = result["checks"]["source_authority"] = None
        else:
            counts["native_repeat_apply"] += 1
            repeated = modules["consumer"].apply_rule_boundaries(decisions, units, [])
            result["observed"]["repeat_events"] = jsonable(repeated)
            result["checks"]["intrinsic_event"] = not intrinsic_events(jsonable(repeated))
            result["checks"]["single_consumption"] = not any(e.changed for e in repeated)
            result["checks"]["source_authority"] = not intrinsic_events(jsonable(repeated))
    elif expected["count"]:
        fresh = modules["engine"]._build_units(segments, trace=True)
        counts["native_duplicate_apply"] += 1
        duplicated = modules["consumer"].apply_rule_boundaries(decisions + decisions, fresh, [])
        result["observed"]["duplicate_events"] = jsonable(duplicated)
        result["checks"]["single_consumption"] = len(intrinsic_events(jsonable(duplicated))) == expected["count"]
    result["input"]["analysis_after"] = jsonable(tokens)
    result["checks"]["input_preserved"] = same_analysis(before, result["input"]["analysis_after"])
    return result


def preflight(references):
    """모델·source import 없이 합성 결과로만 checker의 오류 검출을 확인한다."""
    from copy import deepcopy
    site = references["R45-IREF-05"]["expected"]["intrinsic"]["sites"][0]
    parts = [["곧이듣", "VV"], ["다", "EF"]]
    event = {"changed": True, "rule_ids": ["ko.palatalization"], "boundary": {
        "pair": [0, 1], "parts": parts, "role": "intrinsic_palatalization", "relation": "intrinsic_lexical_property",
        "source": "intrinsic_lexical", "article": "17", "lexical_fact": None, "intrinsic_mapping": "surface_proof",
        "canonical_owner_occurrence": 0, "intrinsic_fact": {"canonical_owner": "곧이듣", "owner_pos": ["VV"],
        "boundary_offset": 1, "property": "intrinsic_palatalization", "source_ids": ["nikl_krdict_27702"]},
        "donor_origin": {"occurrence": 0, "source_offset": 0, "role": "coda", "jamo": NATIVE_JAMO["coda"]},
        "recipient_origins": [{"occurrence": 0, "source_offset": 1, "role": "onset", "jamo": NATIVE_JAMO["onset"]},
                              {"occurrence": 0, "source_offset": 1, "role": "vowel", "jamo": NATIVE_JAMO["vowel"]}]}}
    checks = {"정상 유래 판정": check_authority(event, site, parts), "중복 사건 검출": len(intrinsic_events([event, event])) != 1,
              "차단 조건 사건 부재 판정": not intrinsic_events([]), "차단 조건 사건 유출 검출": bool(intrinsic_events([event]))}
    for name, key, value in [("절대 offset 오류", "pair", [5, 6]), ("제29항 오권한", "article", "29"),
                             ("형식 접미사 오권한", "role", "formal"), ("출현 오류", "canonical_owner_occurrence", 1)]:
        changed = deepcopy(event)
        changed["boundary"][key] = value
        checks[name] = not check_authority(changed, site, parts)
    changed = deepcopy(event)
    changed["boundary"]["intrinsic_fact"]["source_ids"] = []
    checks["사전 출처 누락"] = not check_authority(changed, site, parts)
    checks["원 태그 보존"] = same_analysis(parts, deepcopy(parts))
    checks["원 태그 변경"] = not same_analysis(parts, [["곧이듣", "XSM"], ["다", "EF"]])
    full = references["R45-IREF-01"]
    checks["공식 전체 발음 일치"] = score_full(full, full["expected"]["full_output"]["phones"]) is True
    checks["전체 발음 오류 검출"] = score_full(full, "") is False
    checks["사건 참조의 전체 발음 미채점"] = score_full(references["R45-IREF-05"], "") is None
    checks["미지원 참조를 통과로 세지 않음"] = all(v is None for v in row(references["R45-IREF-12"], "unbound")["checks"].values())
    checks["명시 VV 입력을 VV-I로 완화하지 않음"] = not owner_matches([["곧이듣", "VV-I"]], "VV")
    checks["추상 조건의 VV-I 호환"] = owner_matches([["곧이듣", "VV-I"]])
    checks["추상 조건의 VV-R 호환"] = owner_matches([["곧이듣", "VV-R"]])
    checks["비호환 POS 차단"] = not owner_matches([["곧이듣", "VA"]])
    checks["발음 일치로 조건부 권한을 만들지 않음"] = conditional_authority(full, [], []) is None
    calls = [{"text": full["input"]["text"], "before": [{"form": full["input"]["text"], "tag": "VV+EF", "morphemes": parts}]}]
    conditional = deepcopy(event)
    conditional["boundary"]["word_span"] = [0, len(full["input"]["text"])]
    checks["실제 유래 조건부 판정기"] = conditional_authority(full, [conditional], calls) is True
    conditional["changed"], conditional["rule_ids"] = False, []
    checks["미실행 내재 결정의 유래 관측"] = conditional_authority(full, [conditional], calls) is True
    checks["원본 분석 없는 유래를 확정하지 않음"] = conditional_authority(full, [conditional], []) is None
    retagged = deepcopy(conditional)
    retagged["boundary"]["parts"][0][1] = "VV-I"
    checks["사건 parts의 원 태그 변경 검출"] = conditional_authority(full, [retagged], calls) is False
    checks["역할별 native NFD 코드포인트"] = {role: ord(jamo) for role, jamo in NATIVE_JAMO.items()} == {"coda": 0x11AE, "onset": 0x110B, "vowel": 0x1175}
    for role, incompatible in (("coda", 0x3137), ("onset", 0x3147), ("vowel", 0x3163)):
        malformed = deepcopy(event)
        atom = malformed["boundary"]["donor_origin"] if role == "coda" else next(
            atom for atom in malformed["boundary"]["recipient_origins"] if atom["role"] == role)
        atom["jamo"] = chr(incompatible)
        checks["호환 글자의 native " + role + " 오승인 검출"] = not check_authority(malformed, site, parts)
    swapped = deepcopy(event)
    swapped["boundary"]["recipient_origins"][0]["jamo"] = NATIVE_JAMO["vowel"]
    swapped["boundary"]["recipient_origins"][1]["jamo"] = NATIVE_JAMO["onset"]
    checks["onset/vowel 역할 뒤바뀜 검출"] = not check_authority(swapped, site, parts)
    return {"scope": "checker_synthetic_only", "source_imports": 0, "runtime_calls": 0, "passed": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    src, out = args.src.resolve(), args.out.resolve()
    references = {r["id"]: r for r in read_json(HERE / "references.json")["records"]}
    if args.preflight:
        result = preflight(references)
        out.mkdir(parents=True, exist_ok=True)
        write_json_new(out / "checker_preflight.json", result)
        return 0 if result["passed"] else 1
    freeze = read_json(HERE / "support_copy_receipt.json")
    for file, expected_hash in freeze["artifact_sha256"].items():
        if sha256(HERE / file) != expected_hash:
            raise RuntimeError("동결 바인딩 산출물 해시가 다릅니다.")
    plan = read_json(HERE / "binding_plan.json")
    if plan["status"] != "frozen":
        raise RuntimeError("영구 회귀 바인딩이 동결되지 않았습니다.")
    counts = dict.fromkeys(("model_constructors", "kiwi_tokenize", "g2p_convert", "pipeline_analyze", "pipeline_apply", "native_analysis", "word_certify",
                           "native_certify", "native_apply", "native_duplicate_apply", "native_repeat_apply"), 0)
    inventory = source_digest(src)
    modules, model = prepare_runtime(src, counts)
    observer = observe_pipeline(modules, counts)
    g2p, cache, rows = modules["package"].G2P(), {}, []
    for binding in plan["records"]:
        record = references[binding["ref_id"]]
        if binding["route"] == "g2p_full":
            result = row(record, "g2p_full")
            counts["g2p_convert"] += 1
            observer.update(enabled=True, analysis=[], boundaries=[], events=[])
            try:
                actual = g2p.convert(record["input"]["text"])
            finally:
                observer["enabled"] = False
            result["binding_status"] = "bound"
            result["observed"]["full_output"] = actual.surface_pronunciation
            result["observed"]["g2p_result"] = actual.to_dict()
            result["observed"]["boundaries"] = jsonable(observer["boundaries"])
            result["observed"]["events"] = jsonable(observer["events"])
            result["input"]["analysis_before"] = [{"text": call["text"], "tokens": call["before"]} for call in observer["analysis"]]
            result["input"]["analysis_after"] = [{"text": call["text"], "tokens": jsonable(call["tokens"])} for call in observer["analysis"]]
            if observer["analysis"]:
                result["checks"]["input_preserved"] = same_analysis(result["input"]["analysis_before"], result["input"]["analysis_after"])
            result["checks"]["source_authority"] = conditional_authority(record, result["observed"]["events"], observer["analysis"])
            result["checks"]["full_phone"] = score_full(record, actual.surface_pronunciation)
            result["reason"] = "전체 발음과 실제 pipeline의 조건부 내재 유래를 분리해 기록하며 사건 발생 의무는 미채점"
        elif binding["route"] == "native_event":
            result = native_run(record, binding, modules, counts, cache, references)
        else:
            result = row(record, "unbound")
            result["reason"] = binding["status"]
        rows.append(result)
    out.mkdir(parents=True, exist_ok=True)
    write_json_new(out / "execution.json", {"selected_source": str(src), "source_digest": inventory,
        "loaded_project_modules": verify_modules(src), "model": model, "call_counts": counts, "records": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
