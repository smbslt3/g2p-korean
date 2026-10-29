"""연결된 공개 관찰과 미연결 권한 지표를 분리하는 버전 1 실행기다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import evaluator_binding_v1 as binding
import run_refs as frozen


ROOT = Path(__file__).resolve().parent
RUNNER_VERSION = "r42-available-metrics-v1"


def score_available(case, observation):
    """제공된 관찰만 평가하고 미연결 항목을 런타임 실패로 세지 않는다."""
    expected = case["expected"]
    metrics = {}
    phones = expected["allowed_phones"]
    metrics["phone"] = ("not_required" if phones is None else
                        "passed" if observation.get("phone") in phones else "failed")
    metrics["public_route"] = "passed" if observation.get("route") == case["input"]["route"] else "failed"
    analysis = observation.get("analysis_observation", {})
    calls = analysis.get("calls")
    valid_calls = (
        isinstance(calls, list)
        and type(analysis.get("call_count")) is int
        and analysis["call_count"] == len(calls)
        and all(isinstance(c, dict) and c.get("text") == case["input"]["source"]
                and type(c.get("split_complex")) is bool and type(c.get("saisiot")) is bool for c in calls)
    )
    metrics["supplied_analysis_capture"] = (
        "passed" if observation.get("analysis_source") == "supplied"
        and analysis.get("stub_installed") is True and valid_calls else "failed"
    )
    trace = observation.get("rule_trace_observation", {})
    metrics["rule_trace_capture"] = "captured" if trace.get("status") == "captured" else "not_exposed"
    complete = observation.get("completion_observation", {})
    metrics["public_completion"] = (
        "not_exposed" if complete.get("status") != "captured" else
        "passed" if complete.get("value") is True else "failed"
    )
    # 새 증명 API를 읽지 않은 버전 1은 권한을 바인딩할 수 없다.
    metrics["boundary_authority"] = "unbound" if expected["boundaries"] else "not_required"
    metrics["whole_phone_override_audit"] = "unbound"
    available_failed = any(value == "failed" for value in metrics.values())
    return {"metrics": metrics, "available_metrics_passed": not available_failed,
            "acceptance": "incomplete_unbound_authority",
            "note_ko": "발음 통과만으로 일반 소비자·단일 소비·치환 제거가 입증되지 않는다."}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_report_path(path):
    target = path.resolve()
    protected = set(frozen.check_freeze()["sha256"]) | {"FREEZE.json"}
    if target.parent != ROOT or target.name in protected or target.exists():
        raise ValueError("새 관찰 결과는 독립 참조 폴더의 보호되지 않은 새 파일이어야 합니다.")
    return target


def _manifest():
    manifest = frozen.check_freeze()
    cases = frozen.read_jsonl("cases.jsonl")
    invalid = frozen.read_jsonl("constructor_invalid.jsonl")
    frozen.validate(cases, invalid, manifest)
    return manifest, cases, invalid


def synthetic_preflight():
    """프로젝트를 가져오지 않고 모의 DTO의 직렬화와 상태 분리만 확인한다."""
    @dataclass(frozen=True)
    class SyntheticRewrite:
        before: str
        after: str
        rule_id: str

    @dataclass(frozen=True)
    class SyntheticEngineResult:
        rewrites: tuple

    @dataclass(frozen=True)
    class SyntheticPublicResult:
        complete: bool

    payload = {"source": "모의", "route": "engine.pronounce", "pause_boundaries": []}
    calls = [{"text": "모의", "split_complex": True, "saisiot": True}]
    traces = (SyntheticRewrite("모의", "모의", "synthetic.trace"),
              SyntheticRewrite("모의", "모의", "synthetic.trace"))
    seen = []

    def engine_stub(received):
        seen.append(copy.deepcopy(received))
        return "모의", SyntheticEngineResult(traces), calls

    original_keys = set(sys.modules)
    observation = binding.observe_public(payload, invoke=engine_stub)
    checks = {
        "모의_제공입력만_전달": seen == [payload],
        "기대값_미전달": "expected" not in seen[0],
        "공개_발음_보존": observation["phone"] == "모의",
        "규칙_사건수_보존": observation["rule_trace_observation"]["count"] == 2,
        "규칙_ID_빈도_보존": observation["rule_trace_observation"]["rule_id_counts"] == {"synthetic.trace": 2},
        "분석_호출수_보존": observation["analysis_observation"]["call_count"] == 1,
        "새_권한_미연결": observation["authority_binding"] == binding.AUTHORITY_BINDING,
        "치환_사용여부_미추정": observation["whole_phone_override_used"] is None,
        "경계_증명_미조작": observation["boundaries"] is None,
    }
    public_payload = {**payload, "route": "G2P"}
    public = binding.observe_public(public_payload, invoke=lambda _: ("모의", SyntheticPublicResult(True), []))
    checks["공개_DTO_규칙추적_미노출"] = public["rule_trace_observation"]["status"] == "not_exposed_by_result_dto"
    checks["실제_빈_호출수_보존"] = public["analysis_observation"]["call_count"] == 0
    checks["공개_완료상태_보존"] = public["completion_observation"] == {"status": "captured", "value": True}
    mock_case = {"input": payload, "expected": {"allowed_phones": ["모의"], "boundaries": [{"source_pair": [0, 1]}]}}
    score = score_available(mock_case, observation)
    checks["연결_발음_지표_통과"] = score["metrics"]["phone"] == "passed"
    checks["미연결을_런타임실패로_세지않음"] = score["available_metrics_passed"] and score["metrics"]["boundary_authority"] == "unbound"
    checks["전체_수용_미주장"] = score["acceptance"] == "incomplete_unbound_authority"
    wrong = score_available(mock_case, {**observation, "phone": "불일치"})
    checks["실제_발음불일치_구분"] = wrong["metrics"]["phone"] == "failed" and not wrong["available_metrics_passed"]
    wrong_route = score_available(mock_case, {**observation, "route": "GAP"})
    checks["붙은단어_GAP_우회_거부"] = wrong_route["metrics"]["public_route"] == "failed"
    absent = score_available(mock_case, {**observation, "analysis_observation": {}})
    checks["분석_호출_증거누락_구분"] = absent["metrics"]["supplied_analysis_capture"] == "failed"
    introduced = sorted(name for name in set(sys.modules) - original_keys if name == "g2p_ko" or name.startswith("g2p_ko."))
    checks["프로젝트_런타임_미수입"] = not introduced and not any(name == "g2p_ko" or name.startswith("g2p_ko.") for name in sys.modules)
    return {"runner_version": RUNNER_VERSION, "binding_version": binding.BINDING_VERSION,
            "checks": checks, "all_checks_passed": all(checks.values()),
            "project_runtime_imported": False if checks["프로젝트_런타임_미수입"] else True,
            "kiwi_executed": False, "new_authority_binding": "unbound", "synthetic_only": True}


def run_runtime(cases, invalid):
    """최종 R41 수락 뒤 별도로 허가된 호출에서만 프로젝트를 실행한다."""
    rows = []
    for case in cases:
        try:
            observation = binding.evaluate(copy.deepcopy(case["input"]))
            scored = score_available(case, observation)
            row = {**scored, "observation": observation}
        except Exception as error:
            row = {"available_metrics_passed": False, "acceptance": "runtime_or_binding_exception",
                   "exception": type(error).__name__, "message": str(error), "metrics": {"runtime": "failed"}}
        rows.append({"case_id": case["case_id"], "evidence_scope": case["evidence_scope"], **row})
    constructors = []
    for case in invalid:
        try:
            actual = binding.construct_invalid({"model": case["model"], "args": copy.deepcopy(case["args"])})
        except Exception as error:
            actual = type(error).__name__
        constructors.append({"case_id": case["case_id"], "evidence_scope": "constructor_only",
                             "passed": actual == case["expected_exception"], "observed_exception": actual})
    by_scope = defaultdict(Counter)
    for row in rows:
        for metric, state in row["metrics"].items():
            by_scope[row["evidence_scope"]][metric + ":" + state] += 1
    return {"rows": rows, "constructor_rows": constructors,
            "by_scope": {k: dict(v) for k, v in by_scope.items()},
            "acceptance": "incomplete_unbound_authority",
            "available_metrics_passed": all(r["available_metrics_passed"] for r in rows)
                                        and all(r["passed"] for r in constructors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-synthetic", action="store_true")
    parser.add_argument("--run-runtime", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    _, cases, invalid = _manifest()
    if args.preflight_synthetic and args.run_runtime:
        parser.error("모의 점검과 런타임 실행은 한 호출에서 섞지 않습니다.")
    if args.run_runtime:
        if args.report is None:
            parser.error("런타임 실행에는 새 --report 경로가 필요합니다.")
        target = _new_report_path(args.report)
        result = run_runtime(cases, invalid)
    elif args.preflight_synthetic:
        target = _new_report_path(args.report) if args.report is not None else None
        result = synthetic_preflight()
    else:
        print(json.dumps({"freeze_valid": True, "cases": len(cases), "constructor_invalid": len(invalid),
                          "runtime_imported": False, "new_authority_binding": "unbound"}, ensure_ascii=False))
        return 0
    frozen.check_freeze()
    result.update({"created_at_utc": datetime.now(timezone.utc).isoformat(), "runner_version": RUNNER_VERSION,
                   "binding_version": binding.BINDING_VERSION, "freeze_sha256": _sha(ROOT / "FREEZE.json"),
                   "binding_sha256": _sha(ROOT / "evaluator_binding_v1.py"),
                   "runner_sha256": _sha(ROOT / "evaluator_runner_v1.py"),
                   "helper_sha256": _sha(ROOT / "public_entrypoints_helper.py")})
    if target is not None:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("rows", "constructor_rows", "checks")}
    if args.preflight_synthetic:
        summary["check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    passed = result["all_checks_passed"] if args.preflight_synthetic else result["available_metrics_passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
