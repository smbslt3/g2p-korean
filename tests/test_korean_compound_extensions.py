"""합성어 형태소가 한 토큰으로 묶이거나 비첨가형일 때 경계를 검증한다."""

from __future__ import annotations

import pytest

import g2p_ko.korean.engine as engine_module
from g2p_ko import G2P
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


class FixedAnalyzer:
    """경계와 품사를 통제해 Kiwi 응답과 G2P 규칙을 분리한다."""

    def __init__(self, tokens: tuple[AnalysisToken, ...]) -> None:
        self.tokens = tokens
        self.calls = 0

    def analyze(self, text: str) -> tuple[AnalysisToken, ...]:
        self.calls += 1
        assert "".join(token.form for token in self.tokens) == text
        return self.tokens


def _segment(text: str) -> OutputSegment:
    return OutputSegment(
        text,
        (SourceSpan.from_source(text, 0, len(text)),),
        Handler.KOREAN,
        "test",
    )


def _run_with_analysis(
    source: str,
    tokens: tuple[AnalysisToken, ...],
    monkeypatch: pytest.MonkeyPatch,
):
    analyzer = FixedAnalyzer(tokens)
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)
    result = engine_module.pronounce((_segment(source),))
    return result, analyzer


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("윗입술", "윈닙쑬"),
        ("아랫입술", "아랜닙쑬"),
        ("뒷이야기", "뒨니야기"),
    ],
)
# 위·아랫입술은 한국어기초사전 발음 표기와 대조한다.
# https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=69594
# https://krdict.korean.go.kr/eng/dicSearch/SearchView?ParaWordNo=24455
def test_whole_nominal_tokens_recover_declared_saisiot_prefixes(
    source: str, expected: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = FixedAnalyzer((AnalysisToken(source, "NNG", 0, len(source)),))
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)

    result = engine_module.pronounce((_segment(source),))

    assert result.text == expected
    assert "ko.saisiot.30" in {rewrite.rule_id for rewrite in result.rewrites}
    assert analyzer.calls == 1
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert source[span.start:span.end] == span.surface


@pytest.mark.parametrize(
    ("source", "tokens", "expected"),
    [
        (
            "윗입술",
            (AnalysisToken("윗", "NNG", 0, 1), AnalysisToken("입술", "NNG", 1, 3)),
            "윈닙쑬",
        ),
        (
            "첫인사",
            (AnalysisToken("첫", "MM", 0, 1), AnalysisToken("인사", "NNG", 1, 3)),
            "처딘사",
        ),
        (
            "첫인상",
            (AnalysisToken("첫인상", "NNG", 0, 3),),
            "처딘상",
        ),
    ],
)
# 첫인사 [처딘사]: 국립국어원 온라인가나다. 첫인상 [처딘상]: 한국어기초사전.
# https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?qna_seq=313693
# https://krdict.korean.go.kr/vie/dicSearch/SearchView?ParaWordNo=77846&nation=vie
def test_confirmed_compound_boundaries_use_rules_not_pronunciation_substitutions(
    source: str, tokens: tuple[AnalysisToken, ...], expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, analyzer = _run_with_analysis(source, tokens, monkeypatch)

    assert result.text == expected
    assert not any(rewrite.rule_id == "ko.lexical.verified" for rewrite in result.rewrites)
    assert analyzer.calls == 1
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert source[span.start:span.end] == span.surface


def test_no_n_insertion_applies_representative_coda_before_liaison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "첫인사도"
    tokens = (
        AnalysisToken("첫", "MM", 0, 1),
        AnalysisToken("인사", "NNG", 1, 3),
        AnalysisToken("도", "JX", 3, 4),
    )

    result, _ = _run_with_analysis(source, tokens, monkeypatch)
    ids = {rewrite.rule_id for rewrite in result.rewrites}

    assert result.text == "처딘사도"
    assert {"ko.liaison.lexical", "ko.liaison.single"} <= ids
    assert "ko.n_insertion.compound" not in ids


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("윗입술", "윈닙쑬"),
        ("아랫입술", "아랜닙쑬"),
        ("첫인사", "처딘사"),
        ("첫인상", "처딘상"),
    ],
)
def test_real_analyzer_compound_integration(source: str, expected: str) -> None:
    # 골드 분석 대역 테스트와 분리해 현재 Kiwi 토큰 경로만 확인한다.
    result = G2P().convert(source)

    assert result.surface_pronunciation == expected
    assert result.complete
    assert result.diagnostics.normalization.diagnostics == ()
    assert result.diagnostics.pronunciation.diagnostics == ()


def test_particle_is_not_treated_as_the_second_compound_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "윗이"
    tokens = (
        AnalysisToken("윗", "NNG", 0, 1),
        AnalysisToken("이", "JKS", 1, 2),
    )

    result, _ = _run_with_analysis(source, tokens, monkeypatch)

    assert result.text == "위시"
    assert "ko.saisiot.30" not in {rewrite.rule_id for rewrite in result.rewrites}


@pytest.mark.parametrize(
    ("source", "expected"),
    [("옷이", "오시"), ("불일치", "부릴치"), ("독약", "도갹")],
)
def test_no_n_exception_corpus_and_ordinary_particle_keep_their_readings(
    source: str, expected: str,
) -> None:
    assert G2P()(source) == expected


@pytest.mark.parametrize("source", ["윗입술", "첫인사", "첫인상"])
def test_hard_boundary_prevents_cross_component_rules(source: str) -> None:
    split = 1
    prefix, suffix = source[:split], source[split:]
    segments = (
        OutputSegment(
            prefix,
            (SourceSpan.from_source(source, 0, split),),
            Handler.KOREAN,
            "test",
            boundary_after=Boundary.HARD,
        ),
        OutputSegment(
            suffix,
            (SourceSpan.from_source(source, split, len(source)),),
            Handler.KOREAN,
            "test",
            boundary_before=Boundary.HARD,
        ),
    )

    joined = engine_module.pronounce(segments).text
    isolated = "".join(engine_module.pronounce((segment,)).text for segment in segments)

    assert joined == isolated
