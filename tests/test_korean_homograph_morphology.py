"""동형어의 어휘 속성을 명사·접사 분석과 결합해 사용하는지 검사한다."""

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


@pytest.mark.parametrize(("particle", "tag", "expected"), [
    ("", "", "물질"),
    ("이", "JKS", "물지리"),
    ("을", "JKO", "물지를"),
    ("과", "JC", "물질과"),
])
def test_native_suffix_structure_does_not_receive_sino_tensing(particle, tag, expected):
    # 고유어 물+질/XSN의 표준 발음과 조사 앞 연음을 검사한다.
    # https://stdict.korean.go.kr/search/searchView.do?word_no=127827
    source = "물질" + particle

    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            base = (AnalysisToken("물", "NNG", 0, 1), AnalysisToken("질", "XSN", 1, 2))
            return base + ((AnalysisToken(particle, tag, 2, len(source)),) if particle else ())

    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((_segment(source),))
    assert result.text == expected
    rules = {item.rule_id for item in result.rewrites}
    assert "ko.sino.tensing.26" not in rules
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & rules


def test_real_diving_context_preserves_native_reading():
    source = "해녀가 물질을 한다."
    result = G2P().convert(source)
    assert G2P()(source) == result.surface_pronunciation == "해녀가 물지를 한다."
    assert result.complete


@pytest.mark.parametrize(("source", "start", "expected_focus"), [
    ("잠수해 해산물을 채취하는 활동인 물질을 어촌 기록에 남겼다.", 18, "물지"),
    ("잠수해 해산물을 따는 물질은 숙련이 필요하다.", 12, "물지"),
    ("바닷속에서 해산물을 따는 물질이 끝나자 배로 돌아왔다.", 14, "물지"),
    ("그는 잠수로 해산물을 채취하는 물질로 생계를 이어 갔다.", 17, "물질"),
    ("해산물을 따는 물질에 익숙해진 잠수부는 바다로 나갔다.", 8, "물지"),
    ("잠수해 해산물을 채취하는 물질도 체력과 기술이 필요하다.", 14, "물질"),
])
def test_native_context_is_not_overridden_by_a_whole_noun_sino_default(source, start, expected_focus):
    # 평가자가 잠수 채집 뜻으로 작성한 문맥이다. 전체 NNG 분석도 그 뜻을 배제하지 않는다.
    # 끝 조사 뒤 단어로 이어지는 연음과 구별하기 위해 물질 두 음절의 좌표만 비교한다.
    assert source[start:start + 2] == "물질"
    result = G2P().convert(source)
    assert G2P()(source) == result.surface_pronunciation
    assert result.surface_pronunciation[start:start + 2] == expected_focus
    assert result.complete


def test_sino_homograph_property_cannot_cross_a_hard_boundary():
    source = "물질"
    parts = (_segment(source, 0, 1, hard=True), _segment(source, 1, 2, hard=True))
    result = engine_module.pronounce(parts)
    assert result.text == "".join(engine_module.pronounce((part,)).text for part in parts)
    assert not any(item.rule_id == "ko.sino.tensing.26" for item in result.rewrites)
