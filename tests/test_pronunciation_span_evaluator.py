from __future__ import annotations

import json

import pytest

from tools.evaluate_pronunciation_spans import evaluate, main, validate_cases


def make_case(
    case_id: str = "case-1",
    *,
    text: str = "가나",
    start: int = 0,
    end: int = 1,
    surface: str = "가",
    judgment: str = "verified",
    accepted: list[str] | None = None,
    category: str = "발음",
    family: str = "family-1",
    split: str = "development",
    frequency: int = 1,
    **extra: object,
) -> dict[str, object]:
    case: dict[str, object] = {
        "id": case_id,
        "input": text,
        "target": {"start": start, "end": end, "surface": surface},
        "judgment": judgment,
        "accepted_pronunciations": accepted if accepted is not None else [surface],
        "category": category,
        "family_id": family,
        "split": split,
        "sources": [{"kind": "fixture"}],
        "frequency": frequency,
    }
    case.update(extra)
    return case


def test_extracts_target_by_codepoint_slice_and_allows_repeated_sentence_spans() -> None:
    text = "가나가나"
    cases = [
        make_case("first", text=text, start=0, end=2, surface="가나", accepted=["가나"]),
        make_case(
            "second",
            text=text,
            start=2,
            end=4,
            surface="가나",
            accepted=["가나"],
            family="family-2",
        ),
    ]

    report = evaluate(
        cases,
        [
            {"id": "first", "output": "가나가나"},
            {"id": "second", "output": "가나가나"},
        ],
    )

    assert [row["localized_output"] for row in report["rows"]] == ["가나", "가나"]
    assert report["summary"]["span_exact"]["matched"] == 2


def test_excludes_unverified_gold_but_keeps_judgment_and_frequency_counts() -> None:
    cases = [
        make_case("verified", frequency=3),
        make_case(
            "pending",
            judgment="pending",
            accepted=[],
            family="family-2",
            frequency=4,
        ),
    ]
    report = evaluate(
        cases,
        [
            {"id": "verified", "output": "가나"},
            {"id": "pending", "output": "가나"},
        ],
    )

    assert report["summary"]["judgment_counts"]["pending"] == {
        "cases": 1,
        "frequency_weight": 4,
    }
    assert report["summary"]["exclusions"]["cases"] == 1
    assert report["summary"]["exclusions"]["frequency_weight"] == 4
    assert report["summary"]["span_exact"]["cases"] == 1
    assert report["rows"][1]["span_match"] is None
    assert report["rows"][1]["exclusion_reason"] == "pending"
    assert report["rows"][1]["output_status"] == "provided"


def test_missing_and_error_outputs_are_verified_failures_even_when_complete_is_true() -> None:
    cases = [make_case("missing"), make_case("errored", family="family-2")]
    report = evaluate(
        cases,
        [{"id": "errored", "output": "가나", "error": "엔진 오류", "complete": True}],
    )

    score = report["summary"]["span_exact"]
    assert score["cases"] == 2
    assert score["matched"] == 0
    assert score["mismatched"] == 2
    assert score["missing_outputs"] == 1
    assert score["error_outputs"] == 1
    assert report["rows"][0]["output"] is None
    assert report["rows"][1]["span_match"] is False


def test_accepts_declared_alternative_and_whitespace_ignored_policy() -> None:
    case = make_case(
        text="가 나",
        start=0,
        end=3,
        surface="가 나",
        accepted=["가나", "가 나"],
        normalization="nfc_whitespace_ignored",
    )
    report = evaluate([case], [{"id": "case-1", "output": "가 나"}])

    assert report["rows"][0]["span_match"] is True
    assert report["summary"]["symbol_edit"]["edits"] == 0


def test_length_mismatch_fails_without_guessing_and_explicit_target_is_labeled() -> None:
    cases = [
        make_case("wrong-length", text="가나다", start=1, end=2, surface="나"),
        make_case("prealigned", text="가나다", start=1, end=2, surface="나", family="family-2"),
    ]
    report = evaluate(
        cases,
        [
            {"id": "wrong-length", "output": "다라"},
            {"id": "prealigned", "output": "다라", "target_output": "나"},
        ],
    )

    mismatch, aligned = report["rows"]
    assert mismatch["span_match"] is False
    assert mismatch["alignment"]["status"] == "length_mismatch"
    assert mismatch["alignment"]["actual_codepoints"] == 2
    assert aligned["span_match"] is True
    assert aligned["alignment"] == {
        "status": "aligned",
        "method": "explicit_target_output",
    }
    assert report["summary"]["span_exact"]["alignment_failures"] == 1


@pytest.mark.parametrize(
    ("text", "output"),
    [("가 나", "가나 "), ("가,나", "가나,")],
)
def test_same_length_output_with_moved_space_or_punctuation_fails_alignment(
    text: str, output: str
) -> None:
    case = make_case("boundary", text=text, start=0, end=1, surface="가")
    report = evaluate([case], [{"id": "boundary", "output": output}])

    assert len(text) == len(output)
    assert report["rows"][0]["span_match"] is False
    assert report["rows"][0]["output_status"] == "alignment_failure"
    assert report["rows"][0]["alignment"]["status"] == "boundary_position_mismatch"


def test_same_length_non_nfc_output_fails_alignment() -> None:
    case = make_case("non-nfc", text="ab", start=0, end=1, surface="a")
    output = "e\u0301"
    report = evaluate([case], [{"id": "non-nfc", "output": output}])

    assert len(output) == len(case["input"])
    assert report["rows"][0]["span_match"] is False
    assert report["rows"][0]["alignment"]["status"] == "non_nfc_output"


def test_whole_sentence_score_is_separate_and_only_present_for_declared_gold() -> None:
    case = make_case(
        text="가나다",
        start=1,
        end=2,
        surface="나",
        accepted_sentence_pronunciations=["가나다"],
    )
    report = evaluate([case], [{"id": "case-1", "output": "가나다", "complete": False}])

    assert report["rows"][0]["span_match"] is True
    assert report["rows"][0]["whole_sentence_match"] is True
    assert report["summary"]["whole_sentence_exact"]["cases"] == 1


def test_symbol_edit_uses_onset_vowel_coda_tokens_and_reports_reference_denominator() -> None:
    case = make_case(text="가", start=0, end=1, surface="가", accepted=["가"])
    report = evaluate([case], [{"id": "case-1", "output": "각"}])
    edit = report["rows"][0]["symbol_edit"]

    assert edit["edits"] == 1
    assert edit["reference_token_count"] == 2
    assert edit["output_token_count"] == 3
    assert edit["rate"] == 0.5
    assert report["summary"]["symbol_edit"]["rate"] == 0.5


def test_symbol_edit_alternative_tie_uses_normalized_lexical_order() -> None:
    case = make_case(
        text="가",
        start=0,
        end=1,
        surface="가",
        accepted=["나", "다"],
    )
    report = evaluate([case], [{"id": "case-1", "output": "라"}])

    assert report["rows"][0]["symbol_edit"]["chosen_reference"] == "나"
    assert report["rows"][0]["symbol_edit"]["edits"] == 1


@pytest.mark.parametrize(
    "cases",
    [
        [make_case("same", family="family-a"), make_case("same", family="family-b")],
        [
            make_case("dev", family="shared", split="development"),
            make_case("hold", family="shared", split="holdout"),
        ],
        [
            make_case("dev", family="one", split="development"),
            make_case("hold", family="two", split="holdout"),
        ],
    ],
)
def test_rejects_duplicate_ids_and_family_or_input_split_leakage(cases: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError):
        validate_cases(cases)


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": ""},
        {"target": {"start": 0, "end": 2, "surface": "가"}},
        {"target": {"start": -1, "end": 1, "surface": "가"}},
        {"frequency": 0},
        {"frequency": True},
        {"judgment": "unknown"},
        {"input": "가"},
        {"leakage_group_ids": "not-a-list"},
        {"leakage_group_ids": [""]},
    ],
)
def test_rejects_invalid_case_ids_spans_frequency_and_fields(
    overrides: dict[str, object],
) -> None:
    case = make_case()
    case.update(overrides)
    with pytest.raises(ValueError):
        validate_cases([case])


@pytest.mark.parametrize(
    "outputs",
    [
        [{"id": "case-1", "output": "가나"}, {"id": "case-1", "output": "가나"}],
        [{"id": "unknown", "output": "가나"}],
    ],
)
def test_rejects_duplicate_or_unknown_output_ids(outputs: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError):
        evaluate([make_case()], outputs)


def test_zero_reference_symbol_count_has_null_rate_not_division_by_zero() -> None:
    case = make_case(
        text=" ",
        start=0,
        end=1,
        surface=" ",
        accepted=[" "],
        normalization="nfc_whitespace_ignored",
    )
    report = evaluate([case], [{"id": "case-1", "output": " "}])

    assert report["rows"][0]["symbol_edit"]["reference_token_count"] == 0
    assert report["rows"][0]["symbol_edit"]["rate"] is None
    assert report["summary"]["symbol_edit"]["rate"] is None


def test_rejects_leakage_group_and_source_group_crossing_splits() -> None:
    leakage_cases = [
        make_case("dev-leak", family="dev-family", leakage_group_ids=["shared-leak"]),
        make_case(
            "hold-leak",
            text="다라",
            surface="다",
            family="hold-family",
            split="holdout",
            leakage_group_ids=["shared-leak"],
        ),
    ]
    with pytest.raises(ValueError, match="누수 그룹"):
        validate_cases(leakage_cases)

    source_cases = [
        make_case(
            "dev-source",
            family="dev-source-family",
            sources=[{"kind": "fixture", "source_group_id": "shared-source"}],
        ),
        make_case(
            "hold-source",
            text="다라",
            surface="다",
            family="hold-source-family",
            split="holdout",
            sources=[{"kind": "fixture", "source_group_id": "shared-source"}],
        ),
    ]
    with pytest.raises(ValueError, match="출처 그룹"):
        validate_cases(source_cases)


def test_cli_reads_jsonl_and_writes_report(tmp_path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    outputs_path = tmp_path / "outputs.jsonl"
    report_path = tmp_path / "nested" / "report.json"
    case = make_case("cli-case", text="가", start=0, end=1, surface="가")
    cases_path.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    outputs_path.write_text(
        json.dumps({"id": "cli-case", "output": "가"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = main(
        [
            "--cases",
            str(cases_path),
            "--outputs",
            str(outputs_path),
            "--report",
            str(report_path),
        ]
    )

    assert result == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["span_exact"]["matched"] == 1
