"""공개 G2P가 일반 문장부호를 보존하고 의미 기호를 구별하는지 검증한다."""

from __future__ import annotations

import pytest

from g2p_ko import G2P, KoreanTTSNormalizer


@pytest.fixture(scope="module")
def g2p() -> G2P:
    return G2P()


@pytest.mark.parametrize("normalize", [True, False])
@pytest.mark.parametrize(
    ("source", "pronunciation"),
    [
        ("안녕하세요…", "안녕하세요…"),
        ("“안녕”", "“안녕”"),
        ("‘안녕’", "‘안녕’"),
        ("«안녕»", "«안녕»"),
        ("「안녕」『안녕』", "「안녕」『안녕』"),
        ("안녕—안녕–안녕", "안녕—안녕–안녕"),
        ("안녕﹐ 안녕﹒", "안녕﹐ 안녕﹒"),
        ("안녕。？！、・", "안녕。？！、・"),
        ("“국물”…", "“궁물”…"),
    ],
)
def test_ordinary_unicode_punctuation_is_preserved_and_complete(
    g2p: G2P,
    source: str,
    pronunciation: str,
    normalize: bool,
) -> None:
    result = g2p.convert(source, normalize=normalize)

    assert result.source == source
    assert result.normalized_text == source
    assert result.surface_pronunciation == pronunciation
    assert result.complete
    assert result.diagnostics.normalization.diagnostics == ()
    assert result.diagnostics.pronunciation.diagnostics == ()
    assert g2p(source, normalize=normalize) == pronunciation
    assert KoreanTTSNormalizer().convert(source).complete


@pytest.mark.parametrize("normalize", [True, False])
@pytest.mark.parametrize(
    "symbol",
    [
        "％", "؉", "؊", "٪", "‰", "‱", "＊", "﹡", "﹪", "＜", "＞", "＝", "＾", "～", "∼",
        "×", "±", "€", "∞",
    ],
)
def test_unicode_semantic_signs_remain_preserved_and_incomplete(
    g2p: G2P,
    symbol: str,
    normalize: bool,
) -> None:
    source = f"안녕{symbol}안녕"
    result = g2p.convert(source, normalize=normalize)

    assert result.normalized_text == source
    assert result.surface_pronunciation == source
    assert not result.complete
    assert any(
        item.code == "unsupported_symbol"
        for item in result.diagnostics.pronunciation.diagnostics
    )


@pytest.mark.parametrize("normalize", [True, False])
@pytest.mark.parametrize(
    ("character", "code"),
    [
        ("🙂", "unsupported_emoji"),
        ("⭐", "unsupported_symbol"),
        ("\x0b", "unsupported_character"),
        ("\x1c", "unsupported_character"),
        ("\x85", "unsupported_character"),
        ("\u200b", "unsupported_character"),
    ],
)
def test_allowed_punctuation_does_not_hide_unsupported_characters(
    g2p: G2P,
    character: str,
    code: str,
    normalize: bool,
) -> None:
    source = f"“안녕{character}”…"
    result = g2p.convert(source, normalize=normalize)

    assert result.surface_pronunciation == source
    assert not result.complete
    diagnostics = result.diagnostics.pronunciation.diagnostics
    assert [item.code for item in diagnostics] == [code]
    assert diagnostics[0].source_spans[0].surface == character
    span = diagnostics[0].source_spans[0]
    assert (span.start, span.end) == (3, 4)


@pytest.mark.parametrize("percent", ["%", "％"])
def test_percent_digits_require_upstream_conversion(
    g2p: G2P,
    percent: str,
) -> None:
    result = g2p.convert(f"16{percent} “안녕”…")

    assert result.normalized_text == f"16{percent} “안녕”…"
    assert result.surface_pronunciation == f"16{percent} “안녕”…"
    assert not result.complete
    assert result.diagnostics.normalization.diagnostics == ()
    assert [item.code for item in result.diagnostics.pronunciation.diagnostics] == (
        ["unconverted_numeric"] if percent == "%" else ["unconverted_numeric", "unsupported_symbol"]
    )


def test_skip_normalizer_keeps_existing_ascii_punctuation_contract(g2p: G2P) -> None:
    source = "안녕 % * < > = ^ ~"
    result = g2p.convert(source, normalize=False)

    assert result.normalized_text == source
    assert result.surface_pronunciation == source
    assert result.complete
    assert result.diagnostics.pronunciation.diagnostics == ()
