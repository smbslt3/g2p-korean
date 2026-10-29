"""동결된 긴 부정의 의미·구조·부재 guard를 원입력 그대로 회귀 검증한다."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback


def _require(condition, identifier, check):
    # 본문/뜻/발음/원반환 대신 ID와 검사명만 실패 메시지에 쓴다.
    if not condition:
        raise AssertionError(f"{identifier}:{check}")


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", value) else "HARNESS"


def _verify_support(support, receipt):
    for name, expected in receipt["files_sha256"].items():
        actual = hashlib.sha256((support / name).read_bytes()).hexdigest()
        _require(actual == expected, "HARNESS", "fixture_bytes")


def _execute(support, source, execution, private):
    # 실패 때에도 잘리지 않은 원참고/반환/로그를 pytest 임시 비공개 경로에 남긴다.
    shutil.copyfile(support / "references.json", private / "frozen_references_private.json")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", str(support / "run_controlled_selector.py"),
             "--src", str(source), "--refs", str(support / "references.json"), "--out", str(execution)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        (private / "stdout_private.txt").write_text(completed.stdout, encoding="utf-8")
        (private / "stderr_private.txt").write_text(completed.stderr, encoding="utf-8")
        returncode = completed.returncode
        del completed
    except Exception as error:
        (private / "execution_exception_private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if isinstance(error, subprocess.TimeoutExpired):
            for name, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                if value is not None:
                    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
                    (private / f"{name}_private.txt").write_text(text, encoding="utf-8")
        raise AssertionError("HARNESS:subprocess") from None
    try:
        summary = json.loads((execution / "parent_safe_controlled_summary.json").read_text(encoding="utf-8"))
    except Exception:
        raise AssertionError("HARNESS:summary_schema") from None
    return returncode, summary


def test_long_negative_complex_semantics_and_structural_guards(tmp_path):
    root = Path(__file__).resolve().parents[1]
    support = root / "tests" / "fixtures" / "long_negative_complex"
    source = (root / "src").resolve()
    receipt = json.loads((support / "support_copy_receipt.json").read_text(encoding="utf-8"))
    _verify_support(support, receipt)
    execution = tmp_path / "controlled_private"
    returncode, summary = _execute(support, source, execution, tmp_path)

    # 원래 모든 실패의 전체 비교는 비공개 파일에 있고 여기에는 ID/검사명만 둔다.
    failures = [
        {"record_id": _identifier(record["record_id"]),
         "target_id": _identifier(failure.get("target_id")), "check": _identifier(failure["check"])}
        for record in summary.get("records", []) for failure in record.get("failures", [])
    ]
    (tmp_path / "failure_index_safe.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        first = failures[0]
        _require(False, first["record_id"], f"{first['check']}:failures_{len(failures)}")
    _require(returncode == 0, "HARNESS", "controlled_exit")
    _require(summary["status"] == "CONTROLLED_PARTIAL_CHECKED", "HARNESS", "all_contract_checks")
    for key in ("source_unchanged", "references_unchanged", "support_unchanged", "module_origins_valid"):
        _require(summary[key] is True, "HARNESS", key)
    _require(summary["source_file_count"] > 0, "HARNESS", "source_inventory")
    _require(summary["selector_call_count"] == 56, "HARNESS", "controlled_calls")
    _require(summary["record_count"] == 58 and summary["target_count"] == 58, "HARNESS", "all_records_targets")
    _require(summary["semantic_scored"] == 54, "HARNESS", "eligible_semantics")
    _require(summary["semantic_unscored_target_count"] == 4, "HARNESS", "unscored_targets")
    _require(summary["partial_record_count"] == 9, "HARNESS", "partial_inputs")
    _require(summary["unbound_not_called_record_count"] == 2, "HARNESS", "abstract_not_called")
    _require(summary["failed_record_count"] == 0, "HARNESS", "failed_records")
    _require(summary["g2p_kiwi_model_calls_requested"] == 0, "HARNESS", "controlled_only")

    records = summary["records"]
    _require([r["record_id"] for r in records] == receipt["record_ids"], "HARNESS", "record_ids_and_order")
    abstract = {r["record_id"] for r in records if r["status"] == "not_executed_unbound"}
    _require(abstract == set(receipt["abstract_record_ids"]), "HARNESS", "abstract_ids")
    observed = 0
    for record in records:
        identifier = _identifier(record["record_id"])
        if record["record_id"] in abstract:
            _require(not record["targets"] and record["semantic_scored"] == 0, identifier, "abstract_unscored")
            continue
        _require(record["status"] == "checked", identifier, "controlled_status")
        targets = record["targets"]
        _require([t["target_id"] for t in targets] == receipt["target_ids_by_record"][record["record_id"]], identifier, "target_ids_and_order")
        _require(all(t["observed"] is True for t in targets), identifier, "exact_targets_observed")
        observed += len(targets)
    _require(observed == 58, "HARNESS", "observed_occurrences")

    # 양성43 앵커와 명시 부재는 원참고의 정확한 제약으로 검사한다.
    # 구체 C 양성 참고가 없다는 사실을 향후 C 능력의 부재 요구로 고정하지 않는다.
    origins = json.loads((execution / "module_origins_bound_before_calls.json").read_text(encoding="utf-8"))
    final_origins = json.loads((execution / "module_origins_after.json").read_text(encoding="utf-8"))
    for mapping in (origins, final_origins):
        _require(bool(mapping), "HARNESS", "real_module_origins")
        _require(all(Path(row["path"]).resolve().is_relative_to(source) for row in mapping.values()), "HARNESS", "selected_source_origins")
    _verify_support(support, receipt)
