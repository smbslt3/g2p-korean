"""완성 발음 치환 없이 적용되는 규칙과 과잉 적용 방지를 함께 검증한다."""

from __future__ import annotations

import pytest

from g2p_ko import G2P
import g2p_ko.korean.engine as engine_module
import g2p_ko.korean.morphology as morphology_module
from g2p_ko.korean.official import LEXICAL_PRONUNCIATIONS
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline


@pytest.mark.parametrize(
    ("source", "expected", "rule_id"),
    [
        ("댓잎", "댄닙", "ko.saisiot.30"),
        ("뒷이야기", "뒨니야기", "ko.saisiot.30"),
        ("뒷얘기", "뒨냬기", "ko.saisiot.30"),
        ("공업용", "공엄뇽", "ko.n_insertion.compound"),
        ("개미핥기", "개미할끼", "ko.cluster.tensing"),
        ("발달", "발딸", "ko.sino.tensing.26"),
        ("물고기", "물꼬기", "ko.lexical.tensing"),
        ("줄넘기", "줄럼끼", "ko.stem.tensing.24"),
        ("문법", "문뻡", "ko.lexical.tensing"),
        ("유들유들", "유들류들", "ko.n_insertion.reduplication"),
        ("발등", "발뜽", "ko.lexical.tensing"),
        ("낱알", "나달", "ko.liaison.lexical"),
        ("팥알", "파달", "ko.liaison.lexical"),
        ("팔심", "팔씸", "ko.lexical.tensing"),
        ("싫증", "실쯩", "ko.lexical.tensing"),
    ],
)
@pytest.mark.parametrize("frame", ["{}", "{}도", "「{}」"])
def test_reproduced_defects_use_rules_in_context(
    source: str, expected: str, rule_id: str, frame: str,
) -> None:
    text, pronunciation = frame.format(source), frame.format(expected)
    if frame == "{}도" and source in {"댓잎", "문법"}:
        pronunciation = {"댓잎": "댄닙또", "문법": "문뻡또"}[source]
    result = Pipeline(max_length=1_000).run(text)

    assert result.surface_pronunciation == pronunciation
    assert G2P()(text) == G2P().convert(text).surface_pronunciation == pronunciation
    assert result.complete and not result.diagnostics
    assert rule_id in {item.rule_id for item in result.rewrites}
    assert source not in LEXICAL_PRONUNCIATIONS
    assert not any(item.rule_id == "ko.official.enumerated" for item in result.rewrites)
    assert len(pronunciation) == len(text)
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert text[span.start:span.end] == span.surface


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # 제29항의 -용과 제18·20항을 합성한 결과다. 완성 발음 표에는 없다.
        ("산업용", "사넘뇽"), ("작업용", "자검뇽"), ("교육용", "교융뇽"),
        ("실험용", "실험뇽"), ("선물용", "선물룡"),
        ("결정", "결쩡"), ("활동", "활똥"), ("철도", "철또"),
        ("일정", "일쩡"), ("달성", "달썽"), ("설정", "설쩡"), ("실수", "실쑤"),
        ("발전기", "발쩐기"), ("「발달이」", "「발따리」"),
        ("갈수록", "갈쑤록"), ("할밖에", "할빠께"),
        ("알심", "알씸"),
    ],
)
def test_productive_contexts_outside_the_old_pronunciation_table(source: str, expected: str) -> None:
    assert G2P()(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("옷이", "오시"), ("갓이", "가시"), ("논이랑 밭이랑 다 팔자.", "노니랑 바치랑 다 팔자."),
        ("안기다", "안기다"), ("감기다", "감기다"),
        ("갈비", "갈비"), ("불고기", "불고기"), ("여덟과", "여덜과"),
        ("여덟도", "여덜도"), ("허허실실", "허허실실"),
        ("불일치", "부릴치"), ("몰인정", "모린정"),
        ("W", "더브류"),
    ],
)
def test_similar_spelling_does_not_trigger_unconfirmed_rules(source: str, expected: str) -> None:
    assert G2P()(source) == expected


class FixedAnalyzer:
    """단어 목록과 무관하게 형태소 조건을 분리해서 검사한다."""

    def __init__(self, tokens: tuple[AnalysisToken, ...]) -> None:
        self.tokens = tokens
        self.calls = 0

    def analyze(self, text: str) -> tuple[AnalysisToken, ...]:
        self.calls += 1
        assert "".join(token.form for token in self.tokens) == text
        return self.tokens


def _segment(text: str) -> OutputSegment:
    return OutputSegment(text, (SourceSpan.from_source(text, 0, len(text)),), Handler.KOREAN, "test")


@pytest.mark.parametrize(("tag", "expected"), [("XSN", "도담뇽"), ("NNG", "도다묭")])
def test_unlisted_stem_requires_productive_suffix_metadata(
    monkeypatch: pytest.MonkeyPatch, tag: str, expected: str,
) -> None:
    # 합성 입력의 정답률 주장이 아니라, 접미사 정보만 바뀌는 통제 실험이다.
    analyzer = FixedAnalyzer((AnalysisToken("도담", "NNG", 0, 2), AnalysisToken("용", tag, 2, 3)))
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)

    result = engine_module.pronounce((_segment("도담용"),))

    assert result.text == expected
    assert analyzer.calls == 1


@pytest.mark.parametrize(("tag", "expected"), [("XSN", "안끼"), ("XSV", "안기")])
def test_nominalizer_and_passive_suffix_are_distinguished(
    monkeypatch: pytest.MonkeyPatch, tag: str, expected: str,
) -> None:
    analyzer = FixedAnalyzer((AnalysisToken("안", "VV", 0, 1), AnalysisToken("기", tag, 1, 2)))
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)

    assert engine_module.pronounce((_segment("안기"),)).text == expected


def test_new_sino_lexeme_needs_only_origin_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = FixedAnalyzer((AnalysisToken("결석", "NNG", 0, 2),))
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)
    monkeypatch.setattr(morphology_module, "SINO_KOREAN_LEXEMES", morphology_module.SINO_KOREAN_LEXEMES | {"결석"})

    result = engine_module.pronounce((_segment("결석"),))

    assert result.text == "결썩"
    assert "결석" not in LEXICAL_PRONUNCIATIONS
    assert "ko.sino.tensing.26" in {item.rule_id for item in result.rewrites}


@pytest.mark.parametrize(
    ("source", "tokens", "expected"),
    [
        ("뒷이야기", (AnalysisToken("뒷", "NNG", 0, 1), AnalysisToken("이야기", "NNG", 1, 4)), "뒨니야기"),
        ("일시", (AnalysisToken("일", "NR", 0, 1), AnalysisToken("시", "NNB", 1, 2)), "일씨"),
    ],
)
def test_lexical_properties_survive_analyzer_segmentation_variants(
    monkeypatch: pytest.MonkeyPatch, source: str, tokens: tuple[AnalysisToken, ...], expected: str,
) -> None:
    analyzer = FixedAnalyzer(tokens)
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)

    assert engine_module.pronounce((_segment(source),)).text == expected
    assert analyzer.calls == 1


def test_letter_name_does_not_request_compound_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzer = FixedAnalyzer(())
    monkeypatch.setattr(engine_module, "KiwiAnalyzer", lambda: analyzer)
    segment = OutputSegment("더블유", (SourceSpan.from_source("W", 0, 1),), Handler.ENGLISH, "test", "english.letter_names.v1")

    assert engine_module.pronounce((segment,)).text == "더브류"
    assert analyzer.calls == 0


@pytest.mark.parametrize("source", ["댓잎", "공업용", "개미핥기", "발달", "물고기", "줄넘기", "유들유들"])
def test_new_rules_respect_every_hard_split(source: str) -> None:
    for split in range(1, len(source)):
        segments = tuple(
            OutputSegment(source[start:end], (SourceSpan.from_source(source, start, end),), Handler.KOREAN, "test",
                          boundary_before=Boundary.HARD, boundary_after=Boundary.HARD)
            for start, end in ((0, split), (split, len(source)))
        )
        isolated = "".join(engine_module.pronounce((segment,)).text for segment in segments)
        assert engine_module.pronounce(segments).text == isolated
