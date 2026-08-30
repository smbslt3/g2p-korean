"""첫 한국어 음운 엔진의 규칙 순서·경계·trace를 검증한다."""

import pytest

from g2p_ko.korean.engine import pronounce
from g2p_ko.korean.official import _안전_정확_열거_발음
from g2p_ko.model import Boundary, Handler, OutputSegment, RewriteStage, SourceSpan
from tests._internal_pipeline import convert_pipeline


def _segment(
    source: str,
    start: int,
    end: int,
    *,
    handler: Handler = Handler.KOREAN,
    before: Boundary = Boundary.WORD,
    after: Boundary = Boundary.WORD,
) -> OutputSegment:
    return OutputSegment(
        source[start:end],
        (SourceSpan.from_source(source, start, end),),
        handler,
        "test",
        boundary_before=before,
        boundary_after=after,
    )


@pytest.mark.parametrize(
    ("source", "expected", "rule_id"),
    [
        ("꽃", "꼳", "ko.coda.9"),
        ("옷이", "오시", "ko.liaison.single"),
        ("넋이", "넉씨", "ko.liaison.cluster"),
        ("국물", "궁물", "ko.nasalization"),
        ("신라", "실라", "ko.liquid.20"),
        ("국밥", "국빱", "ko.tensification"),
        ("좋다", "조타", "ko.hieuh.consonant"),
        ("놓는", "논는", "ko.hieuh.consonant"),
        ("많아", "마나", "ko.hieuh.vowel"),
        ("굳이", "구지", "ko.palatalization"),
        ("굳히다", "구치다", "ko.palatalization"),
        ("십육", "심뉵", "ko.n_insertion.numeral"),
        ("스물여섯", "스물려섣", "ko.n_insertion.numeral"),
    ],
)
def test_context_independent_rules_emit_pronunciation_and_trace(
    source: str,
    expected: str,
    rule_id: str,
) -> None:
    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == expected
    assert rule_id in [item.rule_id for item in result.rewrites]
    assert all(item.stage is RewriteStage.PHONOLOGY for item in result.rewrites)


def test_product_official_inventory_excludes_only_ambiguous_headwords() -> None:
    assert len(_안전_정확_열거_발음) == 113
    assert {"물질", "문고리", "잠자리", "강가"}.isdisjoint(_안전_정확_열거_발음)


@pytest.mark.parametrize(
    ("source", "expected"),
    tuple(_안전_정확_열거_발음.items()),
)
def test_safe_official_enumerations_apply_to_complete_eojeols(
    source: str,
    expected: str,
) -> None:
    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == expected
    assert result.rewrites


@pytest.mark.parametrize("source", ["물질", "문고리", "잠자리", "강가"])
def test_ambiguous_dictionary_pronunciations_are_not_forced(source: str) -> None:
    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == source
    assert "ko.official.enumerated" not in [item.rule_id for item in result.rewrites]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("발전기", "발전기"),
        ("경제발전", "경제발전"),
        ("발전은", "발저는"),
    ],
)
def test_official_enumerations_do_not_expand_to_longer_hangul_runs(
    source: str,
    expected: str,
) -> None:
    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == expected
    assert "ko.official.enumerated" not in [item.rule_id for item in result.rewrites]


def test_non_hangul_boundaries_allow_independent_official_matches() -> None:
    source = "발전, 산새"

    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == "발쩐, 산쌔"
    assert [
        item.rule_id for item in result.rewrites if item.rule_id == "ko.official.enumerated"
    ] == ["ko.official.enumerated", "ko.official.enumerated"]


def test_hard_boundary_blocks_an_official_match_across_segments() -> None:
    source = "발전"
    left = _segment(source, 0, 1, after=Boundary.HARD)
    right = _segment(source, 1, 2, before=Boundary.HARD)

    result = pronounce((left, right))

    assert result.text == source
    assert "ko.official.enumerated" not in [item.rule_id for item in result.rewrites]


def test_morpheme_boundary_allows_an_official_match_across_segments() -> None:
    source = "발전"
    left = _segment(source, 0, 1, after=Boundary.MORPHEME)
    right = _segment(source, 1, 2, before=Boundary.MORPHEME)

    result = pronounce((left, right))

    assert result.text == "발쩐"
    assert "ko.official.enumerated" in [item.rule_id for item in result.rewrites]


def test_official_rewrite_preserves_character_source_spans() -> None:
    source = "발전"

    result = pronounce((_segment(source, 0, len(source)),))
    rewrite = next(item for item in result.rewrites if item.rule_id == "ko.official.enumerated")

    assert rewrite.before == source
    assert rewrite.after == "발쩐"
    assert rewrite.stage is RewriteStage.PHONOLOGY
    assert rewrite.source_spans == (
        SourceSpan.from_source(source, 0, 1),
        SourceSpan.from_source(source, 1, 2),
    )


def test_ieung_coda_is_not_moved_to_the_next_syllable() -> None:
    source = "공일공"

    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == source
    assert all(item.rule_id != "ko.liaison.single" for item in result.rewrites)


def test_punctuation_is_preserved_and_blocks_cross_punctuation_rule() -> None:
    source = "꽃, 국물."

    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == "꼳, 궁물."
    assert result.text[1] == ","
    assert result.text[-1] == "."


def test_hard_boundary_blocks_assimilation_between_korean_segments() -> None:
    source = "국물"
    left = _segment(source, 0, 1, after=Boundary.HARD)
    right = _segment(source, 1, 2, before=Boundary.HARD)

    result = pronounce((left, right))

    assert result.text == source
    assert "ko.nasalization" not in [item.rule_id for item in result.rewrites]
    assert result.segments[0].boundary_after is Boundary.HARD
    assert result.segments[1].boundary_before is Boundary.HARD


def test_rewrite_order_tracks_the_rule_execution_order() -> None:
    source = "닭밭"

    result = pronounce((_segment(source, 0, len(source)),))

    assert result.text == "닥빧"
    assert [item.rule_id for item in result.rewrites] == [
        "ko.coda.11",
        "ko.coda.9",
        "ko.tensification",
    ]


def test_builtin_engine_implements_pipeline_pronunciation_contract() -> None:
    result = convert_pipeline("국물")

    assert result.surface_pronunciation == "궁물"
    assert any(item.rule_id == "ko.nasalization" for item in result.rewrites)


def test_inserted_segment_provenance_is_preserved() -> None:
    source = "가"
    anchor = SourceSpan.from_source(source, 0, 1)
    inserted = OutputSegment(
        "꽃",
        (),
        Handler.KOREAN,
        "test_inserted",
        insertion_rule="test.insert",
        anchor=anchor,
    )

    result = pronounce((inserted,))

    assert result.text == "꼳"
    assert result.segments[0].insertion_rule == "test.insert"
    assert result.segments[0].anchor == anchor
