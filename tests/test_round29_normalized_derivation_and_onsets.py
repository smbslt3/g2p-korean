"""제공한 정규화 유래와 원자 초성 속성을 공개 호출까지 검증한다."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from g2p_ko.korean.morphology import _Annotation, _has_licensed_nominal_tail
from g2p_ko.korean.owned_identity import _identity_class
from g2p_ko.korean.owned_lexical import (
    InternalOnsetConstraint, OWNED_INTERNAL_ONSET_ROOTS, OWNED_LEXICAL_ROOTS,
    OWNED_NOMINAL_ORIGIN_ROOTS, owned_root_decisions,
)
from g2p_ko.model import AnalysisToken as T
from test_round28_derived_word_roles import supplied, liaison


def rows_for(text, terms):
    """명시한 표면 성분을 원문 순서에 정렬한다."""
    rows, cursor = [], 0
    for form, tag, *origin in terms:
        start = text.index(form, cursor)
        cursor = start + len(form)
        rows.append((form, tag, start, cursor, *origin))
    return rows


@pytest.mark.parametrize("word,root,surface,tag,origin", [
    ("우아해", "우아", "해", "XSA-R+EF", (("하", "XSA-R"), ("어", "EF"))),
    ("엄숙해", "엄숙", "해", "XSA+EC", (("하", "XSA"), ("어", "EC"))),
    ("아른거려", "아른", "거려", "XSV-R+EC", (("거리", "XSV-R"), ("어", "EC"))),
    ("어렴풋해", "어렴풋", "해", "XSA-R+EF", (("하", "XSA-R"), ("어", "EF"))),
    ("우아함", "우아", "함", "XSA-R+ETN", (("하", "XSA-R"), ("ᆷ", "ETN"))),
])
@pytest.mark.parametrize("whole", [False, True])
def test_source_owned_normalized_fusion_drives_liaison_and_public_applicability(word, root, surface, tag, origin, whole):
    text = "옷 " + word
    terms = [("옷", "NNG")]
    if whole:
        terms.append((word, "XR+"+tag, ((root, "XR"), *origin)))
    else:
        terms.extend(((root, "XR"), (surface, tag, origin)))
    result, calls = supplied(text, rows_for(text, terms))
    execution, = result.boundary_executions
    assert calls == [text]
    assert (execution.applicability, execution.sound_effect) == ("eligible", "changed")
    assert "ko.liaison.lexical" in execution.rule_ids
    assert liaison(result)
    assert result.aligned.result.surface_pronunciation.startswith("오 " + {"우":"두", "엄":"덤", "아":"다", "어":"더"}[word[0]])
    assert result.aligned.alignment.extract_target(2, len(text)).pronunciation == result.aligned.result.surface_pronunciation[2:]
    assert not execution.source_prosody_observed


def test_fused_token_with_particle_keeps_exact_outside_surface_anchors():
    text = "옷 우아해도"
    own = (("우아", "XR"), ("하", "XSA-R"), ("어", "EF"), ("도", "JX"))
    result, _ = supplied(text, [("옷", "NNG", 0, 1), ("우아해도", "XR+XSA-R+EF+JX", 2, 6, own)])
    assert result.boundary_executions[0].applicability == "eligible"
    assert liaison(result)


@pytest.mark.parametrize("token,applicability", [
    (("우아해", "XR+XSA-R+EF", 2, 5), "unknown"),
    (("우아해", "XR+XSA-R+EF", 2, 5, (("다른", "XR"), ("하", "XSA-R"), ("어", "EF"))), "unknown"),
    (("우아해", "XR+XSA-X+EF", 2, 5, (("우아", "XR"), ("하", "XSA-X"), ("어", "EF"))), "unknown"),
    (("우아해", "XR+XSA-R+EF", 2, 5, (("우아", "XR"), ("하", "XSA-R"), ("어", "EC"))), "unknown"),
    (("우아해", "XR+XSM+EF", 2, 5, (("우아", "XR"), ("히", "XSM"), ("어", "EF"))), "ineligible"),
])
def test_missing_origin_unknown_tags_and_unowned_prefix_do_not_license_fusion(token, applicability):
    result, _ = supplied("옷 우아해", [("옷", "NNG", 0, 1), token])
    # 알려진 부사+어미 유형 충돌만 제외하고, 결손·신원 충돌은 보류한다.
    assert result.boundary_executions[0].applicability == applicability
    assert not liaison(result)


def test_fused_token_cannot_borrow_an_unowned_trailing_particle():
    text = "옷 우아해도"
    own = (("우아", "XR"), ("하", "XSA-R"), ("어", "EF"), ("만", "JX"))
    result, _ = supplied(text, [("옷", "NNG", 0, 1), ("우아해도", "XR+XSA-R+EF+JX", 2, 6, own)])
    assert result.boundary_executions[0].applicability == "unknown"
    assert not liaison(result)


@pytest.mark.parametrize("rows", [
    [("옷", "NNG", 0, 1), ("우아", "XR", 2, 4), ("아해", "XSA-R+EF", 3, 5, (("하", "XSA-R"), ("어", "EF")))],
    [("옷", "NNG", 0, 1), ("우아", "XR", 2, 4), ("해", "XSA-R+EF", 4, 6, (("하", "XSA-R"), ("어", "EF")))],
    [("옷", "NNG", 0, 1), ("우아", "XR", 2, 4)],
])
def test_bad_normalized_source_ranges_remain_unknown(rows):
    result, _ = supplied("옷 우아해", rows)
    assert result.boundary_executions[0].applicability == "unknown"
    assert not result.aligned.result.complete
    assert not liaison(result)


@pytest.mark.parametrize("text,terms,applicability", [
    ("옷 우아 해", [("옷", "NNG"), ("우아", "XR"), ("해", "XSA-R+EF", (("하", "XSA-R"), ("어", "EF")))], "ineligible"),
    ("옷 우아해명", [("옷", "NNG"), ("우아", "XR"), ("해", "XSA-R+EF", (("하", "XSA-R"), ("어", "EF"))), ("명", "NNG")], "unknown"),
])
def test_another_word_or_unlicensed_nominal_tail_does_not_extend_fusion(text, terms, applicability):
    result, _ = supplied(text, rows_for(text, terms))
    assert result.boundary_executions[0].applicability == applicability
    assert not liaison(result)


@pytest.mark.parametrize("pause,hard,protected", [((3,), None, False), ((4,), None, False), ((), 4, False), ((), None, 4)])
def test_fused_derivation_cannot_cross_internal_barriers(pause, hard, protected):
    text = "옷 우아해"
    rows = rows_for(text, [("옷", "NNG"), ("우아", "XR"), ("해", "XSA-R+EF", (("하", "XSA-R"), ("어", "EF")))])
    result, _ = supplied(text, rows, pause=pause, hard=hard, protected=protected)
    rewrites = result.rewrites
    assert "ko.liaison.lexical" not in {r.rule_id for r in rewrites}
    if hard is None and not protected:
        assert result.boundary_executions[0].applicability == "unknown"


@pytest.mark.parametrize("text,terms", [
    ("출제는 지명이다", [("출제", "NNG"), ("는", "JX"), ("지명", "NNG"), ("이", "VCP"), ("다", "EF")]),
    ("지명은 출제이다", [("지명", "NNG"), ("은", "JX"), ("출제", "NNG"), ("이", "VCP"), ("다", "EF")]),
])
def test_origin_only_root_blocks_owned_place_type_in_both_copula_directions(text, terms):
    rows = rows_for(text, terms)
    result, _ = supplied(text, rows, relation=None)
    assert "ko.sino.tensing.26" not in {r.rule_id for r in result.rewrites}
    annotation = _Annotation.from_tokens(tuple(T(*row) for row in rows), text)
    decision, = owned_root_decisions(text, annotation, nominal_tail_validator=_has_licensed_nominal_tail)
    assert decision.identity_state == "owned_competing"
    assert decision.competing_relation_evidence
    assert not decision.match.root.sense_ids


@pytest.mark.parametrize("text,terms", [
    ("일산동구는 지명이다", [("일산동구", "NNP"), ("는", "JX"), ("지명", "NNG"), ("이", "VCP"), ("다", "EF")]),
    ("지명은 일산동구이다", [("지명", "NNG"), ("은", "JX"), ("일산동구", "NNP"), ("이", "VCP"), ("다", "EF")]),
])
def test_registered_place_identity_remains_supported_in_both_directions(text, terms):
    rows = rows_for(text, terms)
    result, _ = supplied(text, rows, relation=None)
    assert "ko.sino.tensing.26" in {r.rule_id for r in result.rewrites}
    annotation = _Annotation.from_tokens(tuple(T(*row) for row in rows), text)
    decision, = owned_root_decisions(text, annotation, nominal_tail_validator=_has_licensed_nominal_tail)
    assert decision.applies and decision.owned_relation_evidence
    assert not decision.competing_relation_evidence


def test_identity_registration_and_unresolved_types_do_not_require_fake_sense_ids():
    place = OWNED_LEXICAL_ROOTS[1]
    origin, = OWNED_NOMINAL_ORIGIN_ROOTS
    source = lambda kind: SimpleNamespace(noun_classes=frozenset({kind}), owners=())
    assert not place.sense_ids and not origin.sense_ids
    assert _identity_class(source("place_name_type"), place) == "supported"
    assert _identity_class(source("place_name_type"), origin) == "competing_lexical_identity"
    assert _identity_class(source("unregistered_type"), origin) == ""
    assert _identity_class(source("unregistered_type"), place) == ""


@pytest.mark.parametrize("text,terms,expected", [
    ("우유갑", [("우유갑", "NNG")], "우유깝"),
    ("우유갑은", [("우유갑", "NNG"), ("은", "JX")], "우유까븐"),
    ("우유갑은", [("우유", "NNG"), ("갑", "NNG"), ("은", "JX")], "우유까븐"),
    ("우유갑은", [("우유갑은", "NNG+JX", (("우유갑", "NNG"), ("은", "JX")))], "우유까븐"),
    ("우유갑들", [("우유갑", "NNG"), ("들", "XSN")], "우유깝뜰"),
    ("성격", [("성격", "NNG")], "성껵"),
    ("성격으로", [("성격", "NNG"), ("으로", "JKB")], "성껴그로"),
    ("성격으로", [("성격으로", "NNG+JKB", (("성격", "NNG"), ("으로", "JKB")))], "성껴그로"),
    ("성격도", [("성격", "NNG"), ("도", "JX")], "성껵또"),
    ("성격적", [("성격", "NNG"), ("적", "XSN")], "성껵쩍"),
])
def test_atomic_internal_onsets_use_existing_tensing_and_licensed_tail_ownership(text, terms, expected):
    result, _ = supplied(text, rows_for(text, terms), relation=None)
    assert result.aligned.result.surface_pronunciation == expected
    assert "ko.lexical.tensing" in {r.rule_id for r in result.rewrites}
    assert not {r.rule_id for r in result.rewrites} & {"ko.lexical.verified", "ko.official.morpheme"}


@pytest.mark.parametrize("text,terms", [
    ("우유갑", [("우유갑", "NNP")]),
    ("우유갑", [("우유갑", "NNG", (("우유갑", "VV"),))]),
    ("우유갑은", [("우유갑", "NNG"), ("은", "JX", (("는", "JX"),))]),
    ("우유갑님", [("우유갑", "NNG"), ("님", "XSN")]),
    ("가우유갑", [("가", "XPN"), ("우유갑", "NNG")]),
    ("우유각", [("우유각", "NNG")]),
    ("우유갑은 지명이다", [("우유갑", "NNG"), ("은", "JX"), ("지명", "NNG"), ("이", "VCP"), ("다", "EF")]),
    ("성격", [("성격", "NNP")]),
    ("성격", [("성", "NNG"), ("격", "NNG")]),
    ("성격으로", [("성격", "NNG"), ("으로", "JKB", (("으로", "NNG"),))]),
    ("성격화", [("성격", "NNG"), ("화", "XSN")]),
    ("가성격", [("가", "NNG"), ("성격", "NNG")]),
    ("별격", [("별격", "NNG")]),
    ("성격은 지명이다", [("성격", "NNG"), ("은", "JX"), ("지명", "NNG"), ("이", "VCP"), ("다", "EF")]),
])
def test_atomic_internal_fact_does_not_expand_to_wrong_identity_owner_or_unlicensed_tails(text, terms):
    result, _ = supplied(text, rows_for(text, terms), relation=None)
    assert "ko.lexical.tensing" not in {r.rule_id for r in result.rewrites}


@pytest.mark.parametrize("text,terms,cut", [
    ("우유갑", [("우유", "NNG"), ("갑", "NNG")], 2),
    ("성격", [("성격", "NNG")], 1),
])
@pytest.mark.parametrize("barrier", ["pause", "hard", "protected"])
def test_atomic_onsets_preserve_internal_barriers(text, terms, cut, barrier):
    result, _ = supplied(text, rows_for(text, terms), relation=None,
                         pause=(cut,) if barrier == "pause" else (),
                         hard=cut if barrier == "hard" else None,
                         protected=cut if barrier == "protected" else False)
    assert "ko.lexical.tensing" not in {r.rule_id for r in result.rewrites}


def test_atomic_metadata_distinguishes_compound_and_syllable_without_full_readings_or_lengths():
    container, nature = OWNED_INTERNAL_ONSET_ROOTS
    assert (container.spelling, container.hanja, container.internal_onsets) == (
        "우유갑", "牛乳匣", (InternalOnsetConstraint(2, "ㄱ", "ㄲ", "compound_component"),),
    )
    assert (nature.spelling, nature.hanja, nature.parts, nature.internal_onsets) == (
        "성격", "性格", (("성격", "NNG"),), (InternalOnsetConstraint(1, "ㄱ", "ㄲ", "lexical_syllable"),),
    )
    assert not container.tense_boundaries and not nature.tense_boundaries
    assert not container.sense_ids and not nature.sense_ids
    for root in (container, nature):
        text = root.spelling
        annotation = _Annotation.from_tokens((T(text, "NNG", 0, len(text)),), text)
        decision, = owned_root_decisions(text, annotation, nominal_tail_validator=_has_licensed_nominal_tail)
        assert decision.applied_internal_boundaries == (root.internal_onsets[0].offset,)


@pytest.mark.parametrize("offset,source,target,kind", [(0, "ㄱ", "ㄲ", "lexical_syllable"), (True, "ㄱ", "ㄲ", "lexical_syllable"),
    (1, "ㄱ", "ㄷ", "lexical_syllable"), (1, "ㄱ", "ㄲ", "unsupported")])
def test_internal_onset_schema_rejects_invalid_constraints(offset, source, target, kind):
    with pytest.raises(ValueError):
        InternalOnsetConstraint(offset, source, target, kind)
