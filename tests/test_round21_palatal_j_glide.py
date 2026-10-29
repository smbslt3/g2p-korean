"""외부 사례 없이 성분 계약에서 새로 만든 정규 표기 검증이다."""

from dataclasses import replace
import importlib.metadata
from pathlib import Path
import unicodedata
from unittest.mock import patch

import pytest

from g2p_ko import AlignmentPrecision, AlignmentRelation, AlignmentStatus, G2P
import g2p_ko.korean.engine as engine
from g2p_ko.korean._shared import _Unit
from g2p_ko.korean.hangul import CHOSEONG, JONGSEONG, JUNGSEONG, compose_syllable, decompose_syllable
from g2p_ko.merge import _TextSegment
from g2p_ko.model import Boundary, Handler, OutputSegment, RewriteStage, SourceSpan
from g2p_ko.pipeline import Pipeline, _Resolution
from g2p_ko import vowel_length


# 기대값은 런타임 상수를 가져오지 않고 원자 계약을 독립적으로 옮겼다.
ONSET_CASES = ("ㅈ", "ㅉ", "ㅊ")
VOWEL_CASES = (("ㅑ", "ㅏ"), ("ㅒ", "ㅐ"), ("ㅕ", "ㅓ"), ("ㅖ", "ㅔ"), ("ㅛ", "ㅗ"), ("ㅠ", "ㅜ"))
NEW_RULE = "ko.vowel.palatal_j_canonical"
LEGACY_RULE = "ko.vowel.jyeo"


def _unit(text, *, spans=None):
    spans = spans or (SourceSpan.from_source(text, 0, 1),)
    return _Unit(0, Handler.KOREAN, spans, syllable=decompose_syllable(text, spans))


def _segment(text, *, source=None, handler=Handler.KOREAN, rule_id=None, before=Boundary.WORD, after=Boundary.WORD):
    source = text if source is None else source
    return OutputSegment(text, (SourceSpan.from_source(source, 0, len(source)),), handler,
                         "합성 검증", rule_id, before, after)


def _plain(segment):
    return _TextSegment(segment.text, segment.handler, segment.reason, segment.rule_id,
                        segment.boundary_before, segment.boundary_after)


@pytest.fixture(scope="module")
def converter():
    return G2P()


def test_staged_runtime_and_pinned_kiwi_are_used():
    expected = Path(__file__).resolve().parents[1] / "src/g2p_ko/korean/engine.py"
    assert Path(engine.__file__).resolve() == expected
    assert importlib.metadata.version("kiwipiepy") == "0.24.1"
    assert importlib.metadata.version("kiwipiepy_model") == "0.24.0"


@pytest.mark.parametrize("onset", ONSET_CASES)
@pytest.mark.parametrize("vowel,target", VOWEL_CASES)
def test_three_by_six_matrix_preserves_all_twenty_eight_codas_and_spans(onset, vowel, target):
    # 3×6×28의 성분 조합이며 어휘의 실제 발음을 주장하지 않는다.
    for coda in JONGSEONG:
        original = compose_syllable(onset, vowel, coda)
        unit = _unit(original)
        token = unit.syllable
        events = []
        engine._apply_palatal_j_glide([unit], events)
        assert unit.text == compose_syllable(onset, target, coda)
        assert unit.syllable.onset == onset and unit.syllable.coda == coda
        assert unit.syllable.source_spans == token.source_spans == unit.source_spans
        event, = events
        assert (event.before, event.after, event.rule_id) == (original, unit.text, NEW_RULE)
        assert event.source_spans == unit.source_spans
        assert event.stage is RewriteStage.PHONOLOGY and event.handler is Handler.KOREAN
        engine._apply_palatal_j_glide([unit], events)
        engine._apply_jyeo([unit], events)
        assert len(events) == 1


@pytest.mark.parametrize("onset", tuple(value for value in CHOSEONG if value not in ONSET_CASES))
def test_every_nonpalatal_onset_is_excluded(onset):
    for vowel, _ in VOWEL_CASES:
        for coda in JONGSEONG:
            original = compose_syllable(onset, vowel, coda)
            unit, events = _unit(original), []
            engine._apply_palatal_j_glide([unit], events)
            assert unit.text == original and events == []


@pytest.mark.parametrize("onset", ONSET_CASES)
def test_every_unmapped_vowel_is_excluded_including_w_ui_i_and_ae_e(onset):
    mapped = {vowel for vowel, _ in VOWEL_CASES}
    for vowel in JUNGSEONG:
        if vowel in mapped:
            continue
        for coda in JONGSEONG:
            original = compose_syllable(onset, vowel, coda)
            unit, events = _unit(original), []
            engine._apply_palatal_j_glide([unit], events)
            assert unit.text == original and events == []


@pytest.mark.parametrize("onset", ONSET_CASES)
def test_legacy_jyeo_keeps_rule_before_after_and_no_duplicate(onset):
    for coda in JONGSEONG:
        source = compose_syllable(onset, "ㅕ", coda)
        unit, events = _unit(source), []
        engine._apply_jyeo([unit], events)
        event, = events
        assert (event.before, event.after, event.rule_id) == (source, compose_syllable(onset, "ㅓ", coda), LEGACY_RULE)
        engine._apply_palatal_j_glide([unit], events)
        engine._apply_jyeo([unit], events)
        assert events == [event]


@pytest.mark.parametrize("coda,onset", (("ㅈ", "ㅈ"), ("ㅊ", "ㅊ")))
@pytest.mark.parametrize("vowel,target", VOWEL_CASES)
def test_real_liaison_generates_late_onset_before_final_normalization(coda, onset, vowel, target):
    source = compose_syllable("ㅇ", "ㅏ", coda) + compose_syllable("ㅇ", vowel)
    segment = _segment(source)
    # 분석기의 어휘 판단 대신 조건부 음운 성분을 검사한다. 연음 함수는 실제 구현이다.
    with patch.object(engine, "_apply_morphology_rules", return_value=([], frozenset(), frozenset(), None)):
        detailed = engine.pronounce((segment,))
        plain = engine.pronounce_text((_plain(segment),))
    expected = "아" + compose_syllable(onset, target)
    assert detailed.text == plain == expected
    ids = [event.rule_id for event in detailed.rewrites]
    assert ids == ["ko.liaison.single", NEW_RULE]
    final = detailed.rewrites[-1]
    assert final.before == compose_syllable(onset, vowel)
    assert final.after == compose_syllable(onset, target)
    assert final.source_spans == (SourceSpan.from_source(source, 1, 2),)
    rerun = engine.pronounce(detailed.segments)
    assert rerun.text == expected
    assert not {NEW_RULE, LEGACY_RULE} & {event.rule_id for event in rerun.rewrites}


def test_local_tensing_and_normalization_commute():
    source = "악죠"
    segment = _segment(source)
    first = engine._build_units((segment,), trace=True)
    second = engine._build_units((segment,), trace=True)
    engine._apply_palatal_j_glide(first, [])
    engine._apply_tensification(first, (segment,), [], frozenset(), frozenset(), ())
    engine._apply_tensification(second, (segment,), [], frozenset(), frozenset(), ())
    engine._apply_palatal_j_glide(second, [])
    assert "".join(unit.text for unit in first) == "".join(unit.text for unit in second) == "악쪼"


@pytest.mark.parametrize("handler,rule_id,text", (
    (Handler.PROTECTED, None, "쥬쟤쳐"),
    (Handler.ENGLISH, None, "쥬쟤쳐"),
    (Handler.ENGLISH, "합성.미허용", "쥬쟤쳐"),
    (Handler.ENGLISH, "english.letter_names.v1", "JYEO"),
    (Handler.ENGLISH, None, "JYEO"),
))
def test_raw_protected_unconverted_and_unallowed_generated_segments_are_preserved(handler, rule_id, text):
    segment = _segment(text, handler=handler, rule_id=rule_id)
    result = engine.pronounce((segment,))
    assert result.text == engine.pronounce_text((_plain(segment),)) == text
    assert result.rewrites == ()


@pytest.mark.parametrize("rule_id", ("english.letter_names.v1", "english.conventional.v1"))
def test_allowed_english_generated_units_keep_broad_english_provenance(rule_id):
    segment = _segment("쥬쟤", source="ZX", handler=Handler.ENGLISH, rule_id=rule_id,
                       before=Boundary.HARD, after=Boundary.HARD)
    result = engine.pronounce((segment,))
    assert result.text == engine.pronounce_text((_plain(segment),)) == "주재"
    assert result.segments[0].handler is Handler.ENGLISH
    assert result.segments[0].source_spans == segment.source_spans
    assert result.segments[0].rule_id == rule_id
    assert result.segments[0].boundary_before is Boundary.HARD
    assert len(result.rewrites) == 2
    assert all(event.source_spans == segment.source_spans for event in result.rewrites)
    with patch.object(Pipeline, "_resolve_candidate", return_value=_Resolution("쥬쟤", "합성 영어 읽기", rule_id)):
        aligned = G2P().convert_with_alignment("ZX")
    assert aligned.result.surface_pronunciation == "주재"
    assert aligned.alignment.status is AlignmentStatus.COARSE
    assert all(entry.precision is AlignmentPrecision.OPERATION for entry in aligned.alignment.entries)
    assert aligned.alignment.extract_target(0, 1).reason == "partial_operation"
    assert aligned.alignment.extract_target(0, 2).pronunciation == "주재"


@pytest.mark.parametrize("boundary", (Boundary.WORD, Boundary.MORPHEME, Boundary.HARD))
def test_boundaries_do_not_supply_another_syllables_onset_or_vowel(boundary):
    # 자+야에서 오른쪽 ㅇ을 왼쪽 ㅈ으로 대체하지 않는다. 대상인 쥬는 자기 안에서만 바뀐다.
    source = "자야쥬"
    segments = tuple(OutputSegment(char, (SourceSpan.from_source(source, index, index + 1),),
                                   Handler.KOREAN, "합성 경계", boundary_before=boundary, boundary_after=boundary)
                     for index, char in enumerate(source))
    for pauses in ((), (1,), (2,), (1, 2)):
        result = engine.pronounce(segments, pause_boundaries=pauses)
        assert result.text == "자야주"
        assert engine.pronounce_text(tuple(_plain(segment) for segment in segments), pause_boundaries=pauses) == result.text
        event, = result.rewrites
        assert event.source_spans == (SourceSpan.from_source(source, 2, 3),)
        assert event.rule_id == NEW_RULE


@pytest.mark.parametrize("separator", (" ", ",", ".", "\t", "\n", "😀", "ㅈ", "ᄌ"))
def test_spaces_punctuation_other_characters_and_syllable_count_are_preserved(separator):
    segment = _segment("쥬" + separator + "쟤")
    result = engine.pronounce((segment,))
    assert result.text == "주" + separator + "재"
    assert len(result.text) == len(segment.text)


@pytest.mark.parametrize("onset", ONSET_CASES)
@pytest.mark.parametrize("vowel,target", VOWEL_CASES)
@pytest.mark.parametrize("form", ("NFC", "NFD"))
def test_public_trace_alignment_nucleus_and_repeat_are_truthful(converter, onset, vowel, target, form):
    canonical_input = compose_syllable(onset, vowel, "ㄴ")
    source = unicodedata.normalize(form, canonical_input)
    expected = compose_syllable(onset, target, "ㄴ")
    aligned = converter.convert_with_alignment(source)
    assert converter(source) == aligned.result.surface_pronunciation == expected
    assert aligned.result.source == source
    assert aligned.result.normalized_text == canonical_input
    entry, = aligned.alignment.entries
    raw = SourceSpan.from_source(source, 0, len(source))
    assert entry.source_spans == (raw,)
    assert entry.stage is RewriteStage.PHONOLOGY
    assert entry.rule_id == (LEGACY_RULE if vowel == "ㅕ" else NEW_RULE)
    if form == "NFD":
        assert entry.precision is AlignmentPrecision.OPERATION
        assert entry.relation is AlignmentRelation.CONTRACTION
        assert aligned.alignment.status is AlignmentStatus.COARSE
        assert aligned.alignment.extract_target(0, 1).reason == "partial_operation"
    else:
        assert entry.precision is AlignmentPrecision.CODEPOINT
        assert entry.relation is AlignmentRelation.SUBSTITUTION
    assert aligned.alignment.extract_target(0, len(source)).pronunciation == expected
    assert vowel_length._nucleus_anchor(aligned, raw, canonical_input) == (0, 1)
    assert converter(expected) == expected
    rerun = engine.pronounce((_segment(expected),))
    assert not {NEW_RULE, LEGACY_RULE} & {event.rule_id for event in rerun.rewrites}


def test_repeated_units_make_one_event_each_without_duplicates():
    source = "쟤쟤쥰쥰쳐쳐"
    result = engine.pronounce((_segment(source),))
    assert result.text == "재재준준처처"
    assert len(result.rewrites) == 6
    assert [event.rule_id for event in result.rewrites].count(LEGACY_RULE) == 2
    assert [event.rule_id for event in result.rewrites].count(NEW_RULE) == 4
    assert len({(event.source_spans, event.rule_id) for event in result.rewrites}) == 6


@pytest.mark.parametrize("left,right", (("쟈", "쨔"), ("쟈", "챠"), ("쟤", "졔"), ("쟨", "쟤")))
def test_onset_ae_e_and_coda_distinctions_do_not_collapse(left, right):
    units = [_unit(left), _unit(right)]
    engine._apply_palatal_j_glide(units, [])
    assert units[0].text != units[1].text


def test_nucleus_anchor_rejects_unproven_unrelated_and_coarse_changes(converter):
    aligned = converter.convert_with_alignment("쥰")
    raw = SourceSpan.from_source("쥰", 0, 1)
    entry, = aligned.alignment.entries
    no_rule = replace(aligned, alignment=replace(aligned.alignment, entries=(replace(entry, rule_id="합성.미확인"),)))
    assert vowel_length._nucleus_anchor(no_rule, raw, "쥰") is None
    assert vowel_length._nucleus_anchor(aligned, raw, "쥔") is None
    changed = replace(aligned, result=replace(aligned.result, surface_pronunciation="군"),
                      alignment=replace(aligned.alignment, output="군"))
    assert vowel_length._nucleus_anchor(changed, raw, "쥰") is None
    coarse = replace(aligned, alignment=replace(aligned.alignment,
                     entries=(replace(entry, precision=AlignmentPrecision.OPERATION),)))
    assert vowel_length._nucleus_anchor(coarse, raw, "쥰") is None


def test_inserted_unit_keeps_anchor_insertion_rule_and_empty_segment_sources():
    anchor = SourceSpan.from_source("X", 0, 1)
    segment = OutputSegment("쥬", (), Handler.KOREAN, "합성 삽입", insertion_rule="합성.삽입", anchor=anchor)
    result = engine.pronounce((segment,))
    rendered, = result.segments
    assert rendered.text == "주" and rendered.source_spans == ()
    assert rendered.anchor == anchor and rendered.insertion_rule == "합성.삽입"
    event, = result.rewrites
    assert event.source_spans == (anchor,)
