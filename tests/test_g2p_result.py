"""공개 G2P 상세 결과와 code point 정렬 계약을 검증한다."""

from __future__ import annotations

import pytest

from g2p_ko import G2P, G2PResult, InputValidationError


def test_convert_exposes_intermediate_pronunciation_and_completion() -> None:
    result = G2P().convert("사과 3개와 국물")

    assert isinstance(result, G2PResult)
    assert result.source == "사과 3개와 국물"
    assert result.normalized_text == "사과 세 개와 국물"
    assert result.surface_pronunciation == "사과 세 개와 궁물"
    assert result.complete
    assert result.diagnostics.normalization.source == result.source
    assert result.diagnostics.pronunciation.source == result.normalized_text
    assert result.diagnostics.normalization.diagnostics == ()
    assert result.diagnostics.pronunciation.diagnostics == ()


@pytest.mark.parametrize("normalize", [True, False])
def test_string_and_detailed_paths_return_the_same_pronunciation(normalize: bool) -> None:
    source = "NASA와 16%의 국물" if normalize else "나사와 십육 퍼센트의 국물"
    g2p = G2P()

    assert g2p(source, normalize=normalize) == g2p.convert(
        source,
        normalize=normalize,
    ).surface_pronunciation


def test_normalization_failure_is_not_lost_when_pronunciation_stage_completes() -> None:
    result = G2P().convert("A-1")

    assert not result.complete
    assert result.diagnostics.normalization.diagnostics
    assert result.diagnostics.normalization.source == "A-1"
    assert result.diagnostics.pronunciation.source == "A-1"


def test_undecidable_balb_exception_remains_incomplete() -> None:
    result = G2P().convert("밟")

    assert not result.complete
    assert result.surface_pronunciation == "밟"
    assert result.diagnostics.normalization.diagnostics == ()
    assert result.diagnostics.pronunciation.diagnostics
    assert result.diagnostics.pronunciation.source == "밟"


def test_pronunciation_diagnostics_keep_pre_expansion_coordinate_source() -> None:
    result = G2P().convert("ABC ж")
    diagnostic = next(
        item
        for item in result.diagnostics.pronunciation.diagnostics
        if item.code == "unsupported_script"
    )

    assert result.normalized_text == "에이비씨 ж"
    assert result.diagnostics.pronunciation.source == "ABC ж"
    assert diagnostic.source_spans[0].surface == "ж"
    assert (diagnostic.source_spans[0].start, diagnostic.source_spans[0].end) == (4, 5)


def test_skip_normalizer_detailed_path_keeps_nfc_and_raw_source() -> None:
    source = "\u1100\u1161꽃"
    result = G2P().convert(source, normalize=False)

    assert result.source == source
    assert result.normalized_text == "가꽃"
    assert result.surface_pronunciation == "가꼳"
    assert result.diagnostics.normalization.source == source
    assert result.diagnostics.pronunciation.source == "가꽃"
    assert result.complete


@pytest.mark.parametrize(
    "source",
    [
        "",
        "국물",
        "꽃, 국물.",
        "사과 3개는 6,000원입니다.",
        "NASA와 TV 뉴스를 봤다.",
        "가\t국물\n같이",
        "A-1과 жця",
        "\u1100\u1161꽃",
    ],
)
def test_normalized_text_and_pronunciation_keep_code_point_alignment(source: str) -> None:
    result = G2P().convert(source)

    assert len(result.normalized_text) == len(result.surface_pronunciation)
    for normalized, pronounced in zip(
        result.normalized_text,
        result.surface_pronunciation,
    ):
        if "가" <= normalized <= "힣":
            assert "가" <= pronounced <= "힣"
        else:
            assert pronounced == normalized


def test_user_lexicon_participates_in_detailed_conversion() -> None:
    result = G2P(lexicon={"NAVER": "네이버"}).convert("NAVER 뉴스")

    assert result.normalized_text == "네이버 뉴스"
    assert result.surface_pronunciation == "네이버 뉴스"
    assert result.complete


def test_detailed_result_is_json_serializable() -> None:
    payload = G2P().convert("국물").to_dict()

    assert payload == {
        "source": "국물",
        "normalized_text": "국물",
        "surface_pronunciation": "궁물",
        "diagnostics": {
            "normalization": {"source": "국물", "diagnostics": []},
            "pronunciation": {"source": "국물", "diagnostics": []},
        },
        "complete": True,
    }


def test_convert_rejects_non_boolean_normalize_option() -> None:
    with pytest.raises(InputValidationError, match="normalize"):
        G2P().convert("국물", normalize=0)  # type: ignore[arg-type]


def test_convert_keeps_input_length_limit_when_normalizer_is_skipped() -> None:
    with pytest.raises(InputValidationError, match="최대 길이 3"):
        G2P(max_length=3).convert("가나다라", normalize=False)
