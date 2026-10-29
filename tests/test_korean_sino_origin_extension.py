"""한자어 속성이 조사 앞 연음·비음화와 합성되는지 검증한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.model import AnalysisToken
import g2p_ko.korean.engine as engine


@pytest.mark.parametrize("source,expected,suffix_tag", [
    ("탈색", "탈쌕", None),
    ("탈색이", "탈쌔기", "JKS"),
    ("탈색만", "탈쌩만", "JX"),
])
@pytest.mark.parametrize("analysis", ["actual", "provided_correct"])
def test_sino_origin_composes_with_general_rules(source, expected, suffix_tag, analysis, monkeypatch):
    if analysis == "provided_correct":
        tokens = (AnalysisToken("탈색", "NNG", 0, 2),)
        if suffix_tag:
            tokens += (AnalysisToken(source[2:], suffix_tag, 2, len(source)),)

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
