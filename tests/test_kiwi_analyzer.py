"""공식 Kiwi.tokenize 기반 분석기의 좌표 병합을 검증한다."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import g2p_ko.analyzer as analyzer_module
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.errors import BackendUnavailableError
from g2p_ko.model import AnalysisToken


class FakeKiwi:
    """tokenize 호출과 반환값을 통제하는 가벼운 Kiwi 대역이다."""

    def __init__(self, parts: list[SimpleNamespace]) -> None:
        self.parts = parts
        self.calls: list[str] = []

    def tokenize(self, text: str) -> list[SimpleNamespace]:
        self.calls.append(text)
        return self.parts


class FakeSaisiotKiwi:
    """사이시옷 분해 옵션과 offset 반환을 기록한다."""

    def __init__(self, parts: list[SimpleNamespace]) -> None:
        self.parts = parts
        self.calls: list[tuple[str, bool, bool]] = []

    def tokenize(
        self,
        text: str,
        *,
        split_complex: bool,
        saisiot: bool,
    ) -> list[SimpleNamespace]:
        self.calls.append((text, split_complex, saisiot))
        return self.parts


def _part(form: str, tag: str, start: int, length: int) -> SimpleNamespace:
    return SimpleNamespace(form=form, tag=tag, start=start, len=length)


def test_tokenize_decompositions_are_merged_by_source_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kiwi = FakeKiwi([
        _part("하", "VV", 0, 1),
        _part("었", "EP", 0, 1),
        _part("다", "EF", 1, 1),
    ])

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)
    tokens = KiwiAnalyzer().analyze("했다")

    assert kiwi.calls == ["했다"]
    assert tokens == (
        AnalysisToken("했", "VV+EP", 0, 1),
        AnalysisToken("다", "EF", 1, 2),
    )


def test_nested_source_spans_are_merged_to_the_outer_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kiwi = FakeKiwi([
        _part("이", "VCP", 0, 1),
        _part("ᆸ니다", "EF", 0, 3),
        _part(".", "SF", 3, 1),
    ])
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)

    assert KiwiAnalyzer().analyze("입니다.") == (
        AnalysisToken("입니다", "VCP+EF", 0, 3),
        AnalysisToken(".", "SF", 3, 4),
    )


@pytest.mark.parametrize(
    ("text", "parts", "expected"),
    [
        (
            "3개라고",
            [
                _part("3", "SN", 0, 1),
                _part("개", "NNB", 1, 1),
                _part("이", "VCP", 2, 0),
                _part("라고", "EC", 2, 2),
            ],
            (
                AnalysisToken("3", "SN", 0, 1),
                AnalysisToken("개", "NNB", 1, 2),
                AnalysisToken("라고", "VCP+EC", 2, 4),
            ),
        ),
        (
            "닥",
            [
                _part("하", "VV", 0, 0),
                _part("다", "EF", 0, 1),
                _part("ᆨ", "Z_CODA", 0, 1),
            ],
            (AnalysisToken("닥", "VV+EF+Z_CODA", 0, 1),),
        ),
    ],
)
def test_zero_length_tags_are_attached_to_the_next_source_span(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    parts: list[SimpleNamespace],
    expected: tuple[AnalysisToken, ...],
) -> None:
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", FakeKiwi(parts))

    assert KiwiAnalyzer().analyze(text) == expected


def test_tokenize_coordinates_preserve_gaps_and_combined_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kiwi = FakeKiwi([
        _part("할", "VV+ETM", 0, 1),
        _part("것", "NNB", 2, 1),
    ])

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)
    tokens = KiwiAnalyzer().analyze("할 것")

    assert [(item.form, item.tag, item.normalized_start, item.normalized_end) for item in tokens] == [
        ("할", "VV+ETM", 0, 1),
        ("것", "NNB", 2, 3),
    ]


def test_kiwi_is_created_lazily_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[FakeKiwi] = []

    def create_kiwi() -> FakeKiwi:
        kiwi = FakeKiwi([_part("가", "VV", 0, 1)])
        created.append(kiwi)
        return kiwi

    monkeypatch.setattr(analyzer_module, "_create_kiwi", create_kiwi)
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", None)
    analyzer = KiwiAnalyzer()

    assert not created
    analyzer.analyze("가")
    analyzer.analyze("가")

    assert len(created) == 1
    assert created[0].calls == ["가", "가"]


def test_missing_kiwi_reports_dependency_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "kiwipiepy", None)
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", None)
    analyzer = KiwiAnalyzer()

    with pytest.raises(
        BackendUnavailableError,
        match="프로젝트 의존성을 설치하세요",
    ) as captured:
        analyzer.analyze("했다")

    assert isinstance(captured.value.__cause__, ImportError)


def test_kiwi_without_tokenize_reports_unavailable_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", object())
    analyzer = KiwiAnalyzer()

    with pytest.raises(BackendUnavailableError, match="Kiwi.tokenize"):
        analyzer.analyze("했다")


def test_large_tokenize_result_is_converted_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 5_000
    text = "가" * count
    kiwi = FakeKiwi([_part("가", "NNG", index, 1) for index in range(count)])

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)
    tokens = KiwiAnalyzer().analyze(text)

    assert kiwi.calls == [text]
    assert len(tokens) == count
    assert tokens[-1].normalized_end == count


def test_token_offset_outside_text_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        analyzer_module,
        "_runtime_kiwi",
        FakeKiwi([_part("가", "NNG", 3, 1)]),
    )

    with pytest.raises(ValueError, match="offset"):
        KiwiAnalyzer().analyze("가")


def test_saisiot_positions_use_kiwi_decomposition_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kiwi = FakeSaisiotKiwi([
        _part("내", "NNG", 0, 1),
        _part("ㅅ", "Z_SIOT", 0, 1),
        _part("가", "NNG", 1, 1),
        _part("ㅅ", "Z_SIOT", 0, 1),
    ])
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)

    positions = KiwiAnalyzer().saisiot_positions("냇가")

    assert positions == (0,)
    assert kiwi.calls == [("냇가", True, True)]


def test_saisiot_position_outside_text_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kiwi = FakeSaisiotKiwi([_part("ㅅ", "Z_SIOT", 9, 1)])
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", kiwi)

    with pytest.raises(ValueError, match="offset"):
        KiwiAnalyzer().saisiot_positions("냇가")


def test_legacy_kiwi_without_tokenize_reports_unavailable_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", object())

    with pytest.raises(BackendUnavailableError, match="Kiwi.tokenize"):
        KiwiAnalyzer().saisiot_positions("냇가")
