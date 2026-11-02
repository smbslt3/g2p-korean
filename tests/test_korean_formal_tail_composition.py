"""형태소 경계와 활용형 포장이 바뀌어도 같은 음운 규칙을 적용한다."""

from unittest.mock import patch

import pytest

from g2p_ko import G2P
from g2p_ko.korean import engine
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


@pytest.mark.parametrize(("source", "expected"), [
    ("다같이", "다가치"),
    ("같이해", "가치해"),
    ("같인", "가친"),
    ("붙임성", "부침썽"),
    ("붙임성이", "부침썽이"),
    ("붙임성은", "부침썽은"),
    ("햇볕이", "핻뼈치"),
    ("햇볕을", "핻뼈틀"),
    ("햇볕은", "핻뼈튼"),
    ("어김없이", "어기멉씨"),
    ("끊임없이", "끄니멉씨"),
    ("쓸데없이가", "쓸데업씨가"),
    ("많이를", "마니를"),
    ("덧붙여도", "덛뿌처도"),
    ("불붙인", "불부친"),
    ("밀어붙여", "미러부처"),
    ("허브밭이야?", "허브바치야?"),
    ("감귤밭이에요.", "감귤바치에요."),
    ("끝일껄?", "끄칠껄?"),
    ("핏이였어.", "피시여써."),
])
def test_observed_tail_packaging_uses_compositional_pronunciation(source, expected):
    # 원문 띄어쓰기나 활용형을 교정하지 않고 공급된 표면의 발음만 확인한다.
    g = G2P()
    result = g.convert(source)
    assert result.normalized_text == source
    assert result.surface_pronunciation == g(source) == expected
    assert result.complete


@pytest.mark.parametrize(("source", "fragment"), [
    ("그냥 같이해.", "가치해"),
    ("친구와 다같이 간다.", "다가치"),
    ("붙임성이 좋다.", "부침썽이"),
    ("햇볕이 따갑다.", "핻뼈치"),
    ("뭘 먹을지는 어김없이 고민되네요.", "어기멉씨"),
    ("끊임없이 이야기한다.", "끄니멉씨"),
    ("쓸데없이가 아니고.", "쓸데업씨가"),
    ("아낌없이 나누었다.", "아끼멉씨"),
    ("남김없이 먹었다.", "남기멉씨"),
    ("거침없이 달린다.", "거치멉씨"),
    ("틀림없이 온다.", "틀리멉씨"),
    ("많이를 못해.", "마니를"),
    ("설명을 덧붙여도 된다.", "덛뿌처도"),
    ("그것도 두 개 붙여논거잖아.", "부처논거자나"),
    ("끝이 난다.", "끄치"),
])
def test_same_rule_survives_following_context(source, fragment):
    g = G2P()
    result = g.convert(source)
    assert fragment in result.surface_pronunciation
    assert g(source) == result.surface_pronunciation
    assert result.complete


def _segment(source, start=0, end=None, *, hard=False):
    end = len(source) if end is None else end
    boundaries = {"boundary_before": Boundary.HARD, "boundary_after": Boundary.HARD} if hard else {}
    return OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),),
                         Handler.KOREAN, "test", **boundaries)


@pytest.mark.parametrize(("source", "tokens", "expected"), [
    ("없이", (AnalysisToken("없", "VA", 0, 1), AnalysisToken("이", "XSM", 1, 2)), "업씨"),
    ("많이", (AnalysisToken("많", "VA", 0, 1), AnalysisToken("이", "XSM", 1, 2)), "마니"),
    ("밭이야", (AnalysisToken("밭", "NNG", 0, 1), AnalysisToken("이", "VCP", 1, 2),
               AnalysisToken("야", "EF", 2, 3)), "바치야"),
])
def test_supplied_formal_morphemes_license_sound_rules(source, tokens, expected):
    class SuppliedAnalyzer:
        def analyze(self, text):
            assert text == source
            return tokens

    with patch.object(engine, "KiwiAnalyzer", SuppliedAnalyzer):
        result = engine.pronounce((_segment(source),))
    assert result.text == expected


@pytest.mark.parametrize(("source", "cut"), [
    ("햇볕이", 2), ("같이해", 1), ("붙임성", 1), ("어김없이", 3), ("많이를", 1),
])
def test_formal_tail_rules_preserve_explicit_hard_boundaries(source, cut):
    pieces = (_segment(source, 0, cut, hard=True), _segment(source, cut, hard=True))
    expected = "".join(engine.pronounce((piece,)).text for piece in pieces)
    assert engine.pronounce(pieces).text == expected


def test_intrinsic_structure_uses_general_seong_suffix_rule():
    result = engine.pronounce((_segment("붙임성"),))
    assert result.text == "부침썽"
    assert "ko.derivational.seong_tensing" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "tag"), [("다같이", "NNG"), ("아다같이", "MAG")])
def test_exact_adverb_structure_does_not_override_a_different_owner(source, tag):
    class SuppliedAnalyzer:
        def analyze(self, text):
            assert text == source
            return (AnalysisToken(source, tag, 0, len(source)),)

    with patch.object(engine, "KiwiAnalyzer", SuppliedAnalyzer):
        result = engine.pronounce((_segment(source),))
    assert "ko.palatalization" not in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [
    ("실 밥", "실 밥"), ("현실 밥", "현실 밥"), ("실바늘", "실바늘"),
    ("부성", "부성"), ("횡성", "횡성"), ("같은", "가튼"), ("붙은", "부튼"),
])
def test_unrelated_lexical_owners_remain_protected(source, expected):
    assert G2P()(source) == expected
