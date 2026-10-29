"""선언 어원과 的 성분의 소유 범위·규칙 합성을 검증한다."""
from unittest.mock import patch
import pytest
from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean import engine
from g2p_ko.korean.morphology import _Annotation, _has_intrinsic_nominal_tail
from g2p_ko.korean.owned_sino import owned_sino_spans
from g2p_ko.korean.lexicon import SINO_ORIGINS
from g2p_ko.model import AnalysisToken as T, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline

CASES = [("물질적", "물찔쩍"), ("물질적으로", "물찔쩌그로"),
         ("물질적인", "물찔쩌긴"), ("실질적", "실찔쩍"),
         ("실질적으로", "실찔쩌그로"), ("절대적", "절때적")]


def segment(text, source=None, start=0, **kwargs):
    source = text if source is None else source
    return OutputSegment(text, (SourceSpan.from_source(source, start, start+len(text)),), Handler.KOREAN, "test", **kwargs)


def supplied(source, tokens):
    class Analyzer:
        calls = 0
        def analyze(self, text):
            self.calls += 1
            assert text == source
            return tokens
    analyzer = Analyzer()
    with patch.object(engine, "KiwiAnalyzer", lambda: analyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("주어진 형태소열만 소비해야 한다."),
    ):
        result = engine.pronounce((segment(source),))
    assert analyzer.calls == 1
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert source[span.start:span.end] == span.surface
    return result


def owned(source, tokens):
    # 전체 바깥 꼬리 허가 대신 실제 내부 한자어 음운 소비자와 같은 범위를 검사한다.
    return tuple(owned_sino_spans(source, _Annotation.from_tokens(tokens, source), nominal_tail_validator=_has_intrinsic_nominal_tail))


@pytest.mark.parametrize("source,expected", CASES)
@pytest.mark.parametrize("whole", [False, True])
def test_supplied_whole_and_split(source, expected, whole):
    tokens = ((T(source[:3], "NNG", 0, 3),) if whole else
              (T(source[:2], "NNG", 0, 2), T("적", "XSN", 2, 3)))
    if source.endswith("으로"):
        tokens += (T("으로", "JKB", 3, 5),)
    elif source.endswith("인"):
        tokens += (T("인", "VCP+ETM", 3, 4, (("이", "VCP"), ("ᆫ", "ETM"))),)
    result = supplied(source, tokens)
    assert result.text == expected
    assert owned(source, tokens) == ((0, 3, 0, 3),)
    assert "ko.sino.tensing.26" in {r.rule_id for r in result.rewrites}
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {r.rule_id for r in result.rewrites}


@pytest.mark.parametrize("source,expected", CASES)
def test_real_latest_provider_consumed_and_public_api(source, expected):
    calls = []
    class Recording(KiwiAnalyzer):
        def analyze_components(self, text):
            tokens = super().analyze_components(text)
            calls.append((text, tokens))
            return tokens
    with patch.object(engine, "KiwiAnalyzer", Recording):
        traced = Pipeline(max_length=1000).run(source)
    assert len(calls) == 1 and calls[0][0] == source
    assert [(t.form,t.tag) for t in calls[0][1]][:2] == [(source[:2],"NNG"),("적","XSN")]
    if source.endswith("인"):
        assert calls[0][1][-1].morphemes == (("이","VCP"),("ᆫ","ETM"))
    assert traced.surface_pronunciation == G2P()(source) == expected


@pytest.mark.parametrize("base,expected", [("결실","결씰쩍"),("일상","일쌍적"),("철도","철또적"),("탈세","탈쎄적")])
@pytest.mark.parametrize("whole", [False, True])
def test_independent_declared_base_composition(base, expected, whole):
    assert base in SINO_ORIGINS
    text = base+"적"
    tokens = (T(text,"NNG",0,3),) if whole else (T(base,"NNG",0,2), T("적","XSN",2,3))
    assert supplied(text,tokens).text == expected
    assert owned(text,tokens) == ((0,3,0,3),)


@pytest.mark.parametrize("tail,tokens", [
    ("도는",(T("도","JX",3,4),T("는","JX",4,5))),
    ("인",(T("인","VCP+ETM",3,4,(("이","VCP"),("ㄴ","ETM"))),)),
    ("이다",(T("이","VCP",3,4),T("다","EF",4,5))),
    ("인도",(T("인","VCP+ETM",3,4,(("이","VCP"),("ᆫ","ETM"))),T("도","JX",4,5))),
])
def test_generic_verified_particle_and_copular_tails(tail,tokens):
    source="물질적"+tail
    response=(T("물질","NNG",0,2),T("적","XSN",2,3))+tokens
    assert owned(source,response) == ((0,3,0,3),)
    result = supplied(source,response)
    assert "ko.sino.tensing.26" in {r.rule_id for r in result.rewrites}
    if tail == "도는":
        assert result.text[:3] == "물찔쩍"


@pytest.mark.parametrize("source,tokens", [
    ("물질적",(T("물질적","NNP",0,3),)),
    ("물질적",(T("물질적","MAG",0,3),)),
    ("물질적",(T("물질","NNP",0,2),T("적","XSN",2,3))),
    ("물질적",(T("물질","NNG",0,2),T("적","NNB",2,3))),
    ("물질적",(T("물질","NNG",0,2),T("적","NNG",2,3))),
    ("물질적",(T("물","NNG",0,1),T("질","NNG",1,2),T("적","XSN",2,3))),
    ("물질적",(T("물질적","NNG",0,3,(("물질적","NNP"),)),)),
    ("물질적",(T("물질","NNG",0,2,(("물질","NNP"),)),T("적","XSN",2,3))),
    ("물질적",(T("물질","NNG",0,2),T("적","XSN",2,3,(("적","NNB"),)))),
    ("물질적인",(T("물질","NNG",0,2),T("적","XSN",2,3),T("인","VCP+ETM",3,4,(("이","VCP"),("다","ETM"))))),
    ("물질적도",(T("물질적","NNG",0,3),T("도","JX",3,4,(("가","JX"),)))),
    ("가물질적",(T("가","NNG",0,1),T("물질적","NNG",1,4))),
    ("물질적님",(T("물질적","NNG",0,3),T("님","XSN",3,4))),
    ("바늘적",(T("바늘","NNG",0,2),T("적","XSN",2,3))),
    ("바늘적",(T("바늘적","NNG",0,3),)),
    ("물질",(T("물질","NNG",0,2),)),
])
def test_unsupported_partial_native_and_fake_ownership(source,tokens):
    assert owned(source,tokens) == ()
    assert "ko.sino.tensing.26" not in {r.rule_id for r in supplied(source,tokens).rewrites}


@pytest.mark.parametrize("split", [1,2])
def test_hard_boundary(split):
    text="물질적"
    segments=(segment(text[:split],text,boundary_after=Boundary.HARD),segment(text[split:],text,split,boundary_before=Boundary.HARD))
    assert engine.pronounce(segments).text == "".join(engine.pronounce((item,)).text for item in segments)


def test_pause_punctuation_and_bare_ambiguity():
    assert "물질" not in SINO_ORIGINS
    assert G2P()("물질") == "물질"
    assert G2P()("물질,적") == "물질,적"
    assert engine.pronounce((segment("물질적"),),pause_boundaries=(1,2)).text == "물질적"
    assert G2P()("실지로") == "실찌로"
