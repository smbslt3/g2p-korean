"""독립 작성 후보가 기존 발음 동작과 문법 경계를 보존하는지 검사한다."""

from unittest.mock import patch
from types import SimpleNamespace

import pytest

from g2p_ko import G2P
from g2p_ko.korean.boundary_policy import licenses_n_insertion
import g2p_ko.korean.engine as engine_module
from g2p_ko.model import AnalysisToken, Handler, OutputSegment, SourceSpan


@pytest.mark.parametrize(("source", "expected"), [
    ("결석", "결썩"), ("골절", "골쩔"), ("질서", "질써"), ("질주", "질쭈"),
    ("윗입술", "윈닙쑬"), ("첫인상", "처딘상"), ("첫인사", "처딘사"),
    ("그는 질주했다.", "그는 질쭈핻따."),
    ("질서를 지킨다.", "질써를 지킨다."),
    ("골절이 낫다.", "골쩌리 낟따."),
    ("결실을 얻었다.", "결씨르 러덛따."),
    ("결심을 밝혔다.", "결씨믈 발켣따."),
    ("카드 결제가 끝났다.", "카드 결쩨가 끈낟따."),
])
def test_previous_defects_and_new_rule_compositions(source, expected) -> None:
    # 앞의 일곱 반례와 평가자가 구성한 문장을 검사하며 외부 사전 레코드를 읽지 않는다.
    result = G2P().convert(source)
    assert G2P()(source) == result.surface_pronunciation == expected
    assert result.complete


@pytest.mark.parametrize(("source", "base", "suffix", "expected"), [
    ("늑막염", "늑막", "염", "능망념"),
    ("백분율", "백분", "율", "백뿐뉼"),
])
def test_declared_compound_preserves_correct_noun_suffix_analysis(source, base, suffix, expected) -> None:
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            return (AnalysisToken(base, "NNG", 0, len(base)),
                    AnalysisToken(suffix, "XSN", len(base), len(source)))

    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer):
        result = engine_module.pronounce((segment,))
    assert result.text == expected
    assert "ko.n_insertion.compound" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(("left_tag", "right_tag", "declared", "form", "expected"), [
    ("NNG", "NNG", False, "이불", False),
    ("NNG", "XSN", True, "염", True),
    ("NNG", "XSN", False, "염", False),
    ("NNG", "XSN", False, "용", True),
    ("NNG", "NNG", False, "용", False),
    ("XPN", "VV+EP", False, "익었", True),
    ("XPN", "EC", False, "어", False),
    ("XPN", "VV+JKS", True, "익", False),
    ("NNG", "NNG+ETN", True, "음", False),
    ("NNG+JC", "NNG", True, "이불", False),
    ("ETM", "NNG", False, "일", True),
])
def test_grammatical_boundary_contrasts(left_tag, right_tag, declared, form, expected) -> None:
    assert licenses_n_insertion(left_form="앞", left_tag=left_tag, right_form=form,
                                right_tag=right_tag, declared_boundary=declared, saisiot=False) is expected


@pytest.mark.parametrize(("source", "left", "left_tag", "right", "expected"), [
    ("부엌일", "부엌", "NNG", "일", "부엉닐"),
    ("알약", "알", "NNG", "약", "알략"),
    ("늦여름", "늦", "XPN", "여름", "는녀름"),
    ("밤일", "밤", "NNG", "일", "밤닐"),
    ("앞일", "앞", "NNG", "일", "암닐"),
    ("볼일", "볼", "VV+ETM", "일", "볼릴"),
    ("청산유수", "청산", "NNG", "유수", "청산뉴수"),
])
@pytest.mark.parametrize("whole_noun", [True, False])
def test_compound_rule_with_valid_whole_or_split_analysis(source, left, left_tag, right, expected, whole_noun) -> None:
    class CorrectAnalyzer:
        def analyze(self, text):
            assert text == source
            if whole_noun:
                return (AnalysisToken(source, "NNG", 0, len(source)),)
            return (AnalysisToken(left, left_tag, 0, len(left)),
                    AnalysisToken(right, "NNG", len(left), len(source)))

    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN, "test")
    with patch.object(engine_module, "KiwiAnalyzer", CorrectAnalyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("올바른 분석 통제 경로는 Kiwi를 호출하지 않는다."),
    ):
        result = engine_module.pronounce((segment,))
    assert result.text == expected
    assert "ko.n_insertion.compound" in {item.rule_id for item in result.rewrites}


def test_fused_prenominal_surface_keeps_real_verb_and_ending_tags() -> None:
    class CorrectKiwi:
        def tokenize(self, text, **kwargs):
            assert text == "볼일"
            # 겹친 원시 좌표는 Kiwi 어댑터가 비중첩 표면 범위로 병합한다.
            return (SimpleNamespace(form="보", tag="VV", start=0, len=1),
                    SimpleNamespace(form="ㄹ", tag="ETM", start=0, len=1),
                    SimpleNamespace(form="일", tag="NNG", start=1, len=1))

    source = "볼일"
    segment = OutputSegment(source, (SourceSpan.from_source(source, 0, len(source)),), Handler.KOREAN, "test")
    with patch("g2p_ko.analyzer._get_kiwi", return_value=CorrectKiwi()):
        result = engine_module.pronounce((segment,))
    assert result.text == "볼릴"
