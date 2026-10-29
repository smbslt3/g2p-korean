"""한자 어근 소유권과 기존 규칙 합성을 합성 분석으로 통제한다."""

from unittest.mock import patch

import pytest

from g2p_ko import G2P
from g2p_ko.model import AnalysisToken as T, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.korean import engine
from g2p_ko.korean.morphology import _Annotation
from g2p_ko.korean.owned_sino import owned_sino_spans
from g2p_ko.pipeline import Pipeline


def segment(text, source=None, start=0, **kwargs):
    source = text if source is None else source
    return OutputSegment(text, (SourceSpan.from_source(source, start, start + len(text)),), Handler.KOREAN, "test", **kwargs)


def supplied(source, tokens):
    class Analyzer:
        calls = 0

        def analyze(self, text):
            self.calls += 1
            assert text == source
            return tokens

    analyzer = Analyzer()
    with patch.object(engine, "KiwiAnalyzer", lambda: analyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("주어진 분석만 사용해야 한다."),
    ):
        result = engine.pronounce((segment(source),))
    assert analyzer.calls == 1
    return result


@pytest.mark.parametrize("mode", ["whole", "particle", "adverb"])
@pytest.mark.parametrize("tail", ["", "는", "도는"])
def test_truthful_owner_and_particles(mode, tail):
    source = "실지로" + tail
    tokens = ((T("실지로", "MAG", 0, 3),) if mode == "whole" else
              (T("실지", "NNG", 0, 2), T("로", "JKB" if mode == "particle" else "MAG", 2, 3)))
    tokens += tuple(T(char, "JX", index, index + 1) for index, char in enumerate(tail, 3))
    result = supplied(source, tokens)
    assert result.text == "실찌로" + tail
    assert {item.rule_id for item in result.rewrites} == {"ko.sino.tensing.26"}
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert source[span.start:span.end] == span.surface
    spans = tuple(owned_sino_spans(source, _Annotation.from_tokens(tokens, source)))
    assert spans == ((0, 2, 0, 3),)


@pytest.mark.parametrize("source,tokens", [
    ("실지로", (T("실지로", "NNP", 0, 3),)),
    ("실지로", (T("실지로", "NNG", 0, 3),)),
    ("실지로", (T("실지", "NNP", 0, 2), T("로", "JKB", 2, 3))),
    ("실지로", (T("실지", "NNG", 0, 2), T("로", "NNG", 2, 3))),
    ("실지로", (T("실", "NNG", 0, 1), T("지로", "MAG", 1, 3))),
    ("실지로", (T("실지로", "MAG", 0, 3, (("실지로", "NNP"),)),)),
    ("실지로님", (T("실지로", "MAG", 0, 3), T("님", "XSN", 3, 4))),
    ("가실지로", (T("가", "NNG", 0, 1), T("실지로", "MAG", 1, 4))),
    ("실지로는", (T("실지로", "MAG", 0, 3), T("는", "JX", 3, 4, (("가", "JX"),)))),
    ("실지", (T("실지", "NNG", 0, 2),)),
])
def test_unsupported_owners_do_not_gain_sino(source, tokens):
    result = supplied(source, tokens)
    assert "ko.sino.tensing.26" not in {item.rule_id for item in result.rewrites}


def test_mismatched_surface_is_refused():
    tokens = (T("다른말", "MAG", 0, 3),)
    result = supplied("실지로", tokens)
    assert "ko.sino.tensing.26" not in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize("split", [1, 2])
def test_hard_owner_boundary(split):
    source = "실지로"
    segments = (segment(source[:split], source, boundary_after=Boundary.HARD),
                segment(source[split:], source, split, boundary_before=Boundary.HARD))
    result = engine.pronounce(segments)
    assert "ko.sino.tensing.26" not in {item.rule_id for item in result.rewrites}
    assert result.text == "".join(engine.pronounce((item,)).text for item in segments)


def test_pause_and_punctuation():
    assert engine.pronounce((segment("실지로"),), pause_boundaries=(1,)).text == "실지로"
    assert G2P()("실,지로") == "실,지로"


@pytest.mark.parametrize("source", ["실지로", "실지로는", "실지로도", "실지로 그렇다", "「실지로」", "그건 실지로는 그렇다."])
def test_actual_current_kiwi_and_public_api(source):
    result = G2P().convert(source)
    assert "실찌로" in result.surface_pronunciation
    traced = Pipeline(max_length=1000).run(source)
    assert "ko.sino.tensing.26" in {item.rule_id for item in traced.rewrites}
    assert result.complete
