"""어휘 경계 속성과 비표준 관측형의 대조를 검증한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.model import AnalysisToken
import g2p_ko.korean.engine as engine


@pytest.mark.parametrize("source,expected,base,suffix_tag", [
    ("물살", "물쌀", "물살", None),
    ("물살이", "물싸리", "물살", "JKS"),
    ("물살만", "물쌀만", "물살", "JX"),
    ("온열", "오녈", "온열", None),
    ("등기를", "등기를", "등기", "JKO"),
])
@pytest.mark.parametrize("analysis", ["actual", "provided_correct"])
def test_lexical_fact_and_standard_pronunciation_controls(source, expected, base, suffix_tag, analysis, monkeypatch):
    if analysis == "provided_correct":
        tokens = (AnalysisToken(base, "NNG", 0, len(base)),)
        if suffix_tag:
            tokens += (AnalysisToken(source[len(base):], suffix_tag, len(base), len(source)),)

        class CorrectAnalyzer:
            def analyze(self, text):
                assert text == source
                return tokens

        monkeypatch.setattr(engine, "KiwiAnalyzer", CorrectAnalyzer)
    result = G2P().convert(source)
    assert result.surface_pronunciation == expected
    assert result.complete
    assert not result.diagnostics.normalization.diagnostics
    assert not result.diagnostics.pronunciation.diagnostics
