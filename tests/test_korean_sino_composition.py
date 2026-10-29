"""한자어 기반과 생산적 후행 성분의 음운 합성 및 경계 조건을 검증한다."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from g2p_ko import G2P
import g2p_ko.korean.engine as engine_module
import g2p_ko.korean.morphology as morphology_module
from g2p_ko.korean.lexicon import SINO_ORIGINS
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline


@pytest.mark.parametrize(
    ("source", "expected"),
    [("발전량", "발쩐냥"), ("발전량이", "발쩐냥이"), ("발전량도", "발쩐냥도"),
     ("결정문", "결쩡문"), ("결정문을", "결쩡무늘"), ("「결정문」", "「결쩡문」")],
)
def test_whole_noun_reuses_verified_base_and_attached_component(source, expected) -> None:
    # 발전량은 제20항 해설의 독립된 두 음절 한자어+량 구조에 따른 추론이다.
    # 완성 발음이 사전에 직접 실려 있다는 주장이나 그 발음의 런타임 복사가 아니다.
    # https://www.korean.go.kr/kornorms/regltn/regltnView.do?regltn_code=0002
    # -문(文): https://stdict.korean.go.kr/search/searchView.do?word_no=124752
    assert "발전량" not in SINO_ORIGINS and "결정문" not in SINO_ORIGINS
    result = Pipeline(max_length=1_000).run(source)
    assert G2P()(source) == result.surface_pronunciation == expected
    assert "ko.sino.tensing.26" in {item.rule_id for item in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {item.rule_id for item in result.rewrites}


def test_quantity_component_uses_noun_pos_in_correct_analysis() -> None:
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == "발전량"
            return (AnalysisToken("발전", "NNG", 0, 2), AnalysisToken("량", "NNG", 2, 3))

    source = "발전량"
    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, 3),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((segment,))
    assert result.text == "발쩐냥"
    assert {"ko.sino.tensing.26", "ko.liquid.suffix.20"} <= {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [("발전량", "발쩐냥"), ("결정문", "결쩡문")])
def test_valid_whole_noun_annotation_recovers_typed_component(source, expected) -> None:
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            return (AnalysisToken(source, "NNG", 0, len(source)),)

    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("올바른 통짜 명사 분석은 Kiwi를 호출하지 않는다."),
    ):
        result = engine_module.pronounce((segment,))
    assert result.text == expected
    assert "ko.sino.tensing.26" in {item.rule_id for item in result.rewrites}
    assert not any(item.rule_id == "ko.lexical.verified" for item in result.rewrites)


def test_one_syllable_base_does_not_trigger_the_two_syllable_boundary(monkeypatch) -> None:
    # 비실제 합성 입력으로 길이 조건만 통제한다. 사전 발음 정확도 지표에 넣지 않는다.
    class CorrectAnalyzer:
        def analyze(self, text):
            return (AnalysisToken("산", "NNG", 0, 1), AnalysisToken("량", "NNG", 1, 2))

    monkeypatch.setattr(morphology_module, "SINO_KOREAN_LEXEMES", morphology_module.SINO_KOREAN_LEXEMES | {"산"})
    source = "산량"
    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, 2),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((segment,))
    assert result.text == "살량"
    assert "ko.liquid.suffix.20" not in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("source", "expected"), [("등용문", "등용문"), ("갈비", "갈비"), ("신라", "실라"), ("난로", "날로")])
def test_lexical_homographs_and_simple_sino_words_are_not_resegmented(source, expected) -> None:
    assert G2P()(source) == expected


@pytest.mark.parametrize("source", ["발전량", "결정문"])
def test_derived_sino_forms_preserve_hard_boundaries(source) -> None:
    for split in range(1, len(source)):
        segments = tuple(
            OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),), Handler.KOREAN, "test",
                          boundary_before=Boundary.HARD, boundary_after=Boundary.HARD)
            for start, end in ((0, split), (split, len(source)))
        )
        assert engine_module.pronounce(segments).text == "".join(engine_module.pronounce((part,)).text for part in segments)
