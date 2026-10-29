"""정상 통짜 명사와 성분 분석이 같은 파생어 발음을 생성하는지 검사한다."""

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


@pytest.mark.parametrize(("base", "particle", "tag", "expected"), [
    ("추진", "", "", "추진녁"), ("추진", "만", "JX", "추진녕만"),
    ("해군", "", "", "해군녁"), ("해군", "만", "JX", "해군녕만"),
    ("추진", "이", "JKS", "추진녀기"), ("해군", "은", "JX", "해군녀근"),
])
@pytest.mark.parametrize("analysis", ["whole", "split", "actual"])
def test_force_suffix_generalizes_from_base_with_valid_analysis(base, particle, tag, expected, analysis):
    # 기본형과 -만은 공식 표제어에서 확인했다. -이/-은은 조사 앞 연음 합성 대조다.
    # https://stdict.korean.go.kr/search/searchView.do?word_no=334636
    # https://stdict.korean.go.kr/search/searchView.do?word_no=364318
    source = base + "력" + particle
    if analysis == "actual":
        assert G2P()(source) == G2P().convert(source).surface_pronunciation == expected
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            tokens = ((AnalysisToken(base + "력", "NNG", 0, 3),) if analysis == "whole" else
                      (AnalysisToken(base, "NNG", 0, 2), AnalysisToken("력", "XSN", 2, 3)))
            return tokens + ((AnalysisToken(particle, tag, 3, 4),) if particle else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert "ko.liquid.suffix.20" in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [("인류", "일류"), ("탄력", "탈력"), ("대관령", "대괄령")])
def test_homographic_final_syllables_are_not_blindly_resegmented(source, expected):
    class CorrectAnalyzer:
        def analyze(self, text):
            return (AnalysisToken(text, "NNP" if source == "대관령" else "NNG", 0, len(text)),)

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        assert engine_module.pronounce((_segment(source),)).text == expected


@pytest.mark.parametrize("source", ["추진력", "해군력"])
def test_derived_feature_keeps_hard_boundary(source):
    parts = (_segment(source, 0, 2, hard=True), _segment(source, 2, 3, hard=True))
    assert engine_module.pronounce(parts).text == "".join(engine_module.pronounce((part,)).text for part in parts)


@pytest.mark.parametrize(("base", "tail", "tail_tag", "expected"), [
    ("출연", "료", "XSN", "추련뇨"), ("수신", "료", "XSN", "수신뇨"),
    ("등산", "로", "NNG", "등산노"), ("이원", "론", "XSN", "이원논"),
])
@pytest.mark.parametrize("analysis", ["whole", "split", "actual"])
def test_typed_attachment_has_same_sound_for_whole_and_split_analysis(base, tail, tail_tag, expected, analysis):
    source = base + tail
    if analysis == "actual":
        assert G2P()(source) == expected
        return

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            return ((AnalysisToken(source, "NNG", 0, len(source)),) if analysis == "whole" else
                    (AnalysisToken(base, "NNG", 0, len(base)),
                     AnalysisToken(tail, tail_tag, len(base), len(source))))

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    assert "ko.liquid.suffix.20" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize("changed", [
    {"verified_base": False}, {"base_form": "산"}, {"base_tag": "NNG+JX"},
    {"tail_tag": "NNG+JX"}, {"tail_tag": "NNG_OTHER"},
    {"whole_hanja_compatible": False}, {"nasal_liquid": False},
])
def test_nominal_attachment_requires_typed_unambiguous_evidence(changed):
    from g2p_ko.korean.attachment_policy import licenses_nominal_attachment

    arguments = dict(base_form="등산", base_tag="NNG", tail_form="로", tail_tag="NNG",
                     verified_base=True, expected_tail_form="로", expected_tail_tag="NNG",
                     nasal_liquid=True, whole_hanja_compatible=True)
    assert licenses_nominal_attachment(**(arguments | changed)) is False
