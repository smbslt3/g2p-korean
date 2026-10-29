"""음운 규칙의 문자열·상세 실행 경로가 같은 발음을 내는지 검증한다."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import g2p_ko.korean._shared as shared_module
import g2p_ko.korean.engine as engine_module
import g2p_ko.korean.morphology as morphology_module
from g2p_ko.errors import BackendUnavailableError
from tests._korean_examples import OFFICIAL_EXAMPLES as _안전_정확_열거_발음
from g2p_ko.merge import _TextSegment
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _segments(
    parts: tuple[tuple[str, Handler, Boundary, Boundary, str | None], ...],
) -> tuple[tuple[OutputSegment, ...], tuple[_TextSegment, ...]]:
    source = "".join(text for text, *_ in parts)
    detailed: list[OutputSegment] = []
    plain: list[_TextSegment] = []
    cursor = 0
    for text, handler, before, after, rule_id in parts:
        end = cursor + len(text)
        detailed.append(
            OutputSegment(
                text,
                (SourceSpan.from_source(source, cursor, end),),
                handler,
                "test",
                rule_id,
                before,
                after,
            )
        )
        plain.append(_TextSegment(text, handler, "test", rule_id, before, after))
        cursor = end
    return tuple(detailed), tuple(plain)


@pytest.mark.parametrize(
    "source",
    ("꽃", "옷이", "넋이", "국물", "신라", "국밥", "좋다", "많아", "굳히다", "십육", "스물여섯", "밟다", "맑게"),
)
def test_string_and_detailed_paths_agree_on_rule_families(source: str) -> None:
    detailed, plain = _segments(((source, Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),))

    assert engine_module.pronounce_text(plain) == engine_module.pronounce(detailed).text


def test_string_and_detailed_paths_agree_on_all_official_exact_forms() -> None:
    for source, expected in _안전_정확_열거_발음.items():
        detailed, plain = _segments(((source, Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),))

        assert engine_module.pronounce_text(plain) == engine_module.pronounce(detailed).text == expected


@pytest.mark.parametrize("source", ["곧이어", "넓둥글다", "의견란은", "히읗은", "밭이", "할 일"])
def test_hard_boundaries_isolate_analysis_as_well_as_rewriting(source: str) -> None:
    for split in range(1, len(source)):
        detailed, plain = _segments(tuple(
            (part, Handler.KOREAN, Boundary.HARD, Boundary.HARD, None)
            for part in (source[:split], source[split:])
        ))
        expected = "".join(engine_module.pronounce((part,)).text for part in detailed)
        assert engine_module.pronounce(detailed).text == expected
        assert engine_module.pronounce_text(plain) == expected


@pytest.mark.parametrize("boundary", (Boundary.WORD, Boundary.MORPHEME, Boundary.HARD))
def test_string_and_detailed_paths_share_cross_segment_boundaries(boundary: Boundary) -> None:
    detailed, plain = _segments(
        (
            ("국", Handler.KOREAN, Boundary.WORD, boundary, None),
            ("물", Handler.KOREAN, boundary, Boundary.WORD, None),
        )
    )

    assert engine_module.pronounce_text(plain) == engine_module.pronounce(detailed).text


def test_string_and_detailed_paths_share_handler_and_punctuation_islands() -> None:
    detailed, plain = _segments(
        (
            ("국", Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),
            (",", Handler.PROTECTED, Boundary.WORD, Boundary.WORD, None),
            ("물", Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),
            ("국", Handler.ENGLISH, Boundary.WORD, Boundary.WORD, "english.letter_names.v1"),
            ("물", Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),
        )
    )

    assert engine_module.pronounce_text(plain) == engine_module.pronounce(detailed).text


@pytest.mark.parametrize("analysis", ("valid", "invalid", "failed", "unavailable"))
def test_string_path_preserves_morphology_decision_without_trace_objects(analysis: str) -> None:
    source = "우리의 맑게 밟다"
    detailed, plain = _segments(((source, Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),))

    class Analyzer:
        def analyze(self, _text: str) -> tuple[AnalysisToken, ...]:
            if analysis == "unavailable":
                raise BackendUnavailableError("테스트용 분석기 부재")
            if analysis == "failed":
                raise RuntimeError("테스트용 분석 실패")
            if analysis == "invalid":
                return (AnalysisToken("불일치", "NP", 0, 2),)
            return (
                AnalysisToken("우리", "NP", 0, 2),
                AnalysisToken("의", "JKG", 2, 3),
                AnalysisToken("맑", "VA", 4, 5),
                AnalysisToken("게", "EC", 5, 6),
            )

    with patch.object(engine_module, "KiwiAnalyzer", Analyzer):
        expected = engine_module.pronounce(detailed)
        with (
            patch.object(engine_module, "OutputSegment", side_effect=AssertionError("상세 조각 생성")),
            patch.object(shared_module, "Rewrite", side_effect=AssertionError("변환 기록 생성")),
            patch.object(morphology_module, "Diagnostic", side_effect=AssertionError("진단 생성")),
            patch.object(SourceSpan, "from_source", side_effect=AssertionError("원문 span 생성")),
        ):
            assert engine_module.pronounce_text(plain) == expected.text

    if analysis != "valid":
        code = "analyzer_unavailable" if analysis == "unavailable" else "analyzer_failed"
        assert any(item.code == code for item in expected.diagnostics)
