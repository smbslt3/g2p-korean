"""새로 확인한 합성 경계의 발음과 조사·보호 경계에서의 재사용을 검증한다."""

from unittest.mock import patch

import pytest

from g2p_ko import G2P
import g2p_ko.korean.engine as engine_module
from g2p_ko.korean.official import LEXICAL_PRONUNCIATIONS
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline


@pytest.mark.parametrize(("source", "expected"), [
    ("공공요금", "공공뇨금"), ("공공요금이", "공공뇨그미"),
    ("나랏일", "나란닐"), ("나랏일을", "나란니를"),
    ("밤길", "밤낄"), ("밤길을", "밤끼를"),
    ("밤거리", "밤꺼리"), ("밤거리가", "밤꺼리가"),
    ("공것", "공껃"), ("공것이", "공꺼시"),
    ("물가", "물까"), ("물가가", "물까가"),
    ("끝인사", "끄딘사"), ("끝인사를", "끄딘사를"),
])
def test_verified_boundaries_compose_with_particles(source, expected) -> None:
    # 사전의 표제어 발음과 조사 앞 연음 규칙에서 기대값을 독립적으로 정한다.
    # https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=19858
    # https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=17913
    # https://www.korean.go.kr/nkview/nklife/1993_1/3_5.html
    # https://krdict.korean.go.kr/kor/dicSearch/SearchView?ParaWordNo=38422
    result = Pipeline(max_length=1_000).run(source)
    assert G2P()(source) == result.surface_pronunciation == expected
    assert not any(item.rule_id == "ko.lexical.verified" for item in result.rewrites)


@pytest.mark.parametrize(("source", "expected"), [
    ("공공요금", "공공뇨금"), ("나랏일", "나란닐"),
    ("밤길", "밤낄"), ("밤거리", "밤꺼리"), ("공것", "공껃"),
    ("물가", "물까"),
    ("끝인사", "끄딘사"),
])
def test_valid_whole_noun_analysis_needs_no_kiwi_workaround(source, expected) -> None:
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            return (AnalysisToken(source, "NNG", 0, len(source)),)

    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("올바른 분석 대역은 Kiwi를 호출하지 않는다."),
    ):
        result = engine_module.pronounce((segment,))
    assert result.text == expected
    assert "끝인사" not in LEXICAL_PRONUNCIATIONS
    assert not any(item.rule_id == "ko.lexical.verified" for item in result.rewrites)


@pytest.mark.parametrize("source", ["공공요금", "나랏일", "밤길", "밤거리", "공것", "물가", "끝인사"])
def test_lexical_metadata_cannot_cross_a_hard_boundary(source) -> None:
    for split in range(1, len(source)):
        segments = tuple(
            OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),), Handler.KOREAN, "test",
                          boundary_before=Boundary.HARD, boundary_after=Boundary.HARD)
            for start, end in ((0, split), (split, len(source)))
        )
        assert engine_module.pronounce(segments).text == "".join(engine_module.pronounce((part,)).text for part in segments)
