"""엔진과 실제 평가 자료를 사용하지 않는 참조 사전 검토 검사입니다."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata

import pytest

from tools.pronunciation_reference_preflight import build_report, main


def make_case(text: str = "지금 어떻게", target: str | None = None, *,
              window: tuple[int, int] | None = None, verified: bool = False,
              case_id: str = "synthetic") -> dict:
    target = text if target is None else target
    start = text.index(target)
    case = {
        "id": case_id, "input": text,
        "target": {"start": start, "end": start + len(target), "surface": target},
        "judgment": "verified" if verified else "pending",
        "accepted_pronunciations": [target] if verified else [],
        "category": "합성 경계", "family_id": case_id, "split": "development",
        "sources": [{"kind": "독립 합성 사례"}],
    }
    if window is not None:
        a, b = window
        case["reference_window"] = {"start": a, "end": b, "accepted_pronunciations": [text[a:b]] if verified else []}
    return case


def rows(case: dict, kind: str, **assumptions) -> list[dict]:
    return [row for row in build_report([case], **assumptions)["findings"] if row["kind"] == kind]


@pytest.mark.parametrize(("text", "target", "edge"), [
    ("지금 어떻게", "어떻게", "left"),
    ("그러면 엄마가", "그러면", "right"),
    ("치는 애들도", "치는 애들도", "internal"),
])
def test_vowel_boundaries_cover_both_target_directions_and_internal(text, target, edge):
    case = make_case(text, target, window=(0, len(text)))
    row, = rows(case, "review_source_coda_whitespace_vowel_boundary")
    assert row["affected_target_edge"] == edge
    assert row["ownership"] == "target_affecting"
    assert row["within_window"] is True
    assert row["confirmed_error"] is False


@pytest.mark.parametrize(("target", "edge"), [("먹을", "right"), ("것을", "left")])
def test_tensing_and_adnominal_candidates_cover_both_directions(target, edge):
    text = "먹을 것을"
    case = make_case(text, target, window=(0, len(text)))
    for kind in ("review_potential_consonant_tensing", "review_potential_adnominal_l_boundary"):
        row, = rows(case, kind)
        assert row["affected_target_edge"] == edge
        assert row["source_boundary"] == "을 것"
        assert row["morphology_required"] is True
        assert row["candidate_basis"] == "source_spelling_only"
        assert row["severity"] == "review"


@pytest.mark.parametrize("text", ["책 가방", "책, 가방", "책\n가방"])
def test_tensing_candidates_include_whitespace_and_punctuation(text):
    assert rows(make_case(text), "review_potential_consonant_tensing")


def test_adjacent_target_edge_is_reviewed_without_scanning_all_word_internal_pairs():
    case = make_case("먹다", "다", window=(0, 2))
    assert rows(case, "review_potential_consonant_tensing")[0]["affected_target_edge"] == "left"
    assert not rows(make_case("먹다"), "review_potential_consonant_tensing")
    assert rows(make_case("먹어", "어"), "review_source_coda_adjacent_vowel_boundary")


def test_adnominal_candidate_does_not_assert_morphology_from_noun_spelling():
    row, = rows(make_case("물 병"), "review_potential_adnominal_l_boundary")
    assert row["confirmed_error"] is False
    assert row["morphology_required"] is True
    assert not rows(make_case("물병"), "review_potential_adnominal_l_boundary")


@pytest.mark.parametrize(("text", "kind"), [
    ("나 어떻게", "review_source_coda_whitespace_vowel_boundary"),
    ("지금 A 어떻게", "review_source_coda_whitespace_vowel_boundary"),
    ("책 A 가방", "review_potential_consonant_tensing"),
    ("나 가방", "review_potential_consonant_tensing"),
    ("책 꺼내", "review_potential_consonant_tensing"),
    ("간 것을", "review_potential_adnominal_l_boundary"),
    ("할 일", "review_potential_adnominal_l_boundary"),
])
def test_negative_controls_avoid_unrelated_boundary_kinds(text, kind):
    assert not rows(make_case(text), kind)


def test_punctuation_is_not_assumed_to_be_a_pause():
    case = make_case("(지금), 어떻게", "어떻게", window=(0, 9))
    row, = rows(case, "review_source_coda_punctuation_vowel_boundary")
    assert row["source_offsets"] == {"coda": 2, "onset": 6, "separator_start": 3, "separator_end": 6}
    assert row["assumptions"]["pause_inferred_from_separator"] is False
    assert row["assumptions"]["pause_assumption"] == "unspecified"


def test_context_witness_boundaries_have_no_target_ownership():
    text = "지금 어떻게 가"
    row, = rows(make_case(text, "가", window=(0, len(text))), "review_source_coda_whitespace_vowel_boundary")
    assert row["ownership"] == "context_witness_only"
    assert row["affected_target_edge"] == "none"


@pytest.mark.parametrize(("target", "window", "side"), [("지금", (0, 2), "right"), ("어떻게", (3, 6), "left")])
def test_clipped_context_is_detected_on_both_sides(target, window, side):
    case = make_case("지금 어떻게", target, window=window)
    clipped, = rows(case, "review_window_clips_source_boundary_evidence")
    missing, = rows(case, "review_window_neighbor_evidence_missing")
    assert clipped["within_window"] is False
    assert clipped["affected_target_edge"] == missing["affected_target_edge"] == side
    assert clipped["source_offsets"] == {"coda": 1, "onset": 3, "separator_start": 2, "separator_end": 3}


def test_missing_window_retains_source_warnings_without_generating_gold():
    case = make_case("지금 어떻게", "지금")
    before = copy.deepcopy(case)
    report = build_report([case])
    assert report["contract_errors"] == 0
    assert rows(case, "review_reference_window_missing")
    assert rows(case, "review_window_neighbor_evidence_missing")
    assert rows(case, "review_source_coda_whitespace_vowel_boundary")
    assert report["gold_generated"] is False
    assert report["engine_used"] is False
    assert case == before


def test_non_hangul_neighbor_risk_is_separate_and_does_not_bridge_across_it():
    case = make_case("지금 10A 어떻게", "지금", window=(0, 2))
    assert rows(case, "review_external_normalization_neighbor")
    assert not rows(case, "review_source_coda_whitespace_vowel_boundary")


def test_explicit_profile_pause_are_preserved_without_suppressing_candidates():
    case = make_case()
    for pause in ("no_pause", "possible_pause", "pause"):
        report = build_report([case], reading_profile="낭독 조건 1", pause_assumption=pause)
        row = next(row for row in report["findings"] if row["kind"] == "review_source_coda_whitespace_vowel_boundary")
        assert row["assumptions"]["pause_assumption"] == pause
        assert not any(row["kind"] == "review_boundary_assumptions_unspecified" for row in report["findings"])
    case["reference_boundary_assumptions"] = {"reading_profile": "별도 조건", "pause_assumption": "pause"}
    row, = rows(case, "review_source_coda_whitespace_vowel_boundary", reading_profile="기본", pause_assumption="no_pause")
    assert row["assumptions"]["reading_profile"] == "별도 조건"
    assert row["assumptions"]["pause_assumption"] == "pause"


@pytest.mark.parametrize("assumptions", [None, [], {"reading_profile": ""}, {"pause_assumption": []}, {"pause_assumption": "automatic"}])
def test_invalid_explicit_assumptions_are_hard_schema_failures(assumptions):
    case = make_case()
    case["reference_boundary_assumptions"] = assumptions
    report = build_report([case])
    assert report["contract_errors"] == 1
    assert report["findings"][0]["kind"] == "invalid_boundary_assumptions"


@pytest.mark.parametrize("override", [
    {"id": ""}, {"frequency": True}, {"input": unicodedata.normalize("NFD", "지금 어떻게")},
    {"target": {"start": True, "end": 2, "surface": "지금"}},
    {"target": {"start": 0, "end": 2, "surface": "다름"}},
])
def test_existing_validator_is_reused_for_hard_case_failures(override):
    case = make_case()
    case.update(override)
    before = copy.deepcopy(case)
    report = build_report([case])
    assert report["contract_errors"] == 1
    assert report["review_warnings"] == 0
    assert report["findings"][0]["kind"] == "case_schema_error"
    assert case == before


def test_collection_validation_preserves_cross_split_leakage_checks():
    a = make_case("가나", case_id="a")
    b = make_case("다라", case_id="b")
    a["sources"][0]["source_group_id"] = b["sources"][0]["source_group_id"] = "shared"
    b["split"] = "holdout"
    assert build_report([a, b])["contract_errors"] == 1
    b["split"] = "development"
    b["id"] = a["id"]
    assert build_report([a, b])["contract_errors"] == 1


@pytest.mark.parametrize("window", [[], {"start": True, "end": 6}, {"start": -1, "end": 6},
                                    {"start": 0, "end": 2}, {"start": 0, "end": 6, "accepted_pronunciations": "지금 어떻게"}])
def test_invalid_window_structure_is_a_hard_failure(window):
    case = make_case()
    case["reference_window"] = window
    assert build_report([case])["contract_errors"] == 1


def test_verified_missing_window_remains_hard_failure():
    report = build_report([make_case(verified=True)])
    assert report["contract_errors"] == 1
    assert report["findings"][0]["kind"] == "missing_reference_window"


@pytest.mark.parametrize(("reference", "kind"), [
    ("짧음", "unaligned_window_pronunciation"),
    ("지금어 떻게", "window_boundary_position_mismatch"),
    ("지금 어떠케", "window_target_projection_mismatch"),
])
def test_window_alignment_and_projection_failures_are_not_review_warnings(reference, kind):
    case = make_case(target="어떻게", window=(0, 6), verified=True)
    case["reference_window"]["accepted_pronunciations"] = [reference]
    finding, = rows(case, kind)
    assert finding["severity"] == "error"


def test_empty_verified_window_is_not_repaired_by_conditional_witnesses():
    case = make_case(target="어떻게", window=(0, 6), verified=True)
    case["reference_window"]["accepted_pronunciations"] = []
    case["conditional_projection_witnesses"] = [
        {"condition_ko": "휴지 조건", "reference_window_pronunciation": "지금 어떻게", "target_pronunciation": "어떻게"},
        {"condition_ko": "별도 조건", "reference_window_pronunciation": "자금 어떠케", "target_pronunciation": "어떠케"},
    ]
    before = copy.deepcopy(case)
    report = build_report([case])
    assert report["contract_errors"] == 1
    assert rows(case, "missing_window_pronunciations")
    medial, = rows(case, "review_reference_medial_vowel_change")
    assert medial["conditional_witness_index"] == 1
    assert medial["witness"] == case["conditional_projection_witnesses"][1]
    assert not rows(case, "window_target_projection_mismatch")
    assert case == before


def test_serialized_duplicate_conditions_remain_separate():
    case = make_case(window=(0, 6), verified=True)
    conditions = [{"pronunciation": "지금 어떻게", "condition_ko": "휴지"},
                  {"pronunciation": "지금 어떻게", "condition_ko": "연속"}]
    case["reference_window"]["witness_conditions"] = conditions
    case["reference_window"]["accepted_pronunciations"] = ["자금 어떻게"]
    case["accepted_pronunciations"] = ["자금 어떻게"]
    for condition in conditions:
        condition["pronunciation"] = "자금 어떻게"
    findings = rows(case, "review_reference_medial_vowel_change")
    assert {row["witness"]["condition_ko"] for row in findings} == {"휴지", "연속"}
    assert len(findings) == 2


def test_normalization_policy_is_respected_for_target_projection():
    case = make_case(window=(0, 6), verified=True)
    case["normalization"] = "nfc_whitespace_ignored"
    case["accepted_pronunciations"] = ["지금어떻게"]
    assert not rows(case, "window_target_projection_mismatch")


def _write_cases(path: Path, cases: list[dict]):
    path.write_text("\ufeff" + "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")


def test_cli_warning_success_hash_and_no_overwrite(tmp_path, capsys):
    cases = tmp_path / "cases.jsonl"
    report = tmp_path / "nested" / "report.json"
    _write_cases(cases, [make_case()])
    original = cases.read_bytes()
    argv = ["--cases", str(cases), "--report", str(report)]
    assert main(argv) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["cases_sha256"] == hashlib.sha256(original).hexdigest()
    assert payload["review_warnings"] > 0
    assert payload["contract_errors"] == 0
    assert cases.read_bytes() == original
    before = report.read_bytes()
    assert main(argv) == 2
    assert report.read_bytes() == before
    assert "사전 검토 실행 실패" in capsys.readouterr().err


@pytest.mark.parametrize(("content", "kind"), [(b"{broken}\n", "input_json_error"), (b"\xff", "input_encoding_error")])
def test_cli_malformed_input_has_a_structured_hard_failure_report(tmp_path, content, kind):
    cases, report = tmp_path / "cases.jsonl", tmp_path / "report.json"
    cases.write_bytes(content)
    assert main(["--cases", str(cases), "--report", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["findings"][0]["kind"] == kind
    assert payload["cases"] is None


def test_cli_verified_contract_failure_and_direct_script_import(tmp_path):
    cases, report = tmp_path / "cases.jsonl", tmp_path / "report.json"
    _write_cases(cases, [make_case(verified=True)])
    script = Path(__file__).resolve().parents[1] / "tools" / "pronunciation_reference_preflight.py"
    result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(script), "--cases", str(cases), "--report", str(report),
                             "--reading-profile", "독립 합성", "--pause-assumption", "no_pause"],
                            cwd=tmp_path, text=True, encoding="utf-8", capture_output=True, check=False)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["contract_errors"] == 1
    assert json.loads(report.read_text(encoding="utf-8"))["default_assumptions"]["pause_assumption"] == "no_pause"


def test_report_is_deterministic_and_read_only():
    case = make_case("먹을 것을", "것을", window=(0, 5), verified=True)
    before = copy.deepcopy(case)
    a, b = build_report([case]), build_report([case])
    assert a == b
    assert a["contract_errors"] == 0
    assert case == before
    assert a["historical_scores_modified"] is False
