"""실제 저장된 명사 원천 포장을 원래 참고 제약으로 한 번 회귀 검증한다."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback


def _require(condition, check):
    # 본문·뜻·발음·반환 대신 고정 ID와 검사명만 노출한다.
    if not condition:
        raise AssertionError("LN046:" + check)


def _verify_support(support, receipt):
    for name, expected in receipt["files_sha256"].items():
        _require(hashlib.sha256((support / name).read_bytes()).hexdigest() == expected,
                 "fixture_bytes")


def test_nominal_source_packaging_preserves_original_reference(tmp_path):
    root = Path(__file__).resolve().parents[1]
    support = root / "tests" / "fixtures" / "nominal_source_packaging"
    source = (root / "src").resolve()
    receipt = json.loads((support / "support_copy_receipt.json").read_text(encoding="utf-8"))
    _verify_support(support, receipt)
    execution = tmp_path / "controlled_private"
    shutil.copyfile(support / "references.json", tmp_path / "frozen_reference_private.json")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-B", str(support / "run_controlled_selector.py"),
             "--src", str(source), "--refs", str(support / "references.json"), "--out", str(execution)],
            capture_output=True, timeout=180,
        )
        (tmp_path / "stdout_private.bin").write_bytes(completed.stdout)
        (tmp_path / "stderr_private.bin").write_bytes(completed.stderr)
        returncode = completed.returncode
        del completed
    except Exception as error:
        (tmp_path / "execution_exception_private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if isinstance(error, subprocess.TimeoutExpired):
            for name, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                if value is not None:
                    (tmp_path / (name + "_private.bin")).write_bytes(value)
        raise AssertionError("LN046:subprocess") from None
    try:
        summary = json.loads((execution / "parent_safe_controlled_summary.json").read_text(encoding="utf-8"))
    except Exception:
        raise AssertionError("LN046:summary_schema") from None

    # 모든 원반환·비교와 예외는 러너의 비공개 파일에 보존한다. 실패를 잘라 숨기지 않는다.
    failures = []
    for record in summary.get("records", []):
        for failure in record.get("failures", []):
            code = failure.get("check")
            code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", code) else "checker_schema"
            failures.append({"record_id": "LN046", "check": code})
    (tmp_path / "failure_index_safe.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        _require(False, failures[0]["check"] + ":failures_" + str(len(failures)))
    _require(returncode == 0 and summary["status"] == "CONTROLLED_CHECKED", "contract_status")
    for key in ("source_unchanged", "references_unchanged", "support_unchanged", "module_origins_valid"):
        _require(summary[key] is True, key)
    _require(summary["source_file_count"] > 0, "source_inventory")
    _require(summary["record_count"] == 1 and summary["target_count"] == 1, "one_original_target")
    _require(summary["selector_call_count"] == 1 and summary["semantic_scored"] == 1, "one_controlled_call")
    _require(summary["failed_record_count"] == 0, "all_constraints")
    _require(summary["semantic_unscored_target_count"] == 0 and
             summary["partial_record_count"] == 0 and summary["unbound_not_called_record_count"] == 0,
             "supplied_input_premises")
    _require(summary["g2p_kiwi_model_calls_requested"] == 0, "selector_only")
    records = summary["records"]
    _require(len(records) == 1 and records[0]["record_id"] == "LN046" and
             records[0]["status"] == "checked", "record_binding")
    targets = records[0]["targets"]
    _require(len(targets) == 1 and targets[0]["target_id"] == "t1" and
             targets[0]["observed"] is True and targets[0]["semantic_scored"] is True and
             targets[0]["structure_scored"] is True, "exact_target_observed")
    for name in ("module_origins_bound_before_calls.json", "module_origins_after.json"):
        origins = json.loads((execution / name).read_text(encoding="utf-8"))
        _require(bool(origins) and all(Path(row["path"]).resolve().is_relative_to(source)
                                      for row in origins.values()), "real_source_origins")
    _verify_support(support, receipt)
