"""어휘 내부 속성과 조사 결합을 정상 분석 및 최신 Kiwi에서 분리 검증한다."""
import json
from pathlib import Path

import pytest

from g2p_ko import G2P
from g2p_ko.pipeline import Pipeline
import g2p_ko.korean.engine as engine_module
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan

CASES = json.loads((Path(__file__).parent / "fixtures/korean_law_boundary_properties.json").read_text(encoding="utf-8"))


def _segment(source, start=0, end=None, *, hard=False):
    end = len(source) if end is None else end
    bounds = {"boundary_before": Boundary.HARD, "boundary_after": Boundary.HARD} if hard else {}
    return OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),), Handler.KOREAN, "검사", **bounds)


def _tokens(case, offset=0):
    return tuple(AnalysisToken(token["form"], token["tag"], token["normalized_start"] + offset,
                               token["normalized_end"] + offset, token.get("morphemes", ()))
                 for token in case["manual_tokens"])


def _check_trace(source, result):
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert 0 <= span.start < span.end <= len(source)
            assert source[span.start:span.end] == span.surface


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("analysis", ["manual", "actual"])
def test_lexical_boundary_composes_with_particle(case, analysis, monkeypatch):
    source = case["text"]
    if analysis == "manual":
        class CorrectAnalyzer:
            def analyze(self, text):
                assert text == source
                return _tokens(case)
        monkeypatch.setattr(engine_module, "KiwiAnalyzer", CorrectAnalyzer)
    converter = G2P()
    result = converter.convert(source)
    assert result.surface_pronunciation in case["allowed_pronunciations"]
    assert converter(source) == result.surface_pronunciation
    assert result.complete
    assert not result.diagnostics.normalization.diagnostics
    assert not result.diagnostics.pronunciation.diagnostics
    trace = Pipeline(max_length=1_000).run(source)
    assert trace.surface_pronunciation == result.surface_pronunciation
    assert trace.complete and not trace.diagnostics
    assert len(result.surface_pronunciation) == len(source)
    _check_trace(source, trace)
    if source[:2] in {"민법", "헌법", "형법"}:
        assert "ko.lexical.tensing" in {item.rule_id for item in trace.rewrites}
        assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in trace.rewrites}


@pytest.mark.parametrize("word", ["민법", "헌법", "형법"])
def test_internal_lexical_boundary_does_not_cross_hard(word, monkeypatch):
    class IslandAnalyzer:
        def analyze(self, text):
            assert text in word
            return (AnalysisToken(text, "NNG", 0, len(text)),)
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", IslandAnalyzer)
    parts = (_segment(word, 0, 1, hard=True), _segment(word, 1, 2, hard=True))
    result = engine_module.pronounce(parts)
    assert result.text == word
    assert "ko.lexical.tensing" not in {item.rule_id for item in result.rewrites}
    _check_trace(word, result)


@pytest.mark.parametrize("case", [row for row in CASES if row["id"] in {"LF02", "LF05", "LF11"}], ids=lambda case: case["id"])
def test_repeated_occurrences_keep_independent_source_coordinates(case, monkeypatch):
    word = case["text"]
    source = word + " " + word
    offset = len(word) + 1
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            return _tokens(case) + _tokens(case, offset)
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", CorrectAnalyzer)
    result = engine_module.pronounce((_segment(source),))
    expected = case["allowed_pronunciations"][0]
    assert result.text == expected + " " + expected
    _check_trace(source, result)
    tense = [item for item in result.rewrites if item.rule_id == "ko.lexical.tensing"]
    assert len(tense) == 2
    assert any(all(span.end <= len(word) for span in item.source_spans) for item in tense)
    assert any(all(span.start >= offset for span in item.source_spans) for item in tense)
