"""지역 모음 변이의 실제 렌더링과 보수적 근거 처리를 검증한다."""

import json
import unicodedata
from dataclasses import replace
from unittest.mock import patch

import pytest
from g2p_ko import G2P
from g2p_ko.vowel_variants import build_vowel_variants


def test_lexical_particle_and_liaison_origins():
    g2p = G2P()
    result = g2p.convert_with_variants("의사, 협의, 나의 계례예 희망")
    roles = [slot.role for slot in result.slots]
    assert "lexical_noninitial" in roles
    assert "JKG" in roles
    assert "original_ye" in roles
    lexical = next(slot for slot in result.slots if slot.role == "lexical_noninitial")
    assert lexical.original == "의"
    assert lexical.base == "븨"
    assert lexical.alternatives[0].text == "비"
    particle = next(slot for slot in result.slots if slot.role == "JKG")
    assert {particle.base, *(a.text for a in particle.alternatives)} == {"의", "에"}
    assert all(a.vowel != "ㅣ" for a in particle.alternatives)
    assert any(x.reason == "verified_lexical_initial_ui" for x in result.decisions)
    assert any(x.reason == "original_consonant_ui_is_mandatory" for x in result.decisions)
    assert sum(x.reason == "original_ye_rye_excluded" for x in result.decisions) == 2
    rendered = result.render({slot.slot_id: 0 for slot in result.slots})
    assert "혀비" in rendered and "게례예" in rendered
    assert json.loads(json.dumps(result.to_dict(), ensure_ascii=False))["scope"] == "standard_rule5_local_vowel_variants_only"


def test_raw_nfd_english_and_punctuation_provenance():
    source = "AI AI, " + unicodedata.normalize("NFD", "협의") + "! 계"
    result = G2P().convert_with_variants(source)
    slot = next(x for x in result.slots if x.original == "의")
    assert slot.source_span.surface == unicodedata.normalize("NFD", "의")
    assert source[slot.source_span.start:slot.source_span.end] == slot.source_span.surface
    assert result.aligned.result.surface_pronunciation[slot.output_start:slot.output_end] == "븨"
    assert slot.output_start != slot.source_span.start
    assert result.render({slot.slot_id: 0}).startswith("에이아이 에이아이, 혀비!")
    assert result.aligned.alignment.source == source


def test_mandatory_reductions_never_reverse():
    result = G2P().convert_with_variants("져 쪄 쳐 희")
    assert not result.slots
    assert result.render() == result.aligned.result.surface_pronunciation
    assert all(x.state == "mandatory" for x in result.decisions)


def test_render_does_not_convert_or_analyze_again():
    g2p = G2P()
    with patch.object(g2p, "convert_with_alignment", wraps=g2p.convert_with_alignment) as conversion:
        result = g2p.convert_with_variants("협의 계")
        assert conversion.call_count == 1
    with patch.object(g2p, "convert_with_alignment", side_effect=AssertionError("재변환")), patch("g2p_ko.vowel_variants.KiwiAnalyzer.analyze", side_effect=AssertionError("재분석")):
        assert result.render({0: 0}) != result.render()
        assert result.render({0: 0}) == result.render({0: 0})
        result.to_dict()


def test_empty_and_long_inputs_use_linear_slots():
    empty = G2P().convert_with_variants("")
    assert empty.render() == "" and empty.auxiliary_analysis_calls == 0
    long = G2P().convert_with_variants("협의 " * 120)
    assert len(long.slots) == 120
    assert long.render({slot.slot_id: 0 for slot in long.slots}) == "혀비 " * 120
    assert long.auxiliary_analysis_calls == 1
    assert "variants" not in long.to_dict()


@pytest.mark.parametrize("selection", [{-1: 0}, {0: -1}, {0: 9}, {True: 0}, {0: False}, {"0": 0}, [(0, 0)]])
def test_invalid_selections(selection):
    result = G2P().convert_with_variants("협의")
    with pytest.raises(ValueError):
        result.render(selection)


def test_overlap_is_rejected():
    result = G2P().convert_with_variants("협의")
    forged = replace(result, slots=(result.slots[0], replace(result.slots[0], slot_id=1)))
    with pytest.raises(ValueError):
        forged.render({0: 0, 1: 0})


def test_malformed_auxiliary_analysis_is_unknown():
    aligned = G2P().convert_with_alignment("협의")
    with patch("g2p_ko.vowel_variants.KiwiAnalyzer.analyze", return_value=(object(),)):
        result = build_vowel_variants(aligned)
    assert not result.slots
    assert result.coverage_status == "partial_unknown"
    assert result.auxiliary_analysis_status == "unavailable:ValueError"


def test_existing_apis_and_serializations_are_unchanged():
    g2p = G2P()
    for source in ("나의 협의 계", "AI, 계!", unicodedata.normalize("NFD", "협의"), "", "쳐 희"):
        before = g2p.convert(source).to_dict()
        aligned = g2p.convert_with_alignment(source)
        variants = g2p.convert_with_variants(source)
        assert variants.aligned.result.to_dict() == before
        assert variants.aligned.alignment.to_dict() == aligned.alignment.to_dict()
        assert g2p(source) == variants.render()
    with pytest.raises(ValueError):
        g2p.convert_with_variants("계", profile="unknown")
