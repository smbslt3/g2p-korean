"""공개 G2P batch API의 순서·지연·오류 계약을 검증한다."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import cast, get_type_hints

import pytest

from g2p_ko import G2P, G2PResult, InputValidationError


@pytest.mark.parametrize("normalize", [True, False])
def test_batch_results_preserve_order_and_match_single_item_paths(
    normalize: bool,
) -> None:
    sources = (
        "",
        "국물",
        "ABC ж",
        "https://example.com/path에서 냇가",
        "좋소",
        "\u1100\u1161꽃",
    )
    g2p = G2P()

    pronounced = list(g2p.pronounce_many(iter(sources), normalize=normalize))
    detailed = list(g2p.convert_many(iter(sources), normalize=normalize))

    assert all(isinstance(result, str) for result in pronounced)
    assert pronounced == [g2p(source, normalize=normalize) for source in sources]
    assert all(isinstance(result, G2PResult) for result in detailed)
    assert [result.source for result in detailed] == list(sources)
    assert [result.surface_pronunciation for result in detailed] == pronounced
    assert detailed == [g2p.convert(source, normalize=normalize) for source in sources]


def test_batch_api_return_annotations_match_iterator_contract() -> None:
    assert get_type_hints(G2P.pronounce_many)["return"] == Iterator[str]
    assert get_type_hints(G2P.convert_many)["return"] == Iterator[G2PResult]


@pytest.mark.parametrize("method_name", ["pronounce_many", "convert_many"])
def test_batch_iterators_consume_exactly_one_input_for_each_result(
    method_name: str,
) -> None:
    consumed: list[object] = []

    def source() -> Iterator[object]:
        for item in ("국물", None, "냇가"):
            consumed.append(item)
            yield item

    g2p = G2P()
    method = getattr(g2p, method_name)
    results = method(cast(Iterable[str], source()))

    assert iter(results) is results
    assert consumed == []
    first = next(results)
    assert consumed == ["국물"]
    if isinstance(first, G2PResult):
        assert first.surface_pronunciation == "궁물"
    else:
        assert first == "궁물"
    with pytest.raises(InputValidationError, match="문자열"):
        next(results)
    assert consumed == ["국물", None]


class _SourceFailure(RuntimeError):
    """원본 iterator의 실패가 바뀌지 않는지 확인하는 식별용 예외다."""


@pytest.mark.parametrize("method_name", ["pronounce_many", "convert_many"])
def test_batch_iterators_propagate_source_failure_at_the_failing_next(
    method_name: str,
) -> None:
    def source() -> Iterator[str]:
        yield "국물"
        raise _SourceFailure("두 번째 항목을 만들 수 없습니다.")

    method = getattr(G2P(), method_name)
    results = method(source())

    next(results)
    with pytest.raises(_SourceFailure, match="두 번째"):
        next(results)


@pytest.mark.parametrize("method_name", ["pronounce_many", "convert_many"])
@pytest.mark.parametrize("texts", ["국물", b"text", 7, None])
def test_batch_apis_reject_a_string_or_non_iterable_container_immediately(
    method_name: str,
    texts: object,
) -> None:
    method = getattr(G2P(), method_name)

    with pytest.raises(InputValidationError, match="iterable"):
        method(cast(Iterable[str], texts))


@pytest.mark.parametrize("method_name", ["pronounce_many", "convert_many"])
def test_batch_normalize_option_is_validated_before_input_consumption(
    method_name: str,
) -> None:
    consumed = False

    def source() -> Iterator[str]:
        nonlocal consumed
        consumed = True
        yield "국물"

    method = getattr(G2P(), method_name)

    with pytest.raises(InputValidationError, match="normalize"):
        method(source(), normalize=cast(bool, 0))
    assert not consumed
