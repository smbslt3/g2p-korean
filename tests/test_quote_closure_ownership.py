"""동결된 인용 닫힘·소유 의미와 짧은 명사구 척추 보존을 회귀 검증한다."""

import json
from pathlib import Path
import re
import subprocess
import sys


def _require(condition, identifier, check):
    # 실패에는 사례 본문·발음·자식 프로세스 로그를 포함하지 않는다.
    if not condition:
        raise AssertionError(f"{identifier}:{check}")


def _identifier(value, number):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
        return value
    return f"RECORD-{number}"


def _read_safe_report(execution, references):
    # 기계적으로 비교한 뒤 ID·좌표 검사 결과·개수만 테스트 단언에 전달한다.
    try:
        report = json.loads((execution / "actual_results.json").read_text(encoding="utf-8"))
        summary = json.loads((execution / "parent_safe_summary.json").read_text(encoding="utf-8"))
        reference = json.loads(references.read_text(encoding="utf-8"))
        originals = {row["id"]: row for row in reference["records"]}
        records = []
        for number, row in enumerate(report["records"], 1):
            original = originals[row["id"]]
            executed = row["status"] == "executed"
            records.append({
                "id": _identifier(row["id"], number),
                "status": row["status"],
                "scope": row["scope"],
                "input_preserved": row.get("input_preserved"),
                "original_input_preserved": (
                    row.get("input") == original.get("input")
                    and row.get("supplied_tokens") == original.get("supplied_tokens")
                    and row.get("hard_boundaries") == original.get("hard_boundaries")
                ) if executed else None,
                "supplementary_valid_range_check": row.get("supplementary_valid_range_check"),
                "targets": [{
                    "id": _identifier(target["id"], index),
                    "checks": dict(target["checks"]),
                } for index, target in enumerate(row.get("targets", []), 1)],
            })
        safe = {
            "source": report["source"],
            "source_unchanged": report["source_unchanged"],
            "module_origins": report["module_origins"],
            "initial_module_origins": report["initial_module_origins"],
            "counts": dict(report["counts"]),
            "records": records,
            "summary": summary,
        }
        del report, reference, originals
        return safe
    except Exception:
        raise AssertionError("HARNESS:report_schema") from None


def _execute(support, runner, references, source, execution):
    try:
        completed = subprocess.run(
            [
                sys.executable, "-I", "-B", "-X", "utf8", str(support / runner),
                "--src", str(source), "--out", str(execution),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
    except Exception:
        raise AssertionError("HARNESS:subprocess") from None
    _require(completed.returncode == 0, "HARNESS", f"exit_{completed.returncode}")
    return _read_safe_report(execution, support / references)


def _check_report(report, source, records, calls, targets, unbound):
    _require(Path(report["source"]).resolve() == source, "HARNESS", "source")
    _require(report["source_unchanged"] is True, "HARNESS", "source_unchanged")
    for origins in [report["initial_module_origins"], report["module_origins"]]:
        _require(bool(origins), "HARNESS", "module_count_0")
        _require(all(Path(path).resolve().is_relative_to(source) for path in origins.values()), "HARNESS", "module_origins")

    # 제공 토큰에 대한 제어된 선택이며 실제 Kiwi 분석·모델 포장 관측은 아니다.
    counts = report["counts"]
    _require(counts["selector_calls"] == calls, "HARNESS", "selector_count")
    _require(counts["supplementary_quote_range_calls"] == calls, "HARNESS", "range_count")
    _require(counts["model_constructors_by_runner"] == 0, "HARNESS", "model_count")
    _require(counts["analysis_calls_by_runner"] == 0, "HARNESS", "analysis_count")
    _require(len(report["records"]) == records, "HARNESS", "record_count")

    abstract = {row["id"] for row in report["records"] if row["status"] == "unbound"}
    _require(abstract == unbound, "HARNESS", "unbound_ids")
    executed = [row for row in report["records"] if row["status"] == "executed"]
    _require(len(executed) == calls, "HARNESS", "executed_count")
    _require(sum(len(row["targets"]) for row in executed) == targets, "HARNESS", "target_count")
    for row in report["records"]:
        identifier = row["id"]
        if identifier in unbound:
            _require(row["scope"] == "abstract" and not row["targets"], identifier, "abstract")
            continue
        _require(row["status"] == "executed", identifier, "status")
        _require(row["scope"] == "constructed", identifier, "scope")
        _require(row["input_preserved"] is True, identifier, "tokens_preserved")
        _require(row["original_input_preserved"] is True, identifier, "input_preserved")
        # 원래 검사기의 필수·허용 중첩 범위 판정을 그대로 사용한다.
        _require(row["supplementary_valid_range_check"] is True, identifier, "valid_ranges")
        for target in row["targets"]:
            checks = target["checks"]
            _require(bool(checks) and all(value is True for value in checks.values()), identifier, target["id"])

    summary = report["summary"]
    _require(summary["complete_observation"] is True, "HARNESS", "complete_observation")
    _require(summary["all_nonnull_target_checks_true"] is True, "HARNESS", "semantic_checks")
    _require(summary["input_preservation_all"] is True, "HARNESS", "all_inputs_preserved")
    _require(summary["observed_targets"] == targets, "HARNESS", "observed_targets")
    _require(summary["errors"] == 0, "HARNESS", "error_count")


def test_quote_closure_ownership_and_spine_preservation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = (root / "src").resolve()
    support = root / "tests" / "fixtures" / "quote_closure_ownership"
    original = _execute(support, "run_quote_refs.py", "quote_references.json", source, tmp_path / "quote")
    _check_report(original, source, records=41, calls=40, targets=48, unbound={"QC041"})
    expected = {f"QC{number:03d}" for number in range(1, 41)}
    _require({row["id"] for row in original["records"] if row["status"] == "executed"} == expected, "HARNESS", "original_ids")

    spine = _execute(support, "run_spine_addendum.py", "spine_references.json", source, tmp_path / "spine")
    _check_report(spine, source, records=3, calls=3, targets=4, unbound=set())
    # QC031의 미입증 소유 표식이나 전체 문법 권한의 현재 부재는 고정하지 않는다.
