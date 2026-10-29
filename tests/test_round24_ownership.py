"""기존 원문·원자 계약에서 얻은 열두 관계·소유 범위 주장이다."""

from dataclasses import replace

from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean import engine
from g2p_ko.korean.morphology import _Annotation, _has_licensed_nominal_tail
from g2p_ko.korean.owned_identity import _relation_record, _target_id, decide_owned_identity
from g2p_ko.korean.owned_lexical import owned_root_decisions
from g2p_ko.korean.semantic_policy import SemanticToken, select_senses
from g2p_ko.model import AnalysisToken
from test_round23_owned_lexical import affected, run, segment


def decisions(text, rows=None):
    tokens = KiwiAnalyzer().analyze_components(text) if rows is None else tuple(AnalysisToken(*row) for row in rows)
    semantic = tuple(SemanticToken(t.form, t.tag, t.normalized_start, t.normalized_end, t.morphemes) for t in tokens)
    return tuple(owned_root_decisions(text, _Annotation.from_tokens(tokens, text), select_senses(text, semantic),
                                     nominal_tail_validator=_has_licensed_nominal_tail))


def abstract_decision(*records, place=False):
    text = "일산동구" if place else "문자"
    base, = decisions(text, [(text, "NNP" if place else "NNG", 0, len(text))])
    evidence = []
    for identity, polarity, assertion, reason in records:
        evidence.append(_relation_record(base.match, base.nominal_end, "abstract_owned_relation",
                                         ("copula", "subject", "type"), ((0, 2),), identity,
                                         polarity=polarity, assertion=assertion, reason=reason))
    return decide_owned_identity(text, base.match, base.nominal_end, (), None,
                                 {_target_id(base.match): evidence})


def test_01_same_target_person_blocks_default_on_source_api():
    for text in ("문자는 인명이다", "문자는 사람이다"):
        decision, = decisions(text)
        assert decision.identity_state == "owned_competing" and not decision.applies
        assert affected(engine.pronounce((segment(text),))) == []


def test_02_owned_name_value_is_competing_on_source_api():
    text = "그의 이름은 문자다."
    decision, = decisions(text)
    assert decision.identity_state == "owned_competing" and not decision.applies
    assert any("possessive_owner" in item.relation_path for item in decision.competing_relation_evidence)
    assert affected(engine.pronounce((segment(text),))) == []


def test_03_registered_place_cannot_override_owned_competitor():
    decision = abstract_decision(("competing_person", "positive", "input_asserted", ""), place=True)
    assert decision.identity_state == "owned_competing" and not decision.applies
    assert decision.owned_relation_evidence and decision.competing_relation_evidence


def test_04_unrelated_role_is_not_a_target_identity():
    text = "문자를 보냈다"
    decision, = decisions(text)
    assert decision.identity_state == "unresolved" and decision.applies
    assert not decision.competing_relation_evidence
    assert decision.evidence_kind == "dictionary_default_policy"


def test_05_negated_and_unadopted_competitors_are_not_positive():
    for polarity, assertion in (("negative", "input_asserted"), ("positive", "unadopted_quoted_assertion")):
        decision = abstract_decision(("competing_person", polarity, assertion, ""))
        assert decision.applies and not decision.competing_relation_evidence
        assert decision.relation_evidence[0].polarity == polarity
        assert decision.relation_evidence[0].assertion_scope == assertion


def test_06_same_target_supported_competing_conflict_is_held():
    decision = abstract_decision(("supported", "positive", "input_asserted", ""),
                                 ("competing_person", "positive", "input_asserted", ""))
    assert decision.identity_reason == "conflicting_owned_identities" and not decision.applies


def test_07_low_evidence_retains_labeled_default():
    decision = abstract_decision()
    assert decision.identity_state == "unresolved" and decision.evidence_kind == "dictionary_default_policy"
    assert not decision.owned_relation_evidence and decision.applies


def test_08_target_relevant_unsupported_relation_cannot_default():
    decision = abstract_decision(("unresolved", "positive", "input_asserted", "unsupported_target_relevant_identity_relation"))
    assert decision.identity_state == "unresolved" and not decision.applies
    assert decision.identity_reason != "low_evidence_without_owned_conflict"


def test_09_valid_symbol_head_survives_attached_nonidentity_modifier():
    text = "이 문자는 소리를 적는 기호다."
    decision, = decisions(text)
    assert decision.identity_state == "owned_supported" and decision.evidence_kind == "input_asserted_identity"
    assert affected(engine.pronounce((segment(text),))) == [("ko.lexical.tensing", 3)]


def test_10_verified_plural_particle_has_equivalent_whole_split_projection():
    text = "문자들을"
    split = [("문자", "NNG", 0, 2), ("들", "XSN", 2, 3), ("을", "JKO", 3, 4)]
    whole = [(text, "NNG+XSN+JKO", 0, 4, (("문자", "NNG"), ("들", "XSN"), ("을", "JKO")))]
    for rows in (split, whole):
        decision, = decisions(text, rows)
        assert decision.evidence_kind == "inherited_dictionary_default_policy" and decision.applies
        assert decision.root_span == (0, 2) and decision.owner_span == (0, 3)
        assert decision.applied_internal_boundaries == (1,)
        assert affected(run(text, rows)) == [("ko.lexical.tensing", 1)]


def test_11_verified_derivation_preserves_root_feature_only():
    text = "문자적"
    rows = [("문자", "NNG", 0, 2), ("적", "XSN", 2, 3)]
    decision, = decisions(text, rows)
    assert decision.applies and decision.evidence_kind == "inherited_dictionary_default_policy"
    assert decision.inherited_tail_chain[0][0].affix_identity == "nominal_relational_derivation"
    assert affected(run(text, rows)) == [("ko.lexical.tensing", 1)]


def test_12_registered_nr_projection_is_locally_aligned():
    text = "일산동구"
    rows = [("일", "NR", 0, 1), ("산", "NNG", 1, 2), ("동구", "NNG", 2, 4)]
    decision, = decisions(text, rows)
    assert decision.applies and decision.root_span == (0, 2)
    assert decision.evidence_kind == "registered_composition_inference"
    assert affected(run(text, rows)) == [("ko.sino.tensing.26", 1)]
    assert not decisions(text, [("일산", "NR", 0, 2), ("동구", "NNG", 2, 4)])
