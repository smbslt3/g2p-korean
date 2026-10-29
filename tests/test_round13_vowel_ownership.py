"""통제된 원문·정렬에서 형태 역할과 모음 변이 소유를 확인한다."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from g2p_ko.model import AnalysisToken, G2PResult, G2PDiagnostics, DiagnosticReport
from g2p_ko.alignment import G2PAlignedResult, PronunciationAlignment, AlignmentEntry, AlignmentRelation, AlignmentPrecision
from g2p_ko.unicode import normalize_nfc
from g2p_ko.vowel_variants import build_vowel_variants
from g2p_ko.korean.hangul import decompose_syllable

CASES = json.loads((Path(__file__).parent / "fixtures/round13_vowel_ownership.json").read_text(encoding="utf-8"))["cases"]

def supplied_tokens(case, text):
    parts, mode = case["parts"], case["mode"]
    if mode == "explicit":
        return tuple(AnalysisToken(p[0], p[1], p[2], p[3], ((p[0], p[1]),)) for p in parts)
    if mode == "whole_lexical":
        end = next((i for i, p in enumerate(parts) if p[1].startswith("J")), len(parts))
        parts = [["".join(p[0] for p in parts[:end]), "NNG"]] + parts[end:]
    if mode in {"merged", "tag_mismatch", "missing_composition"}:
        tag = "NNG+JKS" if mode == "tag_mismatch" else "+".join(p[1] for p in parts)
        return (AnalysisToken(text, tag, 0, len(text), () if mode == "missing_composition" else tuple(tuple(p) for p in parts)),)
    result, cursor = [], 0
    for form, tag in parts:
        result.append(AnalysisToken(form, tag, cursor, cursor + len(form), ((form, tag),)))
        cursor += len(form)
    if mode == "overlap":
        result[-1] = AnalysisToken(text[1:], "JKG", 1, len(text))
    return tuple(result)

def controlled_alignment(case):
    source = case["text"]
    normalized = normalize_nfc(source, max_length=len(source))
    entries, output = [], ""
    for index, char in enumerate(normalized.text):
        target = {"A": "에이", "I": "아이"}.get(char, char) if case.get("english_expansion") else char
        target = case.get("base_overrides", {}).get(str(index), target)
        relation = AlignmentRelation.IDENTITY if target == char else AlignmentRelation.EXPANSION if len(target) > 1 else AlignmentRelation.SUBSTITUTION
        entries.append(AlignmentEntry(len(output), len(output) + len(target), (normalized.character_spans[index],), relation, precision=AlignmentPrecision.CODEPOINT))
        output += target
    if case.get("group_first_two"):
        entries[:2] = [AlignmentEntry(0, 2, (normalized.source_span(0, 2),), AlignmentRelation.GROUPED, precision=AlignmentPrecision.OPERATION)]
    result = G2PResult(source, output, output, G2PDiagnostics(DiagnosticReport(source), DiagnosticReport(output)), True)
    return G2PAlignedResult(result, PronunciationAlignment(source, output, tuple(entries))), normalized

@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_owned_local_vowel_contract(case):
    aligned, normalized = controlled_alignment(case)
    with patch("g2p_ko.vowel_variants.KiwiAnalyzer") as provider:
        provider.return_value.analyze.return_value = supplied_tokens(case, normalized.text)
        result = build_vowel_variants(aligned)
        assert provider.return_value.analyze.call_count == result.auxiliary_analysis_calls == 1
    indices = {(span.start, span.end): i for i, span in enumerate(normalized.character_spans)}
    found = {}
    for slot in result.slots:
        index = indices[(slot.source_span.start, slot.source_span.end)]
        owner = next(([start, end] for start in range(len(normalized.text)) for end in range(start + 1, len(normalized.text) + 1) if normalized.source_span(start, end) == slot.owner_span), None)
        found[str(index)] = {"role": slot.role, "owner": owner, "vowels": [decompose_syllable(slot.base, (slot.source_span,)).vowel] + [alternative.vowel for alternative in slot.alternatives]}
        assert aligned.result.source[slot.source_span.start:slot.source_span.end] == slot.source_span.surface
    assert found == case["slots"]
    states = {str(indices[(decision.source_span.start, decision.source_span.end)]): decision.state for decision in result.decisions}
    assert all(states.get(str(index)) == "excluded" for index in case["excluded"])
    assert all(states.get(str(index)) == "unknown" for index in case["unknown"])
    assert result.render() == aligned.result.surface_pronunciation
    with patch("g2p_ko.vowel_variants.KiwiAnalyzer") as provider:
        result.render({slot.slot_id: 0 for slot in result.slots})
        serialized = result.to_dict()
        assert not provider.called
    assert serialized["schema"] == "g2p_local_vowel_variants.v1"
    assert serialized["complete_semantics"] == "base_pipeline_only"
    for selection in ({True: 0}, {0: False}, {-1: 0}, {0: -1}, {0: 9}):
        with pytest.raises(ValueError):
            result.render(selection)


@pytest.mark.parametrize("names", [("도의의_split", "도의의_merged"), ("예의의_split", "예의의_merged")])
def test_default_particle_vowel_uses_certified_owner_in_both_packagings(names):
    from g2p_ko import G2P
    from g2p_ko.analyzer import KiwiAnalyzer

    converter = G2P()
    for name in names:
        case = next(case for case in CASES if case["name"] == name)
        text = case["text"]
        with patch.object(KiwiAnalyzer, "analyze", return_value=supplied_tokens(case, text)), patch(
            "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("통제 검사에서 실제 분석기 호출 금지")
        ):
            aligned = converter.convert_with_alignment(text)
        assert aligned.result.complete
        particle = aligned.alignment.extract_target(len(text) - 1, len(text))
        assert particle.aligned and particle.pronunciation == "에"
        # 같은 철자의 어휘 중성까지 조사 규칙으로 바꾸지 않는다.
        particle_spans = [(span.start, span.end) for entry in aligned.alignment.entries
                          if entry.rule_id == "ko.ui.particle" for span in entry.source_spans]
        assert particle_spans == [(len(text) - 1, len(text))]


@pytest.mark.parametrize("name", ["tag_part_mismatch", "missing_composition", "overlap"])
def test_default_particle_vowel_retains_existing_unproved_packaging_guards(name):
    from g2p_ko import G2P
    from g2p_ko.analyzer import KiwiAnalyzer

    case = next(case for case in CASES if case["name"] == name)
    text = case["text"]
    with patch.object(KiwiAnalyzer, "analyze", return_value=supplied_tokens(case, text)), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("통제 검사에서 실제 분석기 호출 금지")
    ):
        aligned = G2P().convert_with_alignment(text)
    assert all(entry.rule_id != "ko.ui.particle" for entry in aligned.alignment.entries)
