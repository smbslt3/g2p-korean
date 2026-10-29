"""동형어 의미 선택의 구문 관계와 실제 발음 적용을 따로 검증한다."""

from dataclasses import replace

import pytest

from g2p_ko import G2P
import g2p_ko.analyzer as analyzer_module
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.semantic_policy import SemanticToken, select_senses
from tests.test_korean_trace_modes import _segments
from g2p_ko.korean import engine as korean_engine
from g2p_ko.model import Boundary, Handler


def _tokens(text):
    return tuple(
        SemanticToken(t.form, t.tag, t.normalized_start, t.normalized_end, t.morphemes)
        for t in KiwiAnalyzer().analyze_components(text)
    )


@pytest.mark.parametrize(("text", "expected"), [
    ("해녀가 하는 물질의 성분을 조사했다.", (None,)),
    ("채집한 잠자리를 폈다.", (None,)),
    ("잠자리의 날개를 폈다.", ("jamjari.insect",)),
    ("잠자리를 잡아 날개를 폈다.", (None,)),
    ("잠자리를 본 뒤 이불을 폈다.", (None,)),
    ("잠자리에게 이불을 폈다.", (None,)),
    ("잠자리를 폈다고 적었다.", ("jamjari.bedding",)),
    ("물질의 원자를 분석했다.", ("muljil.substance",)),
    ("물질을 연구했다.", (None,)),
    ("해녀가 물질의 성분을 연구했다.", ("muljil.substance",)),
    ("강가에서 낚시했다.", ("gangga.riverbank",)),
    ("잠자리를 펴고 잠자리가 날았다.", ("jamjari.bedding", "jamjari.insect")),
    ("잠자리를 잡는 사람이 잠자리를 폈다.", (None, "jamjari.bedding")),
    ("잠자리를, 폈다.", (None,)),
    ("잠자리를 “폈다”.", (None,)),
])
def test_actual_lemma_relations_choose_or_abstain_per_occurrence(text, expected):
    # 기존 기본 발음이 우연히 맞아도 의미 선택 성공으로 집계하지 않는다.
    choices = select_senses(text, _tokens(text))
    assert tuple(choice.sense_id for choice in choices) == expected
    for choice in choices:
        assert text[choice.start:choice.end] == choice.spelling
        assert all((e.target_start, e.target_end) == (choice.start, choice.end) for e in choice.evidence)


@pytest.mark.parametrize(("text", "focus", "expected"), [
    ("잠자리를 폈다.", "잠자리", "잠짜리"),
    ("강가에서 낚시했다.", "강가", "강까"),
    ("물질의 원자를 분석했다.", "물질", "물찌"),
])
def test_selected_features_reach_both_public_phonology_paths(text, focus, expected):
    converter = G2P()
    detailed = converter.convert(text)
    assert converter(text) == detailed.surface_pronunciation
    start = text.index(focus)
    assert detailed.surface_pronunciation[start:start + len(focus)] == expected
    assert detailed.complete


def test_semantic_hard_cut_blocks_evidence_without_changing_tokens():
    text = "잠자리를 폈다."
    tokens = _tokens(text)
    assert select_senses(text, tokens)[0].sense_id == "jamjari.bedding"
    assert select_senses(text, tokens, frozenset({5}))[0].sense_id is None


def test_offset_translation_preserves_relation_and_evidence():
    text = "물질의 원자를 분석했다."
    tokens = _tokens(text)
    expected = select_senses(text, tokens)[0]
    offset = 11
    moved = tuple(replace(t, start=t.start + offset, end=t.end + offset) for t in tokens)
    actual = select_senses(" " * offset + text, moved)[0]
    assert actual.sense_id == expected.sense_id
    assert (actual.start, actual.end) == (expected.start + offset, expected.end + offset)
    assert actual.evidence == tuple(replace(e, target_start=e.target_start + offset,
        target_end=e.target_end + offset, anchor_start=e.anchor_start + offset,
        anchor_end=e.anchor_end + offset) for e in expected.evidence)


def test_missing_canonical_contraction_does_not_fabricate_a_lemma():
    text = "잠자리를 폈다."
    tokens = _tokens(text)
    assert select_senses(text, tokens)[0].sense_id == "jamjari.bedding"
    stripped = tuple(replace(t, morphemes=()) for t in tokens)
    assert select_senses(text, stripped)[0].sense_id is None


def test_semantic_selection_reuses_the_existing_kiwi_call(monkeypatch):
    real = analyzer_module._get_kiwi()
    calls = []

    class CountingKiwi:
        def tokenize(self, text, **kwargs):
            calls.append(text)
            return real.tokenize(text, **kwargs)

    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", CountingKiwi())
    source = "잠자리를 폈다."
    detailed, _ = _segments(((source, Handler.KOREAN, Boundary.WORD, Boundary.WORD, None),))
    result = korean_engine.pronounce(detailed)
    assert result.text.startswith("잠짜리")
    assert calls == [source]


def test_hard_island_keeps_shifted_lemmas_and_scope_in_both_paths():
    detailed, plain = _segments((
        ("별도. ", Handler.KOREAN, Boundary.HARD, Boundary.HARD, None),
        ("잠자리를 폈다.", Handler.KOREAN, Boundary.HARD, Boundary.HARD, None),
    ))
    expected = "".join(korean_engine.pronounce((part,)).text for part in detailed)
    assert "잠짜리" in expected
    assert korean_engine.pronounce(detailed).text == korean_engine.pronounce_text(plain) == expected
