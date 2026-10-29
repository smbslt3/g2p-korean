"""동결한 어근·꼬리·실현·정렬 계약을 기존 공개 API로 검사한다."""
import dataclasses
import importlib.metadata
import json
from pathlib import Path
import unicodedata
from unittest.mock import patch

import pytest

from g2p_ko import G2P
from g2p_ko.alignment import AlignmentPrecision, PronunciationAlignment
from g2p_ko.model import AnalysisToken
from g2p_ko import vowel_length as length


CASES = json.loads((Path(__file__).parent / "fixtures/round18_length_owned.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def converter():
    return G2P()


def _merged(text, parts):
    parts = tuple(tuple(item) for item in parts)
    return (AnalysisToken(text, "+".join(tag for _, tag in parts), 0, len(text), parts),)


def _evaluate(converter, text, tokens, *, aligned=None):
    aligned = aligned if aligned is not None else converter.convert_with_alignment(text)
    with patch.object(length, "KiwiAnalyzer") as provider:
        provider.return_value.analyze.return_value = tuple(tokens)
        result = length.build_vowel_length(aligned)
        provider.return_value.analyze.assert_called_once_with(unicodedata.normalize("NFC", text))
    return result


POSITIVE_SHAPES = [(case, mode) for case in CASES["positive"] for mode in (("merged",) if case.get("merged_only") else ("merged", "split"))]


@pytest.mark.parametrize("case,mode", POSITIVE_SHAPES, ids=lambda item: item["text"] if isinstance(item, dict) else item)
def test_exact_roots_own_truthful_whole_split_and_merged_analyses(converter, case, mode):
    text, parts = case["text"], tuple(tuple(item) for item in case["parts"])
    tokens = _merged(text, parts) if mode == "merged" else tuple(
        AnalysisToken(text[a:b], part[1], a, b, (part,)) for part, (a, b) in zip(parts, case["spans"])
    )
    result = _evaluate(converter, text, tokens)
    decision, = result.decisions
    assert (decision.value, decision.status, decision.lemma, decision.ending_initial) == (case["value"], "supported", case["lemma"], case["initial"])
    assert (decision.owner_source_span.start, decision.owner_source_span.end) == (0, len(text))
    assert (decision.nucleus_source_span.start, decision.nucleus_source_span.end) == (0, 1)
    assert decision.output_nucleus_syllable_span == (0, 1)
    assert result.auxiliary_analysis_calls == 1


@pytest.mark.parametrize("group,status", (("unsupported", "unsupported"), ("unresolved_realization", "unknown")))
def test_unimplemented_roles_and_unproven_realization_have_distinct_status(converter, group, status):
    for case in CASES[group]:
        decision, = _evaluate(converter, case["text"], _merged(case["text"], case["parts"])).decisions
        assert (decision.value, decision.status) == ("unknown", status), case


def test_explicit_root_extent_is_not_one_character_and_poly_predicates_do_not_shorten(converter, monkeypatch):
    # 임의 표기는 언어 사실 추가가 아니라 일반 소유 알고리즘의 검사 전용 속성이다.
    cases = (
        ("가너어", (("가너", "VV"), ("어", "EF")), "long", "R7_1_POLYSYLLABIC_ROOT_RETAIN", (2, 2)),
        ("가너다아", (("가너다", "VA"), ("어", "EF")), "long", "R7_1_POLYSYLLABIC_ROOT_RETAIN", (3, 3)),
        ("더도", (("더", "NNG"), ("도", "JX")), "short", "R6_NOMINAL_PARTICLE_RETAIN", (1, None)),
    )
    for text, parts, value, rule, (root_end, ending_start) in cases:
        root, tag = parts[0]
        feature = length._RootFeature(root, tag, root if tag == "NNG" else root + "다", "TEST_GENERIC_ROOT", value, tag != "NNG")
        monkeypatch.setitem(length._ROOTS, (root, tag), feature)
        tokens = _merged(text, parts)
        proof = length._prove_root_owner(text, 0, tokens, parts, feature)
        assert proof is not None
        assert (proof.root_start, proof.root_end, proof.first_ending_start) == (0, root_end, ending_start)
        decision, = _evaluate(converter, text, tokens).decisions
        assert (decision.value, decision.status) == (value, "supported")
        assert rule in decision.rule_ids


def test_declarative_rieul_policy_is_reusable_for_a_polysyllabic_test_root(converter, monkeypatch):
    feature = length._RootFeature("가널", "VV", "가널다", "TEST_RIEUL_ROOT", "long", True, True)
    monkeypatch.setitem(length._ROOTS, (feature.root, feature.tag), feature)
    for text, parts, initial in (
        ("가너니", (("가널", "VV"), ("니", "EC")), "consonant"),
        ("가넙니다", (("가널", "VV"), ("ᆸ니다", "EF")), "consonant"),
        ("가널어", (("가널", "VV"), ("어", "EF")), "vowel"),
    ):
        decision, = _evaluate(converter, text, _merged(text, parts)).decisions
        assert (decision.value, decision.status, decision.ending_initial) == ("long", "supported", initial)


def test_coda_ending_must_share_its_actual_source_syllable_with_the_root(converter):
    text = "끕니다만"
    valid = (
        AnalysisToken("끕니다", "VV+EF", 0, 3, (("끌", "VV"), ("ᆸ니다", "EF"))),
        AnalysisToken("만", "JX", 3, 4, (("만", "JX"),)),
    )
    decision, = _evaluate(converter, text, valid).decisions
    assert (decision.value, decision.status) == ("long", "supported")
    invalid = (
        AnalysisToken("끕", "VV", 0, 1, (("끌", "VV"),)),
        AnalysisToken("니다만", "EF+JX", 1, 4, (("ᆸ니다", "EF"), ("만", "JX"))),
    )
    decision, = _evaluate(converter, text, invalid).decisions
    assert (decision.value, decision.status) == ("unknown", "unknown")


@pytest.mark.parametrize("word", ("눈", "밤"))
def test_same_pos_homographs_stay_unknown_without_per_occurrence_sense_evidence(converter, word):
    for particle in ("", "이", "만"):
        text = word + particle
        parts = ((word, "NNG"),) + (((particle, "JKS" if particle == "이" else "JX"),) if particle else ())
        decision, = _evaluate(converter, text, _merged(text, parts)).decisions
        assert (decision.value, decision.status, decision.reason, decision.lexeme_id) == ("unknown", "unknown", "lexical_sense_unresolved", None)


def test_malformed_overlapping_partial_and_false_source_proofs_are_rejected(converter):
    text = "사람은"
    cases = (
        (AnalysisToken("사랑", "NNG", 0, 2, (("사람", "NNG"),)), AnalysisToken("은", "JX", 2, 3, (("은", "JX"),))),
        (AnalysisToken("사람", "NNG", 0, 2, (("사람", "NNG"),)),),
        (AnalysisToken("사", "NNG", 0, 1, (("사람", "NNG"),)), AnalysisToken("은", "JX", 2, 3, (("은", "JX"),))),
        (AnalysisToken("사람", "NNG", 0, 2, (("사람", "NNG"),)), AnalysisToken("람은", "JX", 1, 3, (("은", "JX"),))),
        (AnalysisToken(text, "NNG+JKS", 0, 3, (("사람", "NNG"), ("은", "JX"))),),
        (AnalysisToken(text, "NNG+JX", 0, 3, (("사람", "VV"), ("은", "JX"))),),
        (AnalysisToken("은", "JX", 2, 3, (("은", "JX"),)), AnalysisToken("사람", "NNG", 0, 2, (("사람", "NNG"),))),
        (AnalysisToken("사", "NNG", 0, 1, (("사람", "NNG"),)), AnalysisToken("람은", "JX", 1, 3, (("은", "JX"),))),
    )
    for tokens in cases:
        decision, = _evaluate(converter, text, tokens).decisions
        assert (decision.value, decision.status) == ("unknown", "unknown"), tokens


def test_longer_whole_or_nominal_fragments_do_not_create_an_exact_root(converter):
    for text, parts in (
        ("앞사람", (("앞사람", "NNG"),)),
        ("앞사람", (("앞", "NNG"), ("사람", "NNG"))),
        ("사람집", (("사람", "NNG"), ("집", "NNG"))),
        ("첫눈", (("첫", "MM"), ("눈", "NNG"))),
        ("맛없다", (("맛", "NNG"), ("없", "VA"), ("다", "EF"))),
    ):
        decision, = _evaluate(converter, text, _merged(text, parts)).decisions
        assert (decision.value, decision.status) == ("unknown", "unsupported")


def test_repeated_occurrences_nfd_and_english_prefix_keep_source_and_output_nuclei(converter):
    for text, normalized, tokens, owners, nuclei in (
        ("사람 사람은 마음", "사람 사람은 마음", (
            AnalysisToken("사람", "NNG", 0, 2, (("사람", "NNG"),)),
            AnalysisToken("사람", "NNG", 3, 5, (("사람", "NNG"),)),
            AnalysisToken("은", "JX", 5, 6, (("은", "JX"),)),
            AnalysisToken("마음", "NNG", 7, 9, (("마음", "NNG"),)),
        ), ((0, 2), (3, 6), (7, 9)), ((0, 1), (3, 4), (7, 8))),
        ("사람은", "사람은", (
            AnalysisToken("사람", "NNG", 0, 2, (("사람", "NNG"),)),
            AnalysisToken("은", "JX", 2, 3, (("은", "JX"),)),
        ), ((0, 4),), ((0, 2),)),
        ("ABC 사람은", "ABC 사람은", (
            AnalysisToken("ABC", "SL", 0, 3, (("ABC", "SL"),)),
            AnalysisToken("사람", "NNG", 4, 6, (("사람", "NNG"),)),
            AnalysisToken("은", "JX", 6, 7, (("은", "JX"),)),
        ), ((4, 7),), ((4, 5),)),
    ):
        result = _evaluate(converter, text, tokens)
        assert [d.value for d in result.decisions] == (["long", "long", "short"] if len(owners) == 3 else ["long"])
        assert tuple((d.owner_source_span.start, d.owner_source_span.end) for d in result.decisions) == owners
        assert tuple((d.nucleus_source_span.start, d.nucleus_source_span.end) for d in result.decisions) == nuclei
        assert all(d.output_nucleus_syllable_span is not None for d in result.decisions)
        if text.startswith("ABC"):
            assert result.decisions[0].output_nucleus_syllable_span == (5, 6)
        if text.startswith("ᄉ"):
            assert len(result.decisions[0].nucleus_source_atoms) == 2


def test_coarse_nucleus_never_becomes_supported(converter):
    aligned = converter.convert_with_alignment("사람은")
    entries = tuple(dataclasses.replace(entry, precision=AlignmentPrecision.OPERATION) for entry in aligned.alignment.entries)
    coarse = dataclasses.replace(aligned, alignment=PronunciationAlignment("사람은", aligned.result.surface_pronunciation, entries))
    decision, = _evaluate(converter, "사람은", _merged("사람은", (("사람", "NNG"), ("은", "JX"))), aligned=coarse).decisions
    assert (decision.value, decision.reason) == ("unknown", "nucleus_output_anchor_unresolved")


def test_punctuation_prevents_cross_owner_composition_and_pauses_preserve_lexical_evidence(converter):
    result = converter.convert_with_vowel_length("사람.은")
    first = result.decisions[0]
    assert (first.value, first.owner_source_span.start, first.owner_source_span.end) == ("long", 0, 2)
    assert not any(d.status == "supported" for d in converter.convert_with_vowel_length("신.어").decisions)
    for text, pause in (("사람은", 2), ("신어", 1), ("끌어", 1)):
        base = converter.convert(text, pause_boundaries=(pause,))
        result = converter.convert_with_vowel_length(text, pause_boundaries=(pause,))
        assert result.aligned.result.to_dict() == base.to_dict()
        assert result.decisions[0].status == "supported"


@pytest.mark.parametrize("case", CASES["actual_kiwi"], ids=lambda item: item["text"])
def test_actual_pinned_kiwi_and_default_output_are_preserved(converter, case):
    assert importlib.metadata.version("kiwipiepy") == "0.24.1"
    assert importlib.metadata.version("kiwipiepy_model") == "0.24.0"
    text = case["text"]
    baseline = converter.convert(text)
    result = converter.convert_with_vowel_length(text)
    decision, = result.decisions
    assert decision.value == case["value"]
    assert (decision.status == "supported") == (case["value"] != "unknown")
    if "conditional_target_lemma" in case:
        # 원래 long 사실은 유지하고, 다른 실제 원형에 전파하지 않는 안전 계약이다.
        assert case["original_candidate01_target_value"] == "long"
        assert decision.status == "unsupported"
        assert decision.lemma != case["conditional_target_lemma"]
    if "lemma" in case:
        assert decision.lemma == case["lemma"]
    assert result.aligned.result.to_dict() == baseline.to_dict()
    assert result.auxiliary_analysis_calls == 1
    saved = result.to_dict()
    assert saved["scope"] == "registered_nominal_roots_and_verified_predicate_inflections"
    assert saved["complete_semantics"] == "base_pipeline_only"
    json.dumps(saved, ensure_ascii=False)
