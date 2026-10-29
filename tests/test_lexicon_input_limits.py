"""사용자 입력 길이 제한과 사전 값의 검증 예산을 독립적으로 확인한다."""

from __future__ import annotations

import pytest

from g2p_ko import G2P, InputValidationError
from g2p_ko import analyzer as analyzer_module
from g2p_ko.normalizer import KoreanTTSNormalizer


@pytest.mark.parametrize("factory", [KoreanTTSNormalizer])
@pytest.mark.parametrize(("value", "expected"), [("에이", "에이"), ("3개", "세 개")])
def test_one_character_input_can_expand_to_a_longer_lexicon_value(
    factory: type[KoreanTTSNormalizer] | type[G2P],
    value: str,
    expected: str,
) -> None:
    converter = factory(max_length=1, lexicon={"A": value})

    assert converter("A") == expected
    result = converter.convert("A")
    assert result.normalized_text == expected
    assert result.complete


@pytest.mark.parametrize("factory", [KoreanTTSNormalizer])
@pytest.mark.parametrize("lexicon", [None, {}, {"A": "에이"}])
def test_user_input_limit_remains_active_after_lexicon_validation(
    factory: type[KoreanTTSNormalizer] | type[G2P],
    lexicon: dict[str, str] | None,
) -> None:
    converter = factory(max_length=1, lexicon=lexicon)

    for operation in (converter, converter.convert):
        with pytest.raises(InputValidationError, match="입력이 최대 길이 1"):
            operation("AA")


def test_g2p_input_limit_also_applies_when_normalization_is_skipped() -> None:
    converter = G2P(max_length=1)

    for operation in (converter, converter.convert):
        with pytest.raises(InputValidationError, match="입력이 최대 길이 1"):
            operation("에이", normalize=False)


def test_expansion_can_use_the_exact_configured_output_budget() -> None:
    normalizer = KoreanTTSNormalizer(
        max_length=1,
        max_output_length=2,
        lexicon={"A": "에이"},
    )

    assert normalizer.normalize("A") == "에이"
    assert normalizer.convert("A").normalized_text == "에이"
    with pytest.raises(InputValidationError, match="출력이 최대 길이 1"):
        KoreanTTSNormalizer(max_length=1, max_output_length=1, lexicon={"A": "에이"})


def test_default_output_budget_still_bounds_lexicon_values() -> None:
    normalizer = KoreanTTSNormalizer(max_length=1, lexicon={"A": "가" * 16})

    assert normalizer("A") == "가" * 16
    with pytest.raises(InputValidationError, match="출력이 최대 길이 16"):
        KoreanTTSNormalizer(max_length=1, lexicon={"A": "가" * 17})


@pytest.mark.parametrize("method", ["normalize", "convert"])
def test_multiple_expansions_share_the_call_output_budget(method: str) -> None:
    normalizer = KoreanTTSNormalizer(
        max_length=3,
        max_output_length=4,
        lexicon={"A": "에이"},
    )

    with pytest.raises(InputValidationError, match="출력이 최대 길이 4"):
        getattr(normalizer, method)("A A")


@pytest.mark.parametrize("max_length", [1, 5_000])
def test_raw_lexicon_value_bound_is_independent_of_user_input_limit(max_length: int) -> None:
    normalizer = KoreanTTSNormalizer(
        max_length=max_length,
        max_output_length=8_192,
        lexicon={"A": "가" * 4_096},
    )

    assert normalizer("A") == "가" * 4_096
    with pytest.raises(InputValidationError, match="사전 값 길이가 최대 4096"):
        KoreanTTSNormalizer(
            max_length=max_length,
            max_output_length=8_192,
            lexicon={"A": "가" * 4_097},
        )


@pytest.mark.parametrize("max_length", [1, 5_000])
def test_normalized_lexicon_value_cannot_exceed_the_value_bound(max_length: int) -> None:
    normalizer = KoreanTTSNormalizer(
        max_length=max_length,
        max_output_length=8_192,
        lexicon={"A": "3개 " * 1_024},
    )

    assert normalizer("A") == "세 개 " * 1_024
    assert len(normalizer("A")) == 4_096
    with pytest.raises(InputValidationError, match="기본 정규화 값 길이가 최대 4096"):
        KoreanTTSNormalizer(
            max_length=max_length,
            max_output_length=8_192,
            lexicon={"A": "3개 " * 1_024 + "3"},
        )


@pytest.mark.parametrize("factory", [KoreanTTSNormalizer])
@pytest.mark.parametrize("value", ["😀", "Minnie", "①", "ㅏ"])
def test_small_input_limit_preserves_incomplete_lexicon_rejection(
    factory: type[KoreanTTSNormalizer] | type[G2P],
    value: str,
) -> None:
    with pytest.raises(InputValidationError, match="완결된 발화형"):
        factory(max_length=1, lexicon={"A": value})


@pytest.mark.parametrize("factory", [KoreanTTSNormalizer])
def test_compiled_lexicon_self_check_still_rejects_further_replacement(
    factory: type[KoreanTTSNormalizer] | type[G2P],
) -> None:
    with pytest.raises(InputValidationError, match="완결된 발화형"):
        factory(max_length=1, lexicon={"A": "에이", "에이": "다른"})


def test_numeric_lexicon_validation_is_deterministic_and_keeps_backend_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_calls: list[None] = []

    def unexpected_backend() -> object:
        backend_calls.append(None)
        raise AssertionError("사전 검증 중 Kiwi를 초기화해서는 안 됩니다.")

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", None)
    monkeypatch.setattr(analyzer_module, "_create_kiwi", unexpected_backend)

    for _ in range(2):
        normalizer = KoreanTTSNormalizer(max_length=1, lexicon={"A": "사과 3개"})
        assert normalizer("A") == "사과 세 개"
        assert normalizer.convert("A").complete

    assert backend_calls == []
