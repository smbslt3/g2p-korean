from __future__ import annotations

import pytest

from g2p_ko import G2P, InputValidationError, KoreanTTSNormalizer
from g2p_ko.pipeline import Pipeline
from g2p_ko.routing import is_han
from tests._internal_pipeline import convert_pipeline


def test_g2p_reads_upstream_normalized_input() -> None:
    assert G2P()("사과 세 개와 국물") == "사과 세 개와 궁물"


def test_g2p_reads_reviewed_brand_names() -> None:
    assert G2P()("NAVER 뉴스") == "네이버 뉴스"


def test_g2p_can_skip_normalizer_for_pre_normalized_text() -> None:
    source = "사과 3개와 국물"
    normalized = KoreanTTSNormalizer()(source)
    g2p = G2P()

    assert g2p(normalized, normalize=False) == g2p(normalized)


def test_legacy_normalize_flag_does_not_change_spelling() -> None:
    g2p = G2P()

    assert g2p("NAVER") == "네이버"
    assert g2p("NAVER", normalize=False) == "네이버"


def test_g2p_rejects_non_boolean_normalize_option() -> None:
    with pytest.raises(InputValidationError, match="normalize"):
        G2P()("국물", normalize=0)  # type: ignore[arg-type]


def test_g2p_skip_normalizer_keeps_input_length_limit() -> None:
    with pytest.raises(InputValidationError, match="최대 길이 3"):
        G2P(max_length=3)("가나다라", normalize=False)


def test_g2p_exposes_string_and_detailed_paths() -> None:
    g2p = G2P()

    assert callable(g2p.convert)
    assert not hasattr(g2p, "normalize")


def test_g2p_string_api_uses_the_text_only_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g2p = G2P()
    calls: list[str] = []

    def run_text(source: str, *, pause_boundaries: tuple[int, ...] = ()) -> str:
        assert pause_boundaries == ()
        calls.append(source)
        return "문자열 경로"

    def reject_detailed(_source: str) -> object:
        raise AssertionError("문자열 API가 상세 Pipeline.run을 호출했습니다.")

    monkeypatch.setattr(g2p._pipeline, "run_text", run_text)
    monkeypatch.setattr(g2p._pipeline, "run", reject_detailed)

    assert g2p("국물", normalize=False) == "문자열 경로"
    assert calls == ["국물"]


def test_text_only_pipeline_uses_the_same_pronunciation_contract() -> None:
    """문자열 경로와 상세 경로가 같은 보존·음운 결과를 내는지 확인한다."""

    pipeline = Pipeline(max_length=10_000)
    detailed = pipeline.run("ABC ж 국물")
    text = pipeline.run_text("ABC ж 국물")

    assert text == detailed.surface_pronunciation


def test_internal_diagnostic_keeps_narrow_output_span() -> None:
    result = convert_pipeline("가🙂나")
    diagnostic = next(item for item in result.diagnostics if item.code == "unsupported_emoji")

    assert (diagnostic.source_spans[0].start, diagnostic.source_spans[0].end) == (1, 2)


def test_boolean_integer_limit_is_rejected() -> None:
    with pytest.raises(InputValidationError, match="max_length"):
        G2P(max_length=True)


def test_english_is_always_read_as_letter_names() -> None:
    result = convert_pipeline("ABCD")

    assert result.normalized_text == "에이비씨디"
    assert result.surface_pronunciation == "에이비씨디"
    assert [item.rule_id for item in result.rewrites] == ["english.letter_names.v1"]


def test_unsupported_script_is_preserved_and_incomplete() -> None:
    result = convert_pipeline("жця")

    assert result.normalized_text == "жця"
    assert result.surface_pronunciation == "жця"
    assert not result.complete
    assert [(item.code, item.rule_id) for item in result.diagnostics] == [
        ("unsupported_script", "routing.unsupported_script"),
    ]


def test_foreign_script_and_han_are_reported_separately() -> None:
    sample = "жця世界"
    split = next(index for index, character in enumerate(sample) if is_han(character))
    result = convert_pipeline(sample)

    assert result.normalized_text == sample
    assert result.surface_pronunciation == sample
    assert not result.complete
    assert {
        (item.code, item.source_spans[0].start, item.source_spans[0].end)
        for item in result.diagnostics
    } == {
        ("unsupported_script", 0, split),
        ("unconverted_han", split, len(sample)),
    }


def test_japanese_kana_is_unsupported() -> None:
    result = convert_pipeline("가テスト나")

    assert result.normalized_text == "가テスト나"
    assert result.surface_pronunciation == "가テスト나"
    assert not result.complete
    assert [item.code for item in result.diagnostics] == ["unsupported_script"]


@pytest.mark.parametrize("source", ["123", "٤٢", "²Ⅳ", "四五"])
def test_unconverted_numbers_are_preserved_and_incomplete(source: str) -> None:
    result = convert_pipeline(source)

    assert result.normalized_text == source
    assert result.surface_pronunciation == source
    assert result.diagnostics
    assert not result.complete


@pytest.mark.parametrize("source", ["테스트3", "가3", "3가"])
def test_hangul_numeric_structure_reports_upstream_omission(source: str) -> None:
    result = convert_pipeline(source)

    assert result.normalized_text == source
    assert result.surface_pronunciation == source
    assert result.diagnostics
    assert not result.complete


def test_protected_unsupported_script_is_preserved_and_reported() -> None:
    source = "https://жця.example.com"
    result = convert_pipeline(source)

    assert not result.complete
    assert any(
        item.code == "unsupported_script" and item.source_spans[0].surface == "жця"
        for item in result.diagnostics
    )
