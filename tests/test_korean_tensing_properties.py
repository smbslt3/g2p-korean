"""한자어 속성과 고유어 합성 경음화가 조사·파생형에 합성되는지 검증한다."""

from unittest.mock import patch

import pytest

from g2p_ko import G2P
import g2p_ko.korean.engine as engine_module
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _segment(source, start=0, end=None, *, hard=False):
    end = len(source) if end is None else end
    boundaries = {"boundary_before": Boundary.HARD, "boundary_after": Boundary.HARD} if hard else {}
    return OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),),
                         Handler.KOREAN, "test", **boundaries)


@pytest.mark.parametrize(("base", "tail", "tag", "expected", "rule"), [
    ("출동", "", "", "출똥", "ko.sino.tensing.26"),
    ("출동", "이", "JKS", "출똥이", "ko.sino.tensing.26"),
    ("출동", "은", "JX", "출똥은", "ko.sino.tensing.26"),
    ("출동", "만", "JX", "출똥만", "ko.sino.tensing.26"),
    ("손길", "", "", "손낄", "ko.lexical.tensing"),
    ("손길", "이", "JKS", "손끼리", "ko.lexical.tensing"),
    ("손길", "은", "JX", "손끼른", "ko.lexical.tensing"),
    ("손길", "만", "JX", "손낄만", "ko.lexical.tensing"),
    ("손길", "도", "JX", "손낄도", "ko.lexical.tensing"),
])
@pytest.mark.parametrize("analysis", ["whole", "actual"])
def test_registered_tensing_properties_compose_with_particles(base, tail, tag, expected, rule, analysis):
    # 기본형은 공식 규범·사전, 조사 결합은 일반 연음 규칙으로 기대값을 정한다.
    # https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=15598
    # https://www.korean.go.kr/kornorms/regltn/regltnView.do?regltn_code=0002
    source = base + tail
    if analysis == "actual":
        result = G2P().convert(source)
        assert result.surface_pronunciation == expected
        assert result.complete
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken(base, "NNG", 0, len(base)),)
            return tokens + ((AnalysisToken(tail, tag, len(base), len(source)),) if tail else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert rule in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [
    ("출동하다", "출똥하다"), ("출동해", "출똥해"), ("출동했다", "출똥핻따"),
])
def test_sino_property_remains_available_before_verbal_derivation(source, expected):
    assert G2P()(source) == expected


@pytest.mark.parametrize("source", ["출동", "손길"])
def test_registered_tensing_respects_hard_boundaries(source):
    parts = (_segment(source, 0, 1, hard=True), _segment(source, 1, 2, hard=True))
    assert engine_module.pronounce(parts).text == "".join(engine_module.pronounce((part,)).text for part in parts)


def test_sino_property_requires_a_compatible_pos():
    # 한자어 속성의 품사 조건에 대한 합성 입력이며 실제 발음 정확도 분모와 구분한다.
    source = "출동"
    class NonNounAnalyzer:
        def analyze(self, text):
            return (AnalysisToken(text, "VV", 0, len(text)),)

    with patch.object(engine_module, "KiwiAnalyzer", NonNounAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert "ko.sino.tensing.26" not in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("tail", "expected"), [("", "손낄"), ("이", "손끼리")])
def test_native_compound_keeps_valid_component_analysis(tail, expected):
    source = "손길" + tail

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken("손", "NNG", 0, 1), AnalysisToken("길", "NNG", 1, 2))
            return tokens + ((AnalysisToken("이", "JKS", 2, 3),) if tail else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert "ko.lexical.tensing" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("base", "particle", "expected", "rule"), [
    ("출전", "", "출쩐", "ko.sino.tensing.26"),
    ("출전", "이", "출쩌니", "ko.sino.tensing.26"),
    ("갈대", "", "갈때", "ko.lexical.tensing"),
    ("갈대", "가", "갈때가", "ko.lexical.tensing"),
    ("날짐승", "", "날찜승", "ko.ending.tensing.27"),
    ("날짐승", "이", "날찜승이", "ko.ending.tensing.27"),
])
@pytest.mark.parametrize("analysis", ["whole", "actual"])
def test_related_tensing_families_reuse_their_distinct_properties(base, particle, expected, rule, analysis):
    # 표제어의 규범 발음과 조사 연음을 분리해 구성한 회귀다.
    # https://stdict.korean.go.kr/search/searchView.do?word_no=334706
    # https://stdict.korean.go.kr/search/searchView.do?word_no=390781
    # https://stdict.korean.go.kr/search/searchView.do?word_no=60042
    source = base + particle
    if analysis == "actual":
        assert G2P()(source) == expected
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = (AnalysisToken(base, "NNG", 0, len(base)),)
            return tokens + ((AnalysisToken(particle, "JKS", len(base), len(source)),) if particle else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert rule in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [("물들다", "물들다"), ("열다", "열다")])
def test_liquid_dental_spelling_does_not_imply_sino_tensing(source, expected):
    assert G2P()(source) == expected
