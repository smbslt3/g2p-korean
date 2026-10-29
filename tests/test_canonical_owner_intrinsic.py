"""정규 소유 원형의 내재 경계와 실제 파이프라인 유래를 회귀 검증한다."""

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


def test_canonical_owner_intrinsic_and_provenance(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = (root / "src").resolve()
    support = root / "tests" / "fixtures" / "canonical_owner_intrinsic"
    completed = subprocess.run(
        [
            sys.executable, "-I", str(support / "run_independent_refs.py"),
            "--src", str(source), "--out", str(tmp_path / "execution"),
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((tmp_path / "execution" / "execution.json").read_text(encoding="utf-8"))
    assert Path(report["selected_source"]).resolve() == source
    assert report["loaded_project_modules"]
    assert all(Path(path).resolve().is_relative_to(source) for path in report["loaded_project_modules"].values())
    assert report["model"] == {"kiwipiepy": "0.24.1", "kiwipiepy_model": "0.24.0", "model_type": "cong"}
    counts = report["call_counts"]
    assert counts["model_constructors"] == 1
    assert counts["g2p_convert"] == 4
    assert counts["pipeline_analyze"] >= 4 and counts["pipeline_apply"] >= 4
    assert counts["native_certify"] == counts["native_apply"] == 6
    assert counts["native_duplicate_apply"] == counts["native_repeat_apply"] == 1

    rows = {row["ref_id"]: row for row in report["records"]}
    assert len(rows) == 24
    assert Counter(row["binding_status"] for row in rows.values()) == {"bound": 10, "partial": 5, "unbound": 9}
    partial = {f"R45-IREF-{number:02d}" for number in range(5, 10)}
    unbound = {f"R45-IREF-{number:02d}" for number in (10, 11, 12, 13, 14, 15, 21, 22, 24)}
    assert {key for key, row in rows.items() if row["binding_status"] == "partial"} == partial
    assert {key for key, row in rows.items() if row["binding_status"] == "unbound"} == unbound
    # 미지원·부분 범위를 완전한 발음 사례나 통과 사례로 세지 않는다.
    for key, row in rows.items():
        assert all(value is True for value in row["checks"].values() if value is not None), key
        if key in partial:
            assert row["checks"]["intrinsic_event"] is None
            assert row["input"]["analysis_before"] == row["input"]["analysis_after"]
        if key in unbound:
            assert all(value is None for value in row["checks"].values())

    for number in range(1, 5):
        row = rows[f"R45-IREF-{number:02d}"]
        assert row["checks"]["full_phone"] is True
        assert row["checks"]["source_authority"] is True
        assert row["checks"]["input_preserved"] is True
        assert row["checks"]["intrinsic_event"] is None
        assert any(event["boundary"].get("source") == "intrinsic_lexical" for event in row["observed"]["events"])

    controls = {16: "hard", 17: "protected", 18: "pause", 19: "read", 20: "nonlocal", 23: "repeat"}
    for number, control in controls.items():
        row = rows[f"R45-IREF-{number:02d}"]
        assert row["binding_status"] == "bound"
        assert row["input"]["controls"]["segment_control"] == control
        assert row["checks"]["intrinsic_event"] is True
        assert row["checks"]["source_authority"] is True
    duplicate = [
        event for event in rows["R45-IREF-20"]["observed"]["duplicate_events"]
        if event["changed"] and event["boundary"].get("source") == "intrinsic_lexical"
    ]
    assert len(duplicate) == 1 and duplicate[0]["boundary"]["pair"] == [0, 1]
    repeated = rows["R45-IREF-23"]["observed"]["repeat_events"]
    assert repeated and not any(event["changed"] for event in repeated)
