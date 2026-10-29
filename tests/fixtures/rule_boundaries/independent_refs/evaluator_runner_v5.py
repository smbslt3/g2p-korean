"""네이티브 지표는 보존하고 최초 분석 검증 이후의 합법적 투영을 허용한다."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaluator_binding_v3 as binding
import evaluator_binding_v2 as native_base
import evaluator_runner_v4 as previous
import evaluator_runner_v2 as isolation
import evaluator_runner_v1 as utilities
import input_binding_v2 as controlled_input
import run_refs as frozen


RUNNER_VERSION = "r42-native-source-pinned-v5-once-validated-input"


def score(case, observation):
    result = previous.score(case, observation)
    result["metrics"].pop("separate_word_certificate_object", None)
    word_observation = observation.get("word_certificate_observation", {})
    result["metrics"]["actual_word_certificate_observation"] = word_observation.get("status", "not_observed")
    conditions = observation.get("input_preconditions", {})
    if conditions.get("same_selected_identity_claims") and conditions.get("semantic_identity_delivery") == "not_delivered":
        result["conditional_guard"] = {"state": "unbound_input", "reason_ko": "동일 의미 신원 충돌을 전제로 하는 선언이 실제 런타임에 전달되지 않았다.",
                                       "raw_comparisons_preserved": True}
        result["metrics"]["native_boundary_fields"] = "unbound_input"
    result["available_metrics_passed"] = not any(v == "failed" for v in result["metrics"].values())
    incomplete = any(v in ("unbound", "unbound_input", "partial_unbound") for v in result["metrics"].values())
    result["acceptance"] = ("available_metrics_failed" if not result["available_metrics_passed"] else
                            "incomplete_unbound_requirements" if incomplete else "passed_bound_requirements")
    result["note_ko"] = "네이티브 상태 표기는 그대로 비교한다. 미전달 조건은 미연결 입력이며 별도 단어 인증 객체 부재만으로 임의 거부하지 않는다."
    return result


def synthetic_preflight():
    prior = previous.synthetic_preflight()
    checks = {"기존_네이티브_지표_보존": prior["all_checks_passed"]}

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

    def token(form, tag, start, end):
        return Token(form, tag, start, end, ((form, tag),), ((start, end),))

    original = (token("꽃", "NNG", 0, 1), token("잎", "NNG", 1, 2), token("이랑", "JC", 2, 4))
    payload = {"source": "꽃잎이랑", "pause_boundaries": [1], "dictionary_structure": [],
               "grammatical_structure": [{"relation": "nominal_compound", "left": "p0", "right": "p1"}],
               "canonical_parts": [{"id": f"p{i}", "form": t.form, "tag": t.tag,
                                    "span": [t.normalized_start, t.normalized_end]} for i, t in enumerate(original)],
               "analysis_tokens": [{"form": t.form, "tag": t.tag, "start": t.normalized_start, "end": t.normalized_end,
                                    "morphemes": [list(m) for m in t.morphemes], "morpheme_spans": [list(s) for s in t.morpheme_spans]} for t in original]}
    owner = SimpleNamespace(_Annotation=Annotation)
    descriptor = Annotation.__dict__["from_tokens"]
    with ExitStack() as stack:
        receipt = controlled_input.install_annotation_input(stack, owner, payload, "controlled_structure_supplied")
        initial = Annotation.from_tokens(original, text=payload["source"], nasal_liquid_boundaries=frozenset({3}))
        checks["최초_제공분석_정확검증"] = receipt["initial_validation"]["count"] == 1 and initial.compound_boundaries == frozenset({1})
        expanded = (token("꽃잎", "NNG", 0, 2), original[2])
        changed = Annotation.from_tokens(expanded, text=payload["source"])
        checks["후속_합법_포장변경_허용"] = changed.compound_boundaries == frozenset({1})
        changed_parts = (original[0], token("잎", "NNP", 1, 2), original[2])
        projected = Annotation.from_tokens(changed_parts, text=payload["source"])
        checks["후속_원형투영을_원래신원으로_강제하지않음"] = projected._tokens_starting_at[1] is changed_parts[1]
        subset = Annotation.from_tokens(original[:2], text=payload["source"])
        checks["소유한_부분범위_선언재사용"] = subset.compound_boundaries == frozenset({1})
        outside = Annotation.from_tokens(original[2:], text=payload["source"], compound_boundaries=frozenset({3}))
        checks["범위밖_선언_미전달"] = outside.compound_boundaries == frozenset({3}) and receipt["constructor_calls"][-1]["skipped_outside_owned_range"] == [1]
        gap = Annotation.from_tokens((original[0], original[2]), text=payload["source"])
        checks["소유구멍을_가로지르지않음"] = not gap.compound_boundaries
        checks["최초검증_정확히한번"] = receipt["initial_validation"]["count"] == 1 and sum(c["initial_provider_validation"] for c in receipt["constructor_calls"]) == 1
        checks["다른_경계와_토큰_보존"] = initial.nasal_liquid_boundaries == frozenset({3}) and initial._tokens_starting_at[0] is original[0]
        checks["휴지_입력_불변"] = payload["pause_boundaries"] == [1]

        def reject(label, tokens, text):
            try:
                Annotation.from_tokens(tokens, text=text)
                checks[label] = False
            except controlled_input.InputBindingError:
                checks[label] = True

        reject("후속_원문불일치_거부", expanded, "다른원문")
        reject("후속_범위밖_토큰_거부", (token("이랑", "JC", 2, 5),), payload["source"])
        reject("후속_불리언좌표_거부", (token("꽃", "NNG", False, 1),), payload["source"])
    checks["생성자_복원"] = Annotation.__dict__["from_tokens"] is descriptor
    with ExitStack() as stack:
        controlled_input.install_annotation_input(stack, owner, payload, "controlled_structure_supplied")
        try:
            Annotation.from_tokens(expanded, text=payload["source"])
            checks["최초_검증전_바뀐포장_거부"] = False
        except controlled_input.InputBindingError:
            checks["최초_검증전_바뀐포장_거부"] = True
    with ExitStack() as stack:
        token_only = controlled_input.install_annotation_input(stack, owner, payload, "tokens_only")
        plain = Annotation.from_tokens(expanded, text=payload["source"])
        checks["토큰전용_모드_불변"] = not plain.compound_boundaries and token_only["status"] == "declared_facts_not_delivered"

    @dataclass(frozen=True)
    class SyntheticCertificate:
        parts: tuple
        lexical_status: str
        reason: str

    native_calls = []
    real_object = SyntheticCertificate((("모의", "NNG"),), "eligible", "모의 반환")

    def certify(*args, **kwargs):
        native_calls.append(1)
        return real_object

    target = SimpleNamespace(certify_word=certify)
    captured = []
    with ExitStack() as stack:
        binding.install_word_observers(stack, [("synthetic.certify_word", target, "certify_word")], captured)
        checks["단어인증_추가호출_없음"] = not native_calls
        returned = target.certify_word(None, 0, (), ())
        checks["실제_단어인증_반환객체_보존"] = returned is real_object and len(native_calls) == 1 and captured[0]["certificate"]["lexical_status"] == "eligible"
    checks["단어인증_별칭_복원"] = target.certify_word is certify
    mock_case = {"input": {"source": "모의", "route": "engine.pronounce"},
                 "expected": {"allowed_phones": None, "whole_phone_override": "forbidden",
                              "boundaries": [{"source_pair": [0, 1], "status": "unresolved"}]}}
    mock_observation = {"phone": "모의", "route": "engine.pronounce", "analysis_source": "supplied",
                        "analysis_observation": {"stub_installed": True, "call_count": 0, "calls": []},
                        "completion_observation": {"status": "not_exposed"}, "rule_trace_observation": {"status": "captured"},
                        "whole_phone_override_used": False, "boundaries": [{"source_pair": [0, 1], "values": {"status": "verified"}}],
                        "structure_delivery": {}, "word_certificate_observation": {"status": "not_observed"},
                        "input_preconditions": {"same_selected_identity_claims": [{"identity_claim": "same_selected_identity"}], "semantic_identity_delivery": "not_delivered"}}
    conditional = score(mock_case, mock_observation)
    checks["미전달_의미신원은_미연결입력"] = conditional["metrics"]["native_boundary_fields"] == "unbound_input"
    checks["원래_상태비교_미변조"] = conditional["boundary_checks"][0]["fields"]["status"] == "failed"
    checks["단어객체_부재만으로_임의거부하지않음"] = conditional["available_metrics_passed"] is True
    checks["생산_모듈_미수입"] = not any(isolation.project_name(name) for name in sys.modules)
    return {"synthetic_only": True, "checks": checks, "all_checks_passed": all(checks.values()),
            "prior_native_input_checks": len(prior["checks"]), "source_isolation_checks": prior["source_isolation_checks"],
            "project_runtime_imported": not checks["생산_모듈_미수입"], "kiwi_executed": False}


def run_records(cases, invalid, session, mode):
    rows, constructors = [], []
    for case in cases:
        try:
            observation = binding.evaluate(copy.deepcopy(case["input"]), input_mode=mode)
            row = {**score(case, observation), "observation": observation}
        except controlled_input.InputBindingError as error:
            row = {"available_metrics_passed": False, "acceptance": "input_binding_error", "exception": type(error).__name__, "message": str(error), "metrics": {"input_binding": "failed"}}
        except Exception as error:
            row = {"available_metrics_passed": False, "acceptance": "runtime_or_binding_exception", "exception": type(error).__name__, "message": str(error), "metrics": {"runtime": "failed"}}
        if session.violations:
            raise isolation.SourceIsolationError("선택한 원본 밖의 가져오기가 기록되었습니다.")
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
            "reference_version": "original_frozen_gold_unchanged"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--run-runtime", action="store_true")
    parser.add_argument("--preflight-synthetic", action="store_true")
    parser.add_argument("--input-mode", choices=("tokens_only", "controlled_structure_supplied"), default="tokens_only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        isolation.require_source_option(args.run_runtime, args.src)
    except ValueError as error:
        parser.error(str(error))
    if args.run_runtime and args.preflight_synthetic:
        parser.error("실제 실행과 모의 점검은 분리합니다.")
    _, cases, invalid = utilities._manifest()
    target = utilities._new_report_path(args.report) if args.report is not None else None
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
            result = {"available_metrics_passed": False, "acceptance": "source_isolation_or_runtime_abort", "exception": type(error).__name__, "message": str(error)}
        result["source_origin"] = session.receipt()
        result["audit_cadence"] = {"verified_at_import": True, "initial_after_import": True, "per_record_filesystem_audit": False, "final": True}
    elif args.preflight_synthetic:
        result = synthetic_preflight()
    else:
        print(json.dumps({"freeze_valid": True, "cases": len(cases), "constructor_invalid": len(invalid), "runtime_imported": False}, ensure_ascii=False))
        return 0
    frozen.check_freeze()
    result.update({"created_at_utc": datetime.now(timezone.utc).isoformat(), "runner_version": RUNNER_VERSION,
                   "binding_version": binding.BINDING_VERSION, "input_binding_version": controlled_input.INPUT_BINDING_VERSION,
                   "input_mode": args.input_mode, "python_executable": sys.executable, "python_version": sys.version,
                   "freeze_sha256": utilities._sha(HERE / "FREEZE.json"), "prior_adapter_freeze_sha256": utilities._sha(HERE / "EVALUATOR_V4_FREEZE.json"),
                   "runner_v5_sha256": utilities._sha(HERE / "evaluator_runner_v5.py"), "binding_v3_sha256": utilities._sha(HERE / "evaluator_binding_v3.py"),
                   "input_binding_v2_sha256": utilities._sha(HERE / "input_binding_v2.py"), "native_call_sites": binding.CALL_SITES})
    if target is not None:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("rows", "constructor_rows", "checks", "source_origin")}
    if args.preflight_synthetic:
        summary["repair_check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (result["all_checks_passed"] if args.preflight_synthetic else result["available_metrics_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
