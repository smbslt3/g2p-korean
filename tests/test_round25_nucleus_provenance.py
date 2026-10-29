"""어휘 목록 대신 성분 변화와 실제 trace 결속으로 모음 핵 전이를 검증한다."""

from dataclasses import replace
from types import SimpleNamespace
import unicodedata
from unittest.mock import patch

import pytest

from g2p_ko import G2P
from g2p_ko.alignment import G2PAlignedResult, build_pronunciation_alignment
from g2p_ko.korean.hangul import compose_syllable, JONGSEONG
from g2p_ko.korean.rules import NucleusTransfer, RuleDefinition, RULES
from g2p_ko.model import Handler, OutputSegment, Rewrite, RewriteStage, SourceSpan
from g2p_ko.unicode import normalize_nfc
from g2p_ko.vowel_length import _nucleus_anchor


def chain(source, steps, *, raw_source=None):
    raw_source = source if raw_source is None else raw_source
    normalized = normalize_nfc(raw_source, max_length=len(raw_source))
    assert normalized.text == source
    span = SourceSpan.from_source(source, 0, len(source))
    segment = OutputSegment(source, (span,), Handler.KOREAN, "합성 핵 전이")
    current = source
    events = []
    for before, after, rule in steps:
        events.append(Rewrite((span,), before, after, Handler.KOREAN, rule, RewriteStage.PHONOLOGY))
        current = after
    pipeline = SimpleNamespace(surface_pronunciation=current, normalized_segments=(segment,),
                               pronunciation_segments=(replace(segment, text=current),), rewrites=tuple(events))
    alignment = build_pronunciation_alignment(raw_source, normalized, pipeline)
    result = replace(G2P().convert(raw_source), surface_pronunciation=current)
    return G2PAlignedResult(result, alignment)


@pytest.mark.parametrize("onset", ("ㅈ", "ㅉ", "ㅊ"))
@pytest.mark.parametrize("vowel,target", (("ㅑ", "ㅏ"), ("ㅒ", "ㅐ"), ("ㅕ", "ㅓ"), ("ㅖ", "ㅔ"), ("ㅛ", "ㅗ"), ("ㅠ", "ㅜ")))
def test_declared_nucleus_survives_every_coda_and_unknown_consonant_rule(onset, vowel, target):
    for coda in JONGSEONG:
        original = compose_syllable(onset, vowel, coda)
        canonical = compose_syllable(onset, target, coda)
        final = compose_syllable("ㄲ", target, "ㅁ")
        for nfd in (False, True):
            raw_source = unicodedata.normalize("NFD", original) if nfd else original
            aligned = chain(original, ((original, canonical, "ko.vowel.palatal_j_canonical"),
                                       (canonical, final, "합성.이름과무관한자음변화")), raw_source=raw_source)
            raw = SourceSpan.from_source(raw_source, 0, len(raw_source))
            assert _nucleus_anchor(aligned, raw, original) == (0, 1)
            entry, = aligned.alignment.entries
            assert entry.rule_id == "합성.이름과무관한자음변화"
            assert entry._nucleus_provenance.owner_rule_id == "ko.vowel.palatal_j_canonical"
            assert "_nucleus_provenance" not in entry.to_dict()


def test_actual_vowel_changes_need_a_matching_declaration_and_replace_owner():
    source, canonical, other = "쥰", "준", "진"
    custom = RuleDefinition("합성.선언모음변화", "합성", "새 핵 대응", nucleus_transfer=NucleusTransfer((("ㅜ", "ㅣ"),), frozenset({"ㅈ"})))
    for declared in (False, True):
        with patch.dict(RULES, {custom.id: custom} if declared else {}):
            aligned = chain(source, ((source, canonical, "ko.vowel.palatal_j_canonical"),
                                     (canonical, other, custom.id), (other, "찐", "합성.자음변화")))
        raw = SourceSpan.from_source(source, 0, 1)
        assert _nucleus_anchor(aligned, raw, source) == ((0, 1) if declared else None)
        if declared:
            assert aligned.alignment.entries[0]._nucleus_provenance.owner_rule_id == custom.id


@pytest.mark.parametrize("steps", (
    (("쥰", "준", "ko.vowel.palatal_j_canonical"), ("준", "진", "합성.미선언"), ("진", "찐", "합성.자음")),
    (("쥰", "진", "합성.미선언"), ("진", "쥰", "합성.복귀")),
    (("쥰", "준", "ko.vowel.palatal_j_canonical"), ("진", "찐", "합성.불일치")),
    (("쥰", "진", "ko.vowel.palatal_j_canonical"),),
))
def test_unproven_changes_and_broken_chains_cannot_inherit_or_recover_ownership(steps):
    aligned = chain("쥰", steps)
    assert _nucleus_anchor(aligned, SourceSpan.from_source("쥰", 0, 1), "쥰") is None


def test_unchanged_initial_nucleus_keeps_identity_owner_after_consonant_change():
    aligned = chain("각", (("각", "깜", "합성.초종성"),))
    assert _nucleus_anchor(aligned, SourceSpan.from_source("각", 0, 1), "각") == (0, 1)
    assert aligned.alignment.entries[0]._nucleus_provenance.owner_rule_id is None


def test_repeated_occurrences_keep_separate_owners_and_final_rule_binding():
    source = "쥰쥰"
    spans = tuple(SourceSpan.from_source(source, i, i + 1) for i in range(2))
    segment = OutputSegment(source, spans, Handler.KOREAN, "합성 반복")
    events = (Rewrite((spans[0],), "쥰", "준", Handler.KOREAN, "ko.vowel.palatal_j_canonical", RewriteStage.PHONOLOGY),
              Rewrite(spans, "준쥰", "쭌쥰", Handler.KOREAN, "합성.첫음절", RewriteStage.PHONOLOGY))
    pipeline = SimpleNamespace(surface_pronunciation="쭌쥰", normalized_segments=(segment,),
                               pronunciation_segments=(replace(segment, text="쭌쥰"),), rewrites=events)
    normalization = normalize_nfc(source, max_length=2)
    alignment = build_pronunciation_alignment(source, normalization, pipeline)
    result = replace(G2P().convert(source), surface_pronunciation="쭌쥰")
    aligned = G2PAlignedResult(result, alignment)
    assert [_nucleus_anchor(aligned, span, "쥰") for span in spans] == [(0, 1), (1, 2)]
    assert [entry._nucleus_provenance.owner_rule_id for entry in alignment.entries] == ["ko.vowel.palatal_j_canonical", None]
    entry = replace(alignment.entries[0], rule_id="합성.위조")
    forged = replace(aligned, alignment=replace(alignment, entries=(entry, alignment.entries[1])))
    assert _nucleus_anchor(forged, spans[0], "쥰") is None
