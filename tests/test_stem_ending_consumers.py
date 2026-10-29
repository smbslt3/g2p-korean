"""제어된 어간·어미 포장 두 가지의 실제 G2P 결과를 회귀 검증한다."""

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


def test_stem_ending_consumers_and_packaging(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = (root / "src").resolve()
    support = root / "tests" / "fixtures" / "stem_ending_consumers"
    completed = subprocess.run(
        [
            sys.executable, "-I", str(support / "run_references.py"),
            "--src", str(source), "--out", str(tmp_path / "execution"),
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((tmp_path / "execution" / "execution.json").read_text(encoding="utf-8"))
    assert Path(report["selected_source"]).resolve() == source
    assert report["module_origins"]
    assert all(Path(path).resolve().is_relative_to(source) for path in report["module_origins"].values())
    # 내부 정적 주입이며 공개 custom-analyzer 기능이나 실제 Kiwi 관측이 아니다.
    assert report["mode"] == "controlled_internal_test_injection"
    assert report["public_custom_analyzer_feature"] is False
    assert report["actual_kiwi_packaging_measured"] is False
    assert report["model_constructors_by_runner"] == 0
    counts = report["call_counts"]
    assert counts["g2p_convert_with_alignment"] == counts["analysis_calls"] == 18
    assert counts["saisiot_positions"] == 0

    controlled = [row for row in report["records"] if row["status"] == "executed"]
    unbound = [row for row in report["records"] if row["status"] == "unbound"]
    assert len(report["records"]) == 22 and len(controlled) == 18 and len(unbound) == 4
    expected_ids = {f"R46-REF-{number:02d}" for number in range(1, 10)}
    assert Counter(row["ref_id"] for row in controlled) == dict.fromkeys(expected_ids, 2)
    assert {row["ref_id"] for row in unbound} == {f"R46-REF-{number:02d}" for number in range(10, 14)}
    for key in expected_ids:
        pair = [row for row in controlled if row["ref_id"] == key]
        assert {row["packaging"] for row in pair} == {"within_token", "adjacent_tokens"}
        assert len({row["result"]["surface_pronunciation"] for row in pair}) == 1
    for row in unbound:
        assert row["phone_matches"] is row["rule_presence_matches"] is row["execution_count"] is None

    observed_proofs = 0
    for row in controlled:
        assert row["phone_matches"] is True
        assert row["rule_presence_matches"] is True
        assert row["analysis_preserved"] is True
        assert row["result"]["complete"] is True
        assert row["analysis_before"] == row["analysis_after"] == row["input"]
        assert len(row["analysis_calls"]) == 1
        request = row["analysis_calls"][0]
        assert request["method"] in {"analyze", "analyze_components"}
        assert request["text"] == row["result"]["source"]
        assert all(call["method"] == "verified_token_surface" for call in row["supplementary_calls"])
        assert [call["token_index"] for call in row["supplementary_calls"]] == list(range(len(row["input"])))
        assert len(row["token_surface_proofs"]) == len(row["input"])
        for token, observation in zip(row["input"], row["token_surface_proofs"]):
            assert observation["status"] in {"observed", "missing"}
            if observation["status"] == "observed":
                observed_proofs += 1
                proof = observation["proof"]
                assert proof["parts"] == token["morphemes"]
                assert [proof["start"], proof["end"]] == [token["normalized_start"], token["normalized_end"]]
                assert proof["atoms"]
            else:
                assert observation["proof"] is None
        # 공개 정렬의 규칙 항목은 전체 문법 권한이나 실제 적용 횟수가 아니다.
        assert row["whole_word_grammar"] == "unobserved_by_public_result"
        assert row["new_internal_eligibility"] == "unconfirmed"
        assert row["execution_count"] is None
    assert observed_proofs > 0
    assert counts["verified_token_surface"] == sum(len(row["input"]) for row in controlled) == 28
