# SPDX-License-Identifier: MIT
"""원문 관계의 지시체와 어근 소유권을 분리하여 신원 결정을 기록한다."""

from dataclasses import dataclass

from . import semantic_policy as semantic


@dataclass(frozen=True)
class IdentityEvidence:
    """분류·소유·계사 경로를 같은 원문 target에만 귀속한다."""

    target_id: str
    target_span: tuple[int, int]
    root_span: tuple[int, int]
    owner_span: tuple[int, int]
    scope_id: str
    identity_class: str
    root_identity_or_competing_identity: str
    relation_path: tuple[str, ...]
    anchor_spans: tuple[tuple[int, int], ...]
    attribution_status: str
    polarity: str
    assertion_scope: str
    evidence_kind: str
    unresolved_reason: str = ""


@dataclass(frozen=True)
class OwnedIdentityDecision:
    """미지원과 저증거를 구별하고 기본값·상속을 검토 가능한 결과로 남긴다."""

    match: object
    nominal_end: int
    identity_state: str
    identity_reason: str
    selected_root_identity: str | None
    evidence_kind: str
    owned_relation_evidence: tuple[IdentityEvidence, ...]
    competing_relation_evidence: tuple[IdentityEvidence, ...]
    residual_uncertainty: tuple[str, ...]
    relation_evidence: tuple[IdentityEvidence, ...]
    root_span: tuple[int, int]
    owner_span: tuple[int, int]
    inherited_tail_chain: tuple[object, ...]
    applied_internal_boundaries: tuple[int, ...]
    applies: bool
    match_evidence_kind: str


def _target_id(match):
    return f"{match.root.identity}@{match.start}:{match.end}"


def _relation_record(match, nominal_end, scope, relation, anchors, identity_class, *,
                     polarity="positive", assertion="input_asserted", reason=""):
    return IdentityEvidence(
        _target_id(match), (match.owner_start, nominal_end), (match.start, match.end),
        (match.owner_start, nominal_end), scope, identity_class,
        match.root.identity if identity_class == "supported" else identity_class,
        tuple(relation), tuple(dict.fromkeys(anchors)), "source_owned", polarity, assertion,
        "input_structural_identity" if "name_value" in relation else "input_asserted_identity", reason,
    )


def _same_target(mention, match, nominal_end):
    return (mention.start, mention.end) == (match.owner_start, nominal_end)


def _identity_class(source, root):
    """유형 명사는 관계의 한 논항일 때만 신원 근거로 쓰인다."""
    classes = source.noun_classes
    if classes & {"human", "person_name_type"}:
        return "competing_person"
    if "proper_name_type" in classes:
        return "competing_proper_name"
    if "name_slot" in classes:
        return "competing_name_value" if source.owners else "unresolved_designation"
    allowed = root.identity_classes | frozenset(
        value for sense in root.sense_ids for value in semantic.SENSE_FEATURES[sense].semantic_classes
    )
    excluded = frozenset(value for sense, features in semantic.SENSE_FEATURES.items()
                         if features.spelling == root.spelling and sense not in root.sense_ids
                         for value in features.semantic_classes)
    if classes & allowed:
        return "supported"
    if classes & excluded or "place_name_type" in classes:
        return "competing_lexical_identity"
    return ""


def collect_owned_relations(text, annotation, projections, hard_boundaries=frozenset()):
    """검증한 명사 소유 범위를 기존 절·관형·소유 분석기에 그대로 연결한다."""
    intervals = {(match.owner_start, end) for match, end, _ in projections}
    original = tuple(annotation._tokens_starting_at.values())
    tokens = []
    for token in original:
        interval = next(((start, end) for start, end in intervals if start <= token.normalized_start < end), None)
        if interval is None:
            tokens.append(semantic.SemanticToken(token.form, token.tag, token.normalized_start,
                                                 token.normalized_end, token.morphemes))
        elif token.normalized_start == interval[0]:
            # 이 합성은 구조가 검증된 소유 범위의 명사 좌표다. 뜻 신원을 주입하지 않는다.
            tokens.append(semantic.SemanticToken(text[interval[0]:interval[1]], "NNG", *interval))
    tokens = tuple(tokens)
    scopes, unsupported = semantic._scope_index(text, tokens, hard_boundaries)
    heads = {index: token for index, token in enumerate(tokens) if (token.start, token.end) in intervals}
    evidence = {index: [] for index in heads}
    records = { _target_id(match): [] for match, _, _ in projections }
    quotes = semantic._balanced_quote_ranges(text, hard_boundaries)

    def consume(event, adnominal, scope):
        pairs = []
        if event.tag in {"VCP", "VCN"}:
            subject = semantic._role_or_topic(event, "subject", True)
            complement = semantic._unique_argument(event, "nominal_complement")
            if subject is not None and complement is not None:
                pairs.extend((target, source, ("copula", "subject", "type_or_name_value"))
                             for target in subject.members for source in complement.members)
                pairs.extend((target, source, ("copula", "complement", "type_or_name_value"))
                             for target in complement.members for source in subject.members)
            else:
                subjects = tuple(member for argument in event.arguments if argument.role in {"subject", "topic"}
                                 for member in argument.members)
                complements = tuple(member for argument in event.arguments if argument.role == "nominal_complement"
                                    for member in argument.members)
                pairs.extend((target, source, ("copula", "unresolved_attribution"))
                             for left, right in ((subjects, complements), (complements, subjects))
                             for target in left for source in right)
        classified = semantic._classification_parts(event)
        if classified is not None:
            _, members, category = classified
            if members is not None and category is not None:
                pairs.extend((target, source, ("classification", "member", "category"))
                             for target in members.members for source in category.members)
        if event.predicate in semantic._NAMING_PREDICATES:
            label = semantic._naming_label(event)
            owner = semantic._unique_argument(event, "object")
            if label is not None and owner is not None:
                pairs.extend((target, source, ("naming", "label", "owner"))
                             for target in label.members for source in owner.members)
        for match, nominal_end, _ in projections:
            for target, source, path in pairs:
                if not _same_target(target, match, nominal_end):
                    continue
                identity = _identity_class(source, match.root)
                if "naming" in path and identity == "competing_person":
                    identity = "competing_name_value"
                    path += ("name_value",)
                if not identity:
                    continue
                unresolved = ""
                if "unresolved_attribution" in path:
                    unresolved = "unsupported_target_relevant_identity_relation"
                if adnominal:
                    unresolved = "target_relevant_adnominal_identity_relation"
                if source.noun_classes & {"unresolved_modifier", "unresolved_relation"}:
                    unresolved = "unsupported_target_relevant_identity_relation"
                if identity == "unresolved_designation":
                    unresolved = "generic_designation_is_not_proved_person_identity"
                assertion = "unadopted_quoted_assertion" if any(left < event.start < right for left, right in quotes) else "input_asserted"
                polarity = "negative" if event.negated or event.tag == "VCN" else "positive"
                anchors = [(target.start, target.end), (source.start, source.end), (event.start, event.end)]
                for owner in source.owners:
                    anchors.append((owner.start, owner.end))
                    path += ("name_value", "possessive_owner")
                record = _relation_record(match, nominal_end, scope, path, anchors,
                                          "unresolved" if unresolved else identity,
                                          polarity=polarity, assertion=assertion, reason=unresolved)
                if record not in records[_target_id(match)]:
                    records[_target_id(match)].append(record)

    for scope, indices in scopes.items():
        semantic._scan_scope(tokens, indices, evidence, heads, set(),
                             event_sink=lambda event, adnominal, scope=scope: consume(event, adnominal, str(scope)))
    # 인용된 명사 자체와 타인의 인용 주장은 서로 다르다. 바깥 관계만 다시 연결한다.
    atoms = semantic._quote_atoms(text, tokens, hard_boundaries, heads, set())
    for number, units in enumerate(semantic._quotation_units(text, tokens, hard_boundaries, heads, set(), atoms)):
        semantic._scan_scope(tokens, (), evidence, heads, set(), supplied_units=units, quote_mode=True,
                             event_sink=lambda event, adnominal, number=number: consume(event, adnominal, f"quote_nominal:{number}"))
    return records


def decide_owned_identity(text, match, nominal_end, chain, choice, relations):
    """경쟁·충돌을 먼저 판정하고 단순 저증거에만 등록 기본 읽기를 허용한다."""
    records = list(relations.get(_target_id(match), ()))
    selection_reason = choice.reason if choice is not None else "insufficient_evidence"
    selected = choice is not None and choice.sense_id in match.root.sense_ids
    if choice is not None and choice.sense_id is not None:
        records.append(_relation_record(match, nominal_end, "semantic_selection", ("selected_sense",),
                                        [(item.anchor_start, item.anchor_end) for item in choice.evidence],
                                        "supported" if selected else "competing_lexical_identity"))
    if match.evidence_kind == "registered_composition":
        registration = _relation_record(match, nominal_end, "registered_owner", ("exact_registered_composition",),
                                        ((match.owner_start, match.owner_end),), "supported")
        from dataclasses import replace
        records.append(replace(registration, evidence_kind="registered_composition_inference"))
    asserted = tuple(item for item in records if item.polarity == "positive" and item.assertion_scope == "input_asserted")
    supported = tuple(item for item in asserted if item.identity_class == "supported")
    competing = tuple(item for item in asserted if item.identity_class.startswith("competing_"))
    unresolved = tuple(item.unresolved_reason for item in asserted if item.unresolved_reason)
    if any(item.polarity == "negative" and item.identity_class == "supported"
           and item.assertion_scope == "input_asserted" for item in records):
        unresolved += ("negated_allowed_identity_relation",)
    if choice is not None and not selected and choice.reason != "insufficient_evidence":
        if choice.sense_id is None:
            unresolved += (choice.reason,)
    if competing:
        state, reason, applies = "owned_competing", "conflicting_owned_identities" if supported else "owned_competing_identity", False
        kind, match_kind = "input_asserted_identity", ""
    elif unresolved:
        state, reason, applies = "unresolved", unresolved[0], False
        kind, match_kind = "analyzer_structure_only", ""
    elif supported:
        state, reason, applies = "owned_supported", "source_owned_support", True
        kind = "registered_composition_inference" if match.evidence_kind == "registered_composition" else "input_asserted_identity"
        match_kind = "registered_composition" if match.evidence_kind == "registered_composition" else "selected_sense"
    else:
        state, reason = "unresolved", "low_evidence_without_owned_conflict"
        applies = match.root.default_reading and selection_reason == "insufficient_evidence"
        kind = "dictionary_default_policy" if applies else "analyzer_structure_only"
        match_kind = kind
    if chain and applies:
        if kind == "dictionary_default_policy":
            kind = match_kind = "inherited_dictionary_default_policy"
        else:
            kind = "inherited_" + kind
    internal_boundaries = tuple(match.start + item.offset for item in match.root.internal_onsets)
    if not internal_boundaries:
        internal_boundaries = (match.start + 1,)
    return OwnedIdentityDecision(match, nominal_end, state, reason, match.root.identity if applies else None,
                                 kind, supported, competing, tuple(dict.fromkeys(unresolved)), tuple(records),
                                 (match.start, match.end), (match.owner_start, nominal_end), chain,
                                 internal_boundaries if applies else (), applies, match_kind)
