"""정규화 실행 상태와 서수 특수형의 회귀를 검증한다."""

from __future__ import annotations

import pytest

from g2p_ko import InputValidationError
from g2p_ko.normalizer import KoreanTTSNormalizer


@pytest.mark.parametrize("method", ["normalize", "convert"])
def test_plain_korean_text_respects_output_limit(method: str) -> None:
    normalizer = KoreanTTSNormalizer(max_output_length=1)

    with pytest.raises(InputValidationError, match="최대 길이 1"):
        getattr(normalizer, method)("가나다")


@pytest.mark.parametrize("source", ["abc 😀", "abc 😀 3개"])
def test_unmatched_characters_are_all_diagnosed_after_an_unresolved_token(
    source: str,
) -> None:
    result = KoreanTTSNormalizer().convert(source)

    assert result.normalized_text == source.replace("3개", "세 개")
    assert not result.complete
    assert [(item.code, item.source_spans[0].surface) for item in result.diagnostics] == [
        ("unconverted_latin", "abc"),
        ("unsupported_symbol", "😀"),
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("-1번째", "마이너스 일 번째"),
        ("+1번째", "플러스 일 번째"),
        ("−1번째", "마이너스 일 번째"),
    ],
)
def test_signed_one_does_not_use_first_ordinal_form(source: str, expected: str) -> None:
    result = KoreanTTSNormalizer().convert(source)

    assert result.complete
    assert result.normalized_text == expected


def test_unsigned_one_keeps_first_ordinal_form() -> None:
    assert KoreanTTSNormalizer().normalize("1번째") == "첫 번째"


def test_output_limit_accumulates_protected_and_rendered_segments() -> None:
    source = "가 https://example.com 3개"
    expected = "가 https://example.com 세 개"
    exact = KoreanTTSNormalizer(max_output_length=len(expected))
    too_short = KoreanTTSNormalizer(max_output_length=len(expected) - 1)

    assert exact.convert(source).normalized_text == expected
    with pytest.raises(InputValidationError, match="최대 길이"):
        too_short.convert(source)
