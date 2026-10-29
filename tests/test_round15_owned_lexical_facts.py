"""두 어휘 사실의 소유·경계 회귀 검사 제안이다.

동결 계약의 원래 기대와 실행 결과는 별도 JSON에 그대로 보존한다.
아래 마지막 세 항목은 원래 계약의 잘못된 전체 발음 기대를 고친 별도 회귀다.
"""
from unittest.mock import patch

import pytest

import g2p_ko.korean.engine as engine
from g2p_ko.korean.lexicon import LEXICAL_STRUCTURES, LexicalStructure
from g2p_ko.korean.morphology import _valid_exact_structure_owner
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _run(source, rows, *, pause=(), hard=False):
    class FixedAnalyzer:
        def analyze(self, text):
            if text != source:
                return tuple(AnalysisToken(char, "NNG", index, index + 1) for index, char in enumerate(text))
            return tuple(AnalysisToken(*row) for row in rows)

    cuts = [0, 1, len(source)] if hard else [0, len(source)]
    segments = tuple(OutputSegment(
        source[start:end], (SourceSpan.from_source(source, start, end),), Handler.KOREAN,
        "어휘회귀", boundary_before=Boundary.HARD if start and hard else Boundary.WORD,
    ) for start, end in zip(cuts, cuts[1:]))
    with patch.object(engine, "KiwiAnalyzer", FixedAnalyzer):
        return engine.pronounce(segments, pause_boundaries=pause)


@pytest.mark.parametrize("word,expected", (("글자", "글짜"), ("땅바닥", "땅빠닥")))
@pytest.mark.parametrize("tag", ("NNG", "NNP"))
def test_exact_nominal_owners(word, expected, tag):
    assert _run(word, [(word, tag, 0, len(word))]).text == expected


@pytest.mark.parametrize("word", ("글자", "땅바닥"))
@pytest.mark.parametrize("prefix,suffix", (("표", ""), ("", "판")))
def test_explicit_nominal_component_only_checks_internal_metadata(word, prefix, suffix):
    source = prefix + word + suffix
    start, end = len(prefix), len(prefix) + len(word)
    rows = []
    if prefix:
        rows.append((prefix, "NNG", 0, start))
    rows.append((word, "NNG", start, end))
    if suffix:
        rows.append((suffix, "NNG", end, len(source)))
    result = _run(source, rows)
    # 가상 합성어 전체의 사전 발음은 주장하지 않는다.
    positions = {max(span.end for span in rewrite.source_spans) - 1
                 for rewrite in result.rewrites if rewrite.rule_id == "ko.lexical.tensing"}
    assert positions == {start + 1}


@pytest.mark.parametrize("word", ("글자", "땅바닥"))
def test_unknown_long_whole_has_no_owned_substring(word):
    source = "표" + word + "판"
    result = _run(source, [(source, "NNG", 0, len(source))])
    assert not any(item.rule_id == "ko.lexical.tensing" for item in result.rewrites)


@pytest.mark.parametrize("word", ("글자", "땅바닥"))
@pytest.mark.parametrize("tag", ("VV", "NNG+JX"))
def test_non_nominal_owner_cannot_acquire_lexical_metadata(word, tag):
    result = _run(word, [(word, tag, 0, len(word))])
    assert not any(item.rule_id == "ko.lexical.tensing" for item in result.rewrites)


@pytest.mark.parametrize("word", ("글자", "땅바닥"))
@pytest.mark.parametrize("barrier", ("pause", "hard"))
def test_internal_phonological_barriers(word, barrier):
    result = _run(word, [(word, "NNG", 0, len(word))], pause=(1,) if barrier == "pause" else (), hard=barrier == "hard")
    assert not any(item.rule_id == "ko.lexical.tensing" for item in result.rewrites)


def test_existing_exact_records_keep_composition_disabled():
    for word in ("형성평가", "총괄평가", "수행평가", "진단평가"):
        assert LEXICAL_STRUCTURES[word].allow_owned_composition is False
    structure = LexicalStructure((("밤", "NNG"), ("바", "NNG")), (1,), owner_pos=frozenset({"NNG"}), allow_owned_composition=True)
    assert _valid_exact_structure_owner("앞밤바", 1, 3, structure, (
        AnalysisToken("앞", "NNG", 0, 1), AnalysisToken("밤바", "NNG", 1, 3),
    ), allow_owned_composition=structure.allow_owned_composition)
    assert not _valid_exact_structure_owner("앞밤바", 1, 3, structure, (
        AnalysisToken("앞밤바", "NNG", 0, 3),
    ), allow_owned_composition=structure.allow_owned_composition)


@pytest.mark.parametrize("particle,tag,expected", (
    ("부터", "JX", "땅빠닥뿌터"),
    ("조차", "JX", "땅빠닥쪼차"),
    ("만", "JX", "땅빠당만"),
))
def test_particle_context_preserves_existing_consonant_rules(particle, tag, expected):
    # 원 계약의 세 전체 발음 기대 오류를 명시적으로 구분한 추가 검사다.
    assert _run("땅바닥" + particle, [("땅바닥", "NNG", 0, 3), (particle, tag, 3, 3 + len(particle))]).text == expected
