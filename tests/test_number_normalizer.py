"""베타 숫자 전처리는 입력을 보존하고 기존 발음 단계를 계속 실행한다."""

import pytest

from g2p_ko import G2P, InputValidationError, KoreanTTSNormalizer, normalize_numbers


@pytest.mark.parametrize("text", ["", " 001.20%\r\n", "가\u00a0１２.３", "AI 01.20 국물"])
def test_number_stub_returns_original_string(text):
    assert normalize_numbers(text) is text


def test_number_stub_does_not_skip_english_or_korean_g2p():
    result = G2P().convert("AI 01.20 국물")
    assert result.normalized_text == "에이아이 01.20 국물"
    assert result.surface_pronunciation == "에이아이 01.20 궁물"
    assert not result.complete
    assert any(item.code == "unconverted_numeric" for item in result.diagnostics.pronunciation.diagnostics)
    assert G2P()("123") == "123"


def test_legacy_normalizer_stays_separate_from_number_stub():
    assert normalize_numbers("사과 3개") == "사과 3개"
    assert KoreanTTSNormalizer()("사과 3개") == "사과 세 개"


def test_number_stub_keeps_string_input_contract():
    with pytest.raises(InputValidationError):
        normalize_numbers(123)
