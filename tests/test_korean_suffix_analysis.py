"""어휘 등록 여부와 다른 후보의 존재가 접미사 분석을 좌우하지 않는지 검사한다."""

from unittest.mock import patch

import pytest

import g2p_ko.korean.engine as engine_module
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _segment(source, start=0, end=None, *, hard=False):
    end = len(source) if end is None else end
    options = {"boundary_before": Boundary.HARD, "boundary_after": Boundary.HARD} if hard else {}
    return OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),),
                         Handler.KOREAN, "test", **options)


@pytest.mark.parametrize(("particle", "tag", "expected"), [
    ("", "", "통신녁"), ("은", "JX", "통신녀근"), ("도", "JX", "통신녁또"),
    ("이", "JKS", "통신녀기"), ("의", "JKG", "통신녀게"),
])
def test_productive_suffix_is_analyzed_without_an_unrelated_trigger(particle, tag, expected):
    # 통신력의 표준 사전 발음을 주장하지 않는다. 정상 NNG+XSN 분석을 전제로
    # 제20항의 가능한 합성 발음을 계산하는 기존 규칙의 도달성과 조사 결합을 검사한다.
    # https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=27&pageIndex=1&qna_seq=329357
    source = "통신력" + particle
    calls = []

    class CorrectAnalyzer:
        def analyze(self, text):
            calls.append(text)
            assert text == source
            tokens = (AnalysisToken("통신", "NNG", 0, 2), AnalysisToken("력", "XSN", 2, 3))
            return tokens + ((AnalysisToken(particle, tag, 3, 4),) if particle else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert calls == [source]
    assert result.text == expected
    assert "ko.liquid.suffix.20" in {item.rule_id for item in result.rewrites}
    assert not result.diagnostics


@pytest.mark.parametrize(("source", "tag", "expected", "expected_calls"), [
    ("난로", "NNG", "날로", []),
    ("대관령", "NNP", "대괄령", ["대관령"]),
])
def test_candidate_is_not_a_decision_to_nasalize(source, tag, expected, expected_calls):
    calls = []

    class CorrectAnalyzer:
        def analyze(self, text):
            calls.append(text)
            return (AnalysisToken(text, tag, 0, len(text)),)

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert calls == expected_calls
    assert result.text == expected
    assert "ko.liquid.suffix.20" not in {item.rule_id for item in result.rewrites}


def test_suffix_candidate_does_not_cross_hard_boundary():
    source = "통신력"
    calls = []

    class CorrectAnalyzer:
        def analyze(self, text):
            calls.append(text)
            return (AnalysisToken(text, "NNG", 0, len(text)),)

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source, 0, 2, hard=True),
                                          _segment(source, 2, 3, hard=True)))
    assert not calls
    assert result.text == source


def test_failed_analysis_does_not_silently_choose_a_suffix_reading():
    class UnavailableAnalyzer:
        def analyze(self, text):
            raise RuntimeError("분석 실패 대조군")

    with patch.object(engine_module, "KiwiAnalyzer", UnavailableAnalyzer):
        result = engine_module.pronounce((_segment("통신력"),))
    assert result.text == "통신력"
    assert result.diagnostics
