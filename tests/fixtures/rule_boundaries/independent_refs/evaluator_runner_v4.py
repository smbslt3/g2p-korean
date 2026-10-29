"""고정 네이티브 API의 관찰을 연결하고 원본 검사는 처음과 끝에 수행한다."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaluator_binding_v2 as binding
import evaluator_runner_v1 as public_metrics
import evaluator_runner_v2 as isolation
import run_refs as frozen
import input_binding_v1 as controlled_input


RUNNER_VERSION = "r42-native-source-pinned-v4"
API_METADATA = HERE.parent / "cleanroom/boundary_rules/candidate04/Boundary_API_KO.json"


def score(case, observation):
    result = public_metrics.score_available(case, observation)
    result["metrics"].pop("boundary_authority", None)
    delivery = observation.get("structure_delivery", {})
    if delivery.get("mode") == "controlled_structure_supplied" and delivery.get("declared_nominal_compounds"):
        result["metrics"]["declared_compound_input_delivery"] = "passed" if delivery.get("status") == "controlled_structure_supplied" and delivery.get("constructor_calls") else "failed"
    else:
        result["metrics"]["declared_compound_input_delivery"] = "not_delivered_tokens_only" if delivery.get("declared_nominal_compounds") else "not_required"
    override = observation.get("whole_phone_override_used")
    result["metrics"]["whole_phone_override_audit"] = (
        "unbound" if type(override) is not bool else
        "failed" if case["expected"]["whole_phone_override"] == "forbidden" and override else "passed"
    )
    checks = []
    for expected in case["expected"]["boundaries"]:
        records = [b for b in observation.get("boundaries", []) if b["source_pair"] == expected["source_pair"]]
        field_checks = {}
        for key, value in expected.items():
            observed_key = "consumed_articles" if key == "forbidden_articles" else key
            if not records or any(observed_key not in b["values"] for b in records):
                state = "unbound"
            elif key == "forbidden_articles":
                state = "failed" if any(set(value).intersection(b["values"][observed_key]) for b in records) else "passed"
            else:
                state = "passed" if all(b["values"][key] == value for b in records) else "failed"
            field_checks[key] = state
        checks.append({"source_pair": expected["source_pair"], "native_record_count": len(records), "fields": field_checks})
    result["boundary_checks"] = checks
    result["metrics"]["native_boundary_fields"] = (
        "not_required" if not checks else
        "failed" if any("failed" in row["fields"].values() for row in checks) else
        "partial_unbound" if any("unbound" in row["fields"].values() for row in checks) else "passed"
    )
    result["metrics"]["separate_word_certificate_object"] = "unbound" if checks else "not_required"
    result["available_metrics_passed"] = not any(v == "failed" for v in result["metrics"].values())
    result["acceptance"] = "available_metrics_failed" if not result["available_metrics_passed"] else "incomplete_if_native_facts_unavailable"
    result["note_ko"] = "별도 WordCertificate 객체와 정의되지 않은 권한 투영은 미연결로 남기며 실패나 성공으로 대체하지 않는다."
    return result


def synthetic_preflight():
    """실제 정의와 같은 필드의 모의 DTO와 호출 별칭만 사용한다."""
    @dataclass(frozen=True)
    class Atom:
        occurrence: int
        source_offset: int
        role: str
        jamo: str

    @dataclass(frozen=True)
    class Occurrence:
        index: int
        form: str
        tag: str
        raw_span: tuple

    @dataclass(frozen=True)
    class ProvenAtom:
        jamo: str
        offset: int
        role: str
        origins: tuple

    @dataclass(frozen=True)
    class Step:
        boundary: tuple
        rule_id: str
        inputs: tuple
        outputs: tuple
        before_origins: tuple
        after_origins: tuple
        deleted: tuple

    @dataclass(frozen=True)
    class Proof:
        start: int
        end: int
        parts: tuple
        morpheme_spans: tuple
        occurrences: tuple
        regenerated_spans: tuple
        atoms: tuple
        steps: tuple

    @dataclass(frozen=True)
    class Grammar:
        lexical_status: str = "eligible"
        final_category: str = "V"
        possible_categories: frozenset = frozenset({"V"})

    @dataclass(frozen=True)
    class Boundary:
        pair: tuple
        word_span: tuple
        parts: tuple
        role: str
        relation: str
        source: str
        status: str
        applicability: str
        reason: str
        article: str
        donor_origin: Atom
        recipient_origins: tuple
        surface_proofs: tuple
        grammar: Grammar
        attachment_span: tuple | None = None

    @dataclass(frozen=True)
    class Event:
        boundary: Boundary
        status: str
        applicability: str
        reason: str
        changed: bool
        rule_ids: tuple

    @dataclass(frozen=True)
    class NativeResult:
        rewrites: tuple

    @dataclass(frozen=True)
    class PublicResult:
        complete: bool = True

    donor = Atom(0, 0, "coda", "ᇀ")
    i = Atom(1, 0, "vowel", "ᅵ")
    eo = Atom(2, 0, "vowel", "ᅥ")
    removed = Atom(2, 0, "onset", "ᄋ")
    parts = (("붙", "VV"), ("이", "XSV"), ("어", "EC"))
    raw_spans = ((0, 1), (1, 2), (1, 2))
    step = Step((1, 2), "synthetic.contraction", ("이", "어"), ("여",), ((i,), (eo,)), ((i, eo),), (removed,))
    proof = Proof(0, 2, parts, raw_spans, tuple(Occurrence(n, *p, raw_spans[n]) for n, p in enumerate(parts)),
                  ((0, 1), (1, 2), (2, 2)), (ProvenAtom("ᅧ", 1, "vowel", (i, eo)),), (step,))
    boundary = Boundary((0, 1), (0, 2), parts, "formal_suffix_i", "formal_suffix_derivation",
                        "direct_analysis", "verified", "eligible", "모의", "17", donor, (i, eo), (proof,), Grammar())
    event = Event(boundary, "applied", "eligible", "모의", True, ("synthetic.17",))
    payload = {"source": "붙여", "route": "G2P", "pause_boundaries": [], "dictionary_structure": [],
               "canonical_parts": [{"id": f"p{n}", "form": p[0], "tag": p[1], "span": list(raw_spans[n])} for n, p in enumerate(parts)]}
    order = []
    engine = SimpleNamespace()
    morphology = SimpleNamespace(certify_rule_boundaries=lambda *a, **k: (boundary,))

    def record(*args, **kwargs):
        args[0].append({"rule_id": args[5]})

    def lexical(units, matches, rewrites, segments, pauses):
        order.append("lexical")
        if matches:
            engine._record(rewrites, units, 0, 1, "모의", "synthetic.lexical")

    def apply(*args, **kwargs):
        order.append("apply")
        return (event,)

    lexical_enabled = [False]

    def pronounce(*args, **kwargs):
        decisions = morphology.certify_rule_boundaries(None, (), ())
        rewrites = []
        engine._apply_lexical_pronunciations((), ("모의 매치",) if lexical_enabled[0] else (), rewrites, (), ())
        engine.apply_rule_boundaries(decisions, (), rewrites)
        engine._record(rewrites, (), 0, 1, "모의", "synthetic.generic")
        return NativeResult(tuple(rewrites))

    engine._record = record
    engine._apply_lexical_pronunciations = lexical
    engine.apply_rule_boundaries = apply
    engine.pronounce = pronounce
    pipeline = SimpleNamespace(pronounce=pronounce)
    aliases = {"engine": engine, "pipeline": pipeline, "morphology": morphology}
    original_apply = engine.apply_rule_boundaries

    def invoke(received):
        (pipeline.pronounce if received["route"] == "G2P" else engine.pronounce)(None)
        return "모의", PublicResult(), [{"text": received["source"], "split_complex": True, "saisiot": True}]

    observation = binding.evaluate_native(payload, aliases=aliases, invoke=invoke)
    values = observation["boundaries"][0]["values"]
    preserved = observation["boundaries"][0]["native_evidence"]["surface_proofs"][0]
    checks = {
        "인증_실제별칭_호출": len(observation["native_evidence"]["certify_calls"]) == 1,
        "적용_engine_별칭_호출": len(observation["native_evidence"]["apply_calls"]) == 1,
        "기존치환_뒤_적용_관찰": order[:2] == ["lexical", "apply"],
        "G2P_실제_발음결과_포착": observation["native_evidence"]["pronunciations"][0]["alias"] == "pipeline.pronounce",
        "실제_규칙추적_포착": observation["rule_trace_observation"]["count"] == 1,
        "일반_ID를_치환으로_세지않음": observation["whole_phone_override_used"] is False,
        "원형_ID_대응": values["left_origin"] == "p0" and values["right_origin"] == "p1",
        "원형_받침_NFD_보존": values["original_coda"] == "ㅌ",
        "수신_원형_보존": values["original_receiver"] == "이",
        "원시범위_보존": values["right_origin_span"] == [1, 2],
        "재생성범위_별도보존": preserved["regenerated_spans"][-1] == [2, 2] and preserved["occurrences"][-1]["raw_span"] == [1, 2],
        "삭제_유래_보존": preserved["steps"][0]["deleted"][0]["jamo"] == "ᄋ",
        "공동유래_축약_관찰": values["contracted"] is True,
        "네이티브_사건_단일소비": values["consumption_count"] == 1 and values["consumed_articles"] == ["17"],
        "별도_단어인증_미조작": observation["boundaries"][0]["native_evidence"]["word_certificate"] is None,
        "집합_DTO_직렬화": observation["boundaries"][0]["native_evidence"]["grammar"]["possible_categories"] == ["V"],
        "호출별칭_복원": engine.apply_rule_boundaries is original_apply,
    }
    lexical_enabled[0] = True
    second = binding.evaluate_native({**payload, "route": "engine.pronounce"}, aliases=aliases, invoke=invoke)
    checks["실제_치환_record_관찰"] = second["whole_phone_override_used"] is True and len(second["native_evidence"]["lexical_application_records"]) == 1
    checks["engine_발음결과_포착"] = second["native_evidence"]["pronunciations"][0]["alias"] == "engine.pronounce"
    expected = {"input": payload, "expected": {"allowed_phones": ["모의"], "whole_phone_override": "forbidden",
                "boundaries": [{"source_pair": [0, 1], "role": "formal_suffix_i", "selected_article": "17", "consumption_count": 1}]}}
    checks["실제_치환사용_실패_분리"] = score(expected, second)["metrics"]["whole_phone_override_audit"] == "failed"
    expected["expected"]["boundaries"][0]["consumption_count"] = 2
    checks["실제_소비수_불일치_분리"] = score(expected, observation)["metrics"]["native_boundary_fields"] == "failed"
    local_boundary = copy.deepcopy(observation["boundaries"][0]["native_evidence"]["boundary_record"])
    local_boundary["source"] = "analysis_local_attachment"
    local_boundary["attachment_span"] = [0, 2]
    fake_capture = SimpleNamespace(applications=observation["native_evidence"]["apply_calls"])
    local_projection = binding.project_boundary(payload, local_boundary, fake_capture)
    checks["국소부착을_전체단어로_확대하지않음"] = "word_span" not in local_projection["values"] and local_projection["native_attachment_span"] == [0, 2]
    unknown_source = {**local_boundary, "source": "synthetic_unknown_source"}
    checks["미정의_권한출처_미추정"] = "authority" not in binding.project_boundary(payload, unknown_source, fake_capture)["values"]
    missing_raw = copy.deepcopy(local_boundary)
    missing_raw["surface_proofs"][0]["occurrences"][1]["raw_span"] = None
    checks["재생성범위를_원시범위로_대체하지않음"] = "right_origin_span" not in binding.project_boundary(payload, missing_raw, fake_capture)["values"]

    @dataclass(frozen=True)
    class Token:
        form: str
        tag: str
        normalized_start: int
        normalized_end: int
        morphemes: tuple
        morpheme_spans: tuple

    @dataclass(frozen=True)
    class Annotation:
        _tokens_ending_at: dict
        _tokens_starting_at: dict
        _tokens_covering: dict
        text: str = ""
        compound_boundaries: frozenset = frozenset()
        nasal_liquid_boundaries: frozenset = frozenset()

        @classmethod
        def from_tokens(cls, tokens, text="", compound_boundaries=frozenset(), nasal_liquid_boundaries=frozenset()):
            return cls({t.normalized_end: t for t in tokens}, {t.normalized_start: t for t in tokens},
                       {i: t for t in tokens for i in range(t.normalized_start, t.normalized_end)},
                       text, compound_boundaries, nasal_liquid_boundaries)

    tokens = (Token("솜", "NNG", 0, 1, (("솜", "NNG"),), ((0, 1),)),
              Token("이불", "NNG", 1, 3, (("이불", "NNG"),), ((1, 3),)))
    controlled_payload = {"source": "솜이불", "route": "engine.pronounce", "pause_boundaries": [1],
                          "dictionary_structure": [], "canonical_parts": [
                              {"id": "p0", "form": "솜", "tag": "NNG", "span": [0, 1]},
                              {"id": "p1", "form": "이불", "tag": "NNG", "span": [1, 3]}],
                          "analysis_tokens": [{"form": t.form, "tag": t.tag, "start": t.normalized_start,
                                               "end": t.normalized_end, "morphemes": [list(m) for m in t.morphemes],
                                               "morpheme_spans": [list(s) for s in t.morpheme_spans]} for t in tokens],
                          "grammatical_structure": [{"relation": "nominal_compound", "left": "p0", "right": "p1"}] * 2}
    from contextlib import ExitStack
    constructor_owner = SimpleNamespace(_Annotation=Annotation)
    original_constructor = Annotation.__dict__["from_tokens"]
    with ExitStack() as stack:
        delivery = controlled_input.install_annotation_input(stack, constructor_owner, controlled_payload, "controlled_structure_supplied")
        actual = Annotation.from_tokens(tokens, text="솜이불", nasal_liquid_boundaries=frozenset({2}))
        checks["선언된_합성경계만_전달"] = actual.compound_boundaries == frozenset({1})
        checks["중복_선언_단일좌표"] = len(delivery["declared_nominal_compounds"]) == 2 and delivery["constructor_calls"][0]["declared_boundaries"] == [1]
        checks["실제클래스와_원래맵_보존"] = isinstance(actual, Annotation) and actual._tokens_starting_at[0] is tokens[0]
        checks["다른_경계_필드_보존"] = actual.nasal_liquid_boundaries == frozenset({2})
        checks["휴지입력_그대로_유지"] = controlled_payload["pause_boundaries"] == [1]
        try:
            Annotation.from_tokens(tokens, text="다른원문")
            checks["불일치_원문_거부"] = False
        except controlled_input.InputBindingError:
            checks["불일치_원문_거부"] = True
        wrong_tokens = (Token("솜", "VV", 0, 1, (("솜", "VV"),), ((0, 1),)), tokens[1])
        try:
            Annotation.from_tokens(wrong_tokens, text="솜이불")
            checks["불일치_태그_거부"] = False
        except controlled_input.InputBindingError:
            checks["불일치_태그_거부"] = True
    checks["공통_생성자_복원"] = Annotation.__dict__["from_tokens"] is original_constructor
    with ExitStack() as stack:
        token_delivery = controlled_input.install_annotation_input(stack, constructor_owner, controlled_payload, "tokens_only")
        checks["기존_토큰전용_입력_보존"] = not Annotation.from_tokens(tokens, text="솜이불").compound_boundaries and token_delivery["status"] == "declared_facts_not_delivered"
    with ExitStack() as stack:
        absent_fact = {**controlled_payload, "grammatical_structure": []}
        controlled_input.install_annotation_input(stack, constructor_owner, absent_fact, "controlled_structure_supplied")
        checks["N인접에서_합성_발명금지"] = not Annotation.from_tokens(tokens, text="솜이불").compound_boundaries
    checks["사전자료_주입금지"] = delivery["dictionary_structure_injected"] is False
    old_morphology = SimpleNamespace(_Annotation=Annotation)
    old_engine = SimpleNamespace(_record=lambda *a, **k: None, _apply_lexical_pronunciations=lambda *a, **k: None)

    def old_pronounce(*args, **kwargs):
        old_morphology._Annotation.from_tokens(tokens, text="솜이불")
        return NativeResult(())

    old_engine.pronounce = old_pronounce
    old_pipeline = SimpleNamespace(pronounce=old_pronounce)

    def old_invoke(received):
        old_engine.pronounce(None)
        return "모의", PublicResult(), []

    old_observation = binding.evaluate_native(controlled_payload, aliases={"morphology": old_morphology, "engine": old_engine, "pipeline": old_pipeline}, invoke=old_invoke, input_mode="controlled_structure_supplied")
    checks["이전API에도_같은_입력기본연산"] = old_observation["structure_delivery"]["status"] == "controlled_structure_supplied"
    checks["이전API_새인증_미조작"] = old_observation["native_api_available"] == {"certify": False, "apply": False} and old_observation["boundaries"] == []
    checks["생산_모듈_미수입"] = not any(isolation.project_name(name) for name in sys.modules)
    isolation_result = isolation.synthetic_preflight()
    checks["기존_원본격리_모의점검"] = isolation_result["all_checks_passed"]
    return {"synthetic_only": True, "checks": checks, "all_checks_passed": all(checks.values()),
            "source_isolation_checks": len(isolation_result["checks"]), "project_runtime_imported": not checks["생산_모듈_미수입"],
            "kiwi_executed": False, "tested_input_modes": ["tokens_only", "controlled_structure_supplied"]}


def run_records(cases, invalid, session, input_mode):
    rows, constructors = [], []
    for case in cases:
        try:
            observation = binding.evaluate(copy.deepcopy(case["input"]), input_mode=input_mode)
            row = {**score(case, observation), "observation": observation}
        except controlled_input.InputBindingError as error:
            row = {"available_metrics_passed": False, "acceptance": "input_binding_error", "exception": type(error).__name__, "message": str(error), "metrics": {"input_binding": "failed"}}
        except Exception as error:
            row = {"available_metrics_passed": False, "acceptance": "runtime_or_binding_exception",
                   "exception": type(error).__name__, "message": str(error), "metrics": {"runtime": "failed"}}
        if session.violations:
            raise isolation.SourceIsolationError("실제 가져오기에서 선택 원본 위반이 기록되었습니다.")
        rows.append({"case_id": case["case_id"], "evidence_scope": case["evidence_scope"], **row})
    for case in invalid:
        try:
            actual = binding.construct_invalid({"model": case["model"], "args": copy.deepcopy(case["args"])})
        except Exception as error:
            actual = type(error).__name__
        constructors.append({"case_id": case["case_id"], "evidence_scope": "constructor_only", "passed": actual == case["expected_exception"], "observed_exception": actual})
    counts = defaultdict(Counter)
    for row in rows:
        for metric, state in row["metrics"].items():
            counts[row["evidence_scope"]][metric + ":" + state] += 1
    return {"rows": rows, "constructor_rows": constructors, "by_scope": {k: dict(v) for k, v in counts.items()},
            "available_metrics_passed": all(r["available_metrics_passed"] for r in rows) and all(r["passed"] for r in constructors),
            "acceptance": "consult_bound_field_checks_and_explicit_unavailable_facts"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--run-runtime", action="store_true")
    parser.add_argument("--preflight-synthetic", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--input-mode", choices=("tokens_only", "controlled_structure_supplied"), default="tokens_only")
    args = parser.parse_args()
    try:
        isolation.require_source_option(args.run_runtime, args.src)
    except ValueError as error:
        parser.error(str(error))
    if args.run_runtime and args.preflight_synthetic:
        parser.error("실제 실행과 모의 점검은 분리합니다.")
    _, cases, invalid = public_metrics._manifest()
    target = public_metrics._new_report_path(args.report) if args.report is not None else None
    if args.run_runtime:
        if target is None:
            parser.error("실제 실행에는 새 결과 경로가 필요합니다.")
        session = isolation.SourceSession(args.src)
        try:
            with session:
                binding.prepare_native_imports()
                session.audit()
                result = run_records(cases, invalid, session, args.input_mode)
        except Exception as error:
            result = {"available_metrics_passed": False, "acceptance": "source_isolation_or_runtime_abort",
                      "exception": type(error).__name__, "message": str(error)}
        result["source_origin"] = session.receipt()
        result["audit_cadence"] = {"verified_at_import": True, "initial_after_import": True, "per_record_filesystem_audit": False, "final": True}
    elif args.preflight_synthetic:
        result = synthetic_preflight()
    else:
        print(json.dumps({"freeze_valid": True, "cases": len(cases), "constructor_invalid": len(invalid), "runtime_imported": False}, ensure_ascii=False))
        return 0
    frozen.check_freeze()
    result.update({"created_at_utc": datetime.now(timezone.utc).isoformat(), "runner_version": RUNNER_VERSION,
                   "input_mode": args.input_mode,
                   "binding_version": binding.BINDING_VERSION, "python_executable": sys.executable, "python_version": sys.version,
                   "freeze_sha256": public_metrics._sha(HERE / "FREEZE.json"), "runner_v4_sha256": public_metrics._sha(HERE / "evaluator_runner_v4.py"),
                   "binding_v2_sha256": public_metrics._sha(HERE / "evaluator_binding_v2.py"),
                   "input_binding_v1_sha256": public_metrics._sha(HERE / "input_binding_v1.py"),
                   "source_guard_v2_sha256": public_metrics._sha(HERE / "evaluator_runner_v2.py"),
                   "approved_native_api_sha256": public_metrics._sha(API_METADATA), "native_call_sites": binding.CALL_SITES})
    if target is not None:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("rows", "constructor_rows", "checks", "source_origin")}
    if args.preflight_synthetic:
        summary["native_check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (result["all_checks_passed"] if args.preflight_synthetic else result["available_metrics_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
