# SPDX-License-Identifier: MIT
"""정확히 소유한 파생어의 문법 역할을 음운 소비자 사이에서 공유한다."""

from dataclasses import dataclass

from ..model import Handler
from ._shared import _has_phonological_barrier
from .hangul import character_source_spans, is_modern_syllable
from .surface_proof import TokenSurfaceProof as _TokenSurfaceProof, verified_token_surface
from .word_grammar import (ENDINGS as _ENDINGS, PARTICLES as _PARTICLES, NOUNS,
                           VARIABLES as _VARIABLE_TAGS, base_tag as _base_tag, parse_parts)
from .surface_proof import surface_proof_conflict, licensed_spelling
from .nominal_surface import matches_positive_copula_tail, is_vowel_final_nominal_source


@dataclass(frozen=True)
class DerivedWordRole:
    """원문 한 단어의 검증된 형태소열과 최종 어휘 범주다."""

    start: int
    end: int
    role: str
    parts: tuple[tuple[str, str], ...]


def _normalized_owned_parts(token):
    """표면 소유와 정규 형태소 유래를 분리하고 정상 융합 활용만 소비한다."""
    own = token.morphemes or ((token.form, token.tag),)
    if tuple(tag for _, tag in own) != tuple(token.tag.split("+")):
        return None
    if any(not form for form, _ in own):
        return None
    if "".join(form for form, _ in own) == token.form:
        return own
    # 정규화 token은 겹친 원시 용언·어미를 원문 표면 범위에 이미 배정한다.
    # 원형의 연결로 표면을 재생성하지 않으며, 융합 밖의 성분은 원문에 고정한다.
    for index, (_, tag) in enumerate(own[:-1]):
        if _base_tag(tag) not in _VARIABLE_TAGS or own[index + 1][1] not in _ENDINGS:
            continue
        tail = index + 1
        while tail < len(own) and own[tail][1] in _ENDINGS:
            tail += 1
        if any(part_tag not in _PARTICLES for _, part_tag in own[tail:]):
            continue
        prefix = "".join(form for form, _ in own[:index])
        suffix = "".join(form for form, _ in own[tail:])
        if (token.form.startswith(prefix) and token.form.endswith(suffix)
                and len(token.form) > len(prefix) + len(suffix)):
            return own
    return None


def _verified_token_surface(token):
    """공유 합성 증명기를 기존 엄격 파생 역할 API로 연결한다."""
    return verified_token_surface(token)


def _exact_owned_parts(token):
    """원문 전체 표면 증명에 성공한 원형열만 파생 문법으로 전달한다."""
    proof = _verified_token_surface(token)
    return proof.parts if proof is not None else None


@dataclass(frozen=True, slots=True)
class WordCertificate:
    """소유·문법·표면 권한과 단어·내부 성분 범위를 구별하는 증명이다."""

    start: int
    end: int
    parts: tuple[tuple[str, str], ...]
    lexical_status: str
    final_category: str | None
    host_state: str
    tail_state: str
    surface_status: str
    reason: str
    basis_tag: str | None = None
    prefixed: bool = False
    derived: bool = False
    legacy_kind: str | None = None
    observed_tags: tuple[str, ...] = ()
    surface_proofs: tuple[_TokenSurfaceProof, ...] = ()
    possible_categories: frozenset[str] = frozenset()
    scope: str = "word"
    core_starts: tuple[int, ...] = (0,)
    authority_kind: str = "complete_scope"
    grammar_status: str = "unresolved"


_N_RECIPIENT_NOUNS = frozenset({"NNG", "NNP", "NNB", "NNBC", "NP"})
_SIMPLE_PREDICATES = frozenset({"VV", "VA", "VX"})
_LIAISON_BASES = frozenset({"NNG", "NNP", "NNB", "NNBC", "NP", "NR",
                            "VV", "VA", "VX", "VCN", "MAG", "MAJ", "MM"})


def _explicit_opaque_predicate_class(parts, source):
    """명시 불규칙 성분의 범주만 유지하며 불투명 구간 밖은 직접 고정한다."""
    grammar = parse_parts(parts)
    if grammar.lexical_status != "eligible" or grammar.prefixed:
        return False
    if parts[0][1] in {"VV-I", "VA-I", "VX-I"} and all(tag in _ENDINGS for _, tag in parts[1:]):
        return True
    for index, (_, tag) in enumerate(parts[:-1]):
        if tag not in {"XSV-I", "XSA-I"} or parts[index + 1][1] not in _ENDINGS:
            continue
        tail_end = index + 1
        while tail_end < len(parts) and parts[tail_end][1] in _ENDINGS:
            tail_end += 1
        if any(part_tag not in _PARTICLES for _, part_tag in parts[tail_end:]):
            continue
        prefix = "".join(form for form, _ in parts[:index])
        suffix = "".join(form for form, _ in parts[tail_end:])
        if source.startswith(prefix) and source.endswith(suffix) and len(source) > len(prefix) + len(suffix):
            return True
    return False


def _bare_first_inflection_layout(tokens):
    """하나의 기본 용언과 첫 어미가 실제로 분리 소유된 배치만 찾는다."""
    if len(tokens) < 2:
        return False
    stem = _canonical_token_parts(tokens[0])
    first_ending = _canonical_token_parts(tokens[1])
    return (stem is not None and len(stem) == 1 and _base_tag(stem[0][1]) in _SIMPLE_PREDICATES
            and first_ending is not None and len(first_ending) == 1 and first_ending[0][1] in _ENDINGS
            and tokens[0].normalized_end == tokens[1].normalized_start)


def _bare_first_inflection_class(tokens):
    """실제 기본 용언과 첫 어미의 한정된 불투명 구간에서 범주만 보존한다."""
    if not _bare_first_inflection_layout(tokens):
        return False
    stem = _canonical_token_parts(tokens[0])
    first_ending = _canonical_token_parts(tokens[1])
    parts = stem + first_ending
    cursor = tokens[1].normalized_end
    for token in tokens[2:]:
        own = _canonical_token_parts(token)
        if (own is None or token.normalized_start != cursor
                or any(tag not in _ENDINGS | _PARTICLES for _, tag in own)
                or not licensed_spelling(own, token.form)):
            return False
        parts += own
        cursor = token.normalized_end
    grammar = parse_parts(parts)
    return (grammar.lexical_status == "eligible" and not grammar.prefixed and not grammar.derived
            and len(grammar.core_starts) == 1)


def contextual_zero_copula(token, tail_edge, nominal_form):
    """모음 끝 명사 문맥의 실제 영폭 VCP만 예외로 두고 나머지 범위는 대조한다."""
    parts, spans = token.morphemes, token.morpheme_spans
    if not is_vowel_final_nominal_source(nominal_form) or not spans or len(parts) != len(spans):
        return False
    markers = [index for index, span in enumerate(spans) if span[0] == span[1]]
    if not markers or any(parts[index] != ("이", "VCP") or spans[index] != (tail_edge, tail_edge) for index in markers):
        return False
    cursor = token.normalized_start
    for (form, tag), (begin, end) in zip(parts, spans):
        if begin == end:
            continue
        if begin != cursor or not begin < end <= token.normalized_end:
            return False
        actual = token.form[begin - token.normalized_start:end - token.normalized_start]
        alternatives = {form}
        if begin == tail_edge and tag in _ENDINGS:
            if form == "에요":
                alternatives.add("예요")
            if form == "었":
                alternatives.add("였")
        if actual not in alternatives:
            return False
        cursor = end
    return cursor == token.normalized_end


def adnominal_core_evidence(parts, source, *, nominal_host_form=None):
    """정확한 ETM 핵심과 잔여 JX만 확인하며 바깥 부착은 허가하지 않는다."""
    split = next((index for index in range(1, len(parts))
                  if parts[index][1] == "JX" and parts[index - 1][1] == "ETM"), None)
    if split is None or any(tag != "JX" for _, tag in parts[split:]):
        return None
    suffix = "".join(form for form, _ in parts[split:])
    if not suffix or not source.endswith(suffix) or len(source) <= len(suffix):
        return None
    core, surface = tuple(parts[:split]), source[:-len(suffix)]
    grammar = parse_parts(core, initial_host="nominal" if nominal_host_form is not None else None)
    realized = licensed_spelling(core, surface)
    if nominal_host_form is not None:
        realized = realized or matches_positive_copula_tail(
            surface, core, vowel_final_nominal=is_vowel_final_nominal_source(nominal_host_form))
    if grammar.lexical_status == "eligible" and realized:
        return grammar
    return None


def _certify_owned_scope(annotation, start, units, segments, pause_boundaries=(), *,
                         end_bound=None, scope="word"):
    """단어 또는 별도로 입증한 성분 범위의 소유·표면·문법을 같은 방식으로 확인한다."""
    begin = start if isinstance(start, int) and not isinstance(start, bool) else 0
    end, parts, tags, proofs = begin, [], [], []

    def record(status="unresolved", reason="grammatical_evidence_unavailable", *,
               surface="unavailable", grammar=None, category=None, host="unknown",
               tail="unknown", legacy=None, authority="complete_scope", grammar_status=None):
        return WordCertificate(
            begin, end, tuple(parts), status,
            grammar.final_category if grammar is not None else category,
            grammar.host_state if grammar is not None else host,
            grammar.tail_state if grammar is not None and authority != "recipient_class" else tail,
            surface, reason,
            grammar.basis_tag if grammar is not None else (tags[0] if tags else None),
            grammar.prefixed if grammar is not None else False,
            grammar.derived if grammar is not None else False,
            legacy, tuple(tags), tuple(proofs),
            grammar.possible_categories if grammar is not None else frozenset(),
            scope,
            grammar.core_starts if grammar is not None else (0,),
            authority,
            grammar_status if grammar_status is not None else (grammar.lexical_status if grammar is not None else status),
        )

    if annotation is None:
        return record()
    text = annotation.text
    if (isinstance(start, bool) or not isinstance(start, int) or not isinstance(text, str)
            or not 0 <= start < len(text)
            or (scope == "word" and start and text[start - 1].isalnum())):
        return record(reason="word_start_unproven")
    if end_bound is None:
        while end < len(text) and text[end].isalnum():
            end += 1
    elif (isinstance(end_bound, bool) or not isinstance(end_bound, int)
          or not start < end_bound <= len(text)):
        return record(reason="component_range_unproven")
    else:
        end = end_bound
    if (not text[start:end] or not all(is_modern_syllable(char) for char in text[start:end])
            or units is None or len(units) != len(text)):
        return record(reason="whole_korean_word_unproven")
    segment_map, source_maps = [], {}
    if segments:
        if "".join(segment.text for segment in segments) != text:
            return record(reason="source_ownership_conflict", surface="conflict")
        for segment_index, segment in enumerate(segments):
            segment_map.extend((segment_index, local) for local in range(len(segment.text)))
            if hasattr(segment, "source_spans"):
                provenance = segment.source_spans or ((segment.anchor,) if segment.anchor is not None else ())
                source_maps[segment_index] = character_source_spans(segment.text, provenance)
    for offset in range(start, end):
        unit = units[offset]
        if unit.handler is not Handler.KOREAN or unit.syllable is None:
            return record(reason="word_scope_barrier")
        if segments and not 0 <= unit.segment_index < len(segments):
            return record(reason="source_ownership_conflict", surface="conflict")
        if segments:
            expected_segment, local = segment_map[offset]
            if expected_segment != unit.segment_index:
                return record(reason="source_ownership_conflict", surface="conflict")
            segment = segments[unit.segment_index]
            if (segment.handler is not Handler.KOREAN and not (
                    segment.handler is Handler.ENGLISH and segment.rule_id == "english.conventional.v1")):
                return record(reason="word_scope_barrier")
            # 원시 provenance는 치환 뒤 여러 문자에서 공유될 수 있다.
            if unit.source_spans and unit.segment_index in source_maps and unit.source_spans != source_maps[unit.segment_index][local]:
                return record(reason="source_ownership_conflict", surface="conflict")
        if offset > start and _has_phonological_barrier(
                units, offset - 1, offset, segments, pause_boundaries):
            return record(reason="word_scope_barrier")
    cursor, tokens, unavailable, missing_originals = start, [], False, False
    surface_conflicts = []
    while cursor < end:
        token = annotation.starting_at(cursor)
        if token is None:
            return record(reason="whole_word_ownership_unproven")
        if (isinstance(token.normalized_start, bool) or not isinstance(token.normalized_start, int)
                or isinstance(token.normalized_end, bool) or not isinstance(token.normalized_end, int)
                or token.normalized_start != cursor or not cursor < token.normalized_end <= end
                or token.form != text[cursor:token.normalized_end]
                or any(annotation.covering(i) != token for i in range(cursor, token.normalized_end))):
            return record(reason="source_ownership_conflict", surface="conflict")
        tokens.append(token)
        own_tags = tuple(token.tag.split("+"))
        tags.extend(own_tags)
        if not own_tags or any(not tag for tag in own_tags):
            return record(reason="original_tag_conflict", surface="conflict")
        if token.morphemes:
            if (tuple(tag for _, tag in token.morphemes) != own_tags
                    or any(not form for form, _ in token.morphemes)):
                return record(reason="original_tag_conflict", surface="conflict")
            parts.extend(token.morphemes)
        elif len(own_tags) == 1:
            parts.append((token.form, token.tag))
        else:
            missing_originals = True
        proof = _verified_token_surface(token)
        if proof is not None:
            proofs.append(proof)
        elif surface_proof_conflict(token):
            surface_conflicts.append(token)
            unavailable = True
        else:
            unavailable = True
        cursor = token.normalized_end

    grammar = parse_parts(parts) if not missing_originals else None
    contextual_copula = (grammar is not None and grammar.lexical_status == "eligible" and len(parts) >= 3
                        and _base_tag(parts[0][1]) in NOUNS and parts[1] == ("이", "VCP")
                        and text[start:end].startswith(parts[0][0])
                        and matches_positive_copula_tail(text[start + len(parts[0][0]):end], tuple(parts[1:]),
                            vowel_final_nominal=is_vowel_final_nominal_source(parts[0][0])))
    if surface_conflicts and not (contextual_copula and all(
            contextual_zero_copula(token, start + len(parts[0][0]), parts[0][0]) for token in surface_conflicts)):
        return record(reason="surface_evidence_conflict", surface="conflict")
    if missing_originals:
        # 옛 단순 명사 태그열의 권한은 수신 적격성에만 한정한다.
        if tags and all(_base_tag(tag) in _N_RECIPIENT_NOUNS | {"NR"} for tag in tags):
            return record("eligible", "legacy_whole_nominal_recipient", category="noun",
                          host="nominal", tail="none", legacy="nominal_recipient")
        if len(tokens) == 1 and tags and all(tag == "MAG" for tag in tags):
            return record("eligible", "legacy_simple_adverbial_recipient", category="adverb",
                          host="adverbial", tail="none", legacy="adverbial_recipient")
        return record(reason="original_parts_unavailable")

    if grammar.lexical_status == "unresolved":
        core = adnominal_core_evidence(parts, text[start:end])
        if core is not None:
            return record("eligible", "adnominal_core_recipient_unresolved_outer_tail", grammar=core,
                          surface="unavailable" if unavailable else "verified", legacy="adnominal_core_recipient",
                          authority="recipient_class", grammar_status="unresolved")
        if (scope == "word" and len(tokens) >= 2 and _base_tag(tokens[0].tag) in NOUNS
                and _canonical_token_parts(tokens[0]) == ((tokens[0].form, tokens[0].tag),)):
            nominal_parts = len(tokens[0].morphemes) or 1
            tail = tuple(parts[nominal_parts:])
            source_tail = text[tokens[0].normalized_end:end]
            if (tail and _base_tag(tail[0][1]) in _SIMPLE_PREDICATES
                    and (all(tag in _ENDINGS for _, tag in tail[1:]) or _bare_first_inflection_class(tokens[1:]))
                    and parse_parts(tail).lexical_status == "eligible"
                    and (licensed_spelling(tail, source_tail)
                         or (_bare_first_inflection_class(tokens[1:]) if _bare_first_inflection_layout(tokens[1:])
                             else _explicit_opaque_predicate_class(tail, source_tail)))):
                return record("eligible", "initial_nominal_recipient_unresolved_compound_structure",
                              category=None, host="lexical_unknown", tail="unknown",
                              surface="unavailable" if unavailable else "verified", legacy="nominal_predicate_recipient",
                              authority="recipient_class", grammar_status="unresolved")
    if unavailable:
        if grammar.lexical_status == "eligible" and licensed_spelling(parts, text[start:end]):
            return record("eligible", "licensed_spelling_class_recipient", grammar=grammar,
                          legacy="licensed_spelling")
        if grammar.lexical_status == "eligible" and _bare_first_inflection_class(tokens):
            return record("eligible", "bare_first_inflection_class_recipient", grammar=grammar,
                          legacy="bare_first_inflection")
        if (grammar.lexical_status == "eligible" and not grammar.prefixed
                and grammar.tail_state.startswith("auxiliary_")):
            auxiliary_start = next((index for index in range(1, len(parts))
                                    if _base_tag(parts[index][1]) == "VX" and parts[index - 1][1] == "EC"), None)
            part_cursor, opaque_seen, components_valid = 0, False, auxiliary_start is not None
            for token in tokens:
                own = token.morphemes or ((token.form, token.tag),)
                if not licensed_spelling(own, token.form):
                    opaque = (auxiliary_start is not None and part_cursor + len(own) <= auxiliary_start
                              and _explicit_opaque_predicate_class(own, token.form))
                    opaque_seen = opaque_seen or opaque
                    components_valid = components_valid and opaque
                part_cursor += len(own)
            if components_valid and opaque_seen:
                return record("eligible", "legacy_opaque_auxiliary_recipient", grammar=grammar,
                              legacy="opaque_auxiliary")
        # 기존 단순 활용의 어휘 수신 권한만 보존한다. 자모 소유는 발행하지 않는다.
        simple_inflection = (
            len(parts) >= 2 and _base_tag(parts[0][1]) in _SIMPLE_PREDICATES
            and all(tag in _ENDINGS for _, tag in parts[1:])
            and grammar.lexical_status == "eligible"
            and not _bare_first_inflection_layout(tokens)
        )
        if simple_inflection:
            return record("eligible", "legacy_simple_inflection_recipient", grammar=grammar,
                          legacy="simple_inflection")
        # 명시된 불규칙 파생 용언의 옛 어휘 범주 권한만 따로 보존한다.
        # 불투명 활용 바깥 성분은 직접 고정하며 무표지 중간 불일치는 허용하지 않는다.
        if grammar.derived and _explicit_opaque_predicate_class(parts, text[start:end]):
            return record("eligible", "legacy_opaque_derived_predicate_recipient", grammar=grammar,
                          legacy="opaque_derived_predicate")
        # 기존 명사 계사 이형태 증명은 어휘 수신 권한만 보존하며 자모를 만들지 않는다.
        nominal_copula = (
            grammar.lexical_status == "eligible" and len(parts) >= 3
            and _base_tag(parts[0][1]) in NOUNS and parts[1] == ("이", "VCP")
            and text[start:end].startswith(parts[0][0])
            and matches_positive_copula_tail(
                text[start + len(parts[0][0]):end], tuple(parts[1:]),
                vowel_final_nominal=is_vowel_final_nominal_source(parts[0][0]),
            )
        )
        if nominal_copula:
            return record("eligible", "legacy_nominal_copula_recipient", grammar=grammar,
                          legacy="nominal_copula")
        if grammar.lexical_status == "excluded":
            return record("excluded", grammar.reason, grammar=grammar)
        return record(reason="whole_surface_evidence_unavailable", grammar=grammar)
    return record(grammar.lexical_status, grammar.reason, surface="verified", grammar=grammar)


def certify_word(annotation, start, units, segments, pause_boundaries=()):
    """실제 단어 시작에서 원문 전체 단어를 증명하며 내부 시작은 허용하지 않는다."""
    return _certify_owned_scope(annotation, start, units, segments, pause_boundaries)


def _canonical_token_parts(token):
    """실제 토큰 출현의 원형 신원을 확인하며 결합 태그의 원형을 발명하지 않는다."""
    parts = token.morphemes or ((token.form, token.tag),)
    if (tuple(tag for _, tag in parts) != tuple(token.tag.split("+"))
            or any(not form or not tag or "+" in tag for form, tag in parts)):
        return None
    return tuple(parts)


def certify_component_recipient(annotation, left, right, units, segments, pause_boundaries=()):
    """실제 내부 토큰 경계의 오른쪽 성분만 증명하며 단어·합성 구조는 주장하지 않는다."""
    begin = right if isinstance(right, int) and not isinstance(right, bool) else 0

    def unresolved(reason):
        return WordCertificate(begin, begin, (), "unresolved", None, "unknown", "unknown",
                               "unavailable", reason, scope="component")

    if (annotation is None or isinstance(left, bool) or not isinstance(left, int)
            or isinstance(right, bool) or not isinstance(right, int)
            or not isinstance(annotation.text, str) or right != left + 1
            or not 0 <= left < right < len(annotation.text)
            or not is_modern_syllable(annotation.text[left])
            or not is_modern_syllable(annotation.text[right])):
        return unresolved("internal_component_edge_unproven")
    preceding = annotation.ending_at(right)
    following = annotation.starting_at(right)
    if (preceding is None or following is None or preceding == following
            or preceding.normalized_end != right or following.normalized_start != right
            or annotation.starting_at(preceding.normalized_start) != preceding):
        return unresolved("internal_component_edge_unproven")
    left_parts = _canonical_token_parts(preceding)
    right_parts = _canonical_token_parts(following)
    if left_parts is None or right_parts is None:
        return unresolved("original_parts_unavailable")
    previous = _certify_owned_scope(annotation, preceding.normalized_start, units, segments,
                                    pause_boundaries, end_bound=right, scope="component")
    if previous.parts != left_parts or previous.surface_status == "conflict":
        return unresolved("component_source_ownership_unproven")
    if _has_phonological_barrier(units, left, right, segments, pause_boundaries):
        return unresolved("word_scope_barrier")
    return _certify_owned_scope(annotation, right, units, segments, pause_boundaries,
                                end_bound=following.normalized_end, scope="component")


def lexical_liaison_projection(certificate):
    """공유 단어 증명에서 기존 연음 소비자의 범주 정책만 투영한다."""
    if certificate.lexical_status != "eligible":
        return certificate.lexical_status
    if certificate.derived:
        return "eligible" if certificate.final_category in {"noun", "verb", "adjective", "adverb"} else "excluded"
    if certificate.legacy_kind == "nominal_recipient":
        return "eligible"
    return "eligible" if certificate.basis_tag in _LIAISON_BASES else "excluded"


def word_n_insertion_projection(certificate):
    """ㄴ 첨가의 좁은 명사·부사·용언 정책을 문법 상태와 구별한다."""
    if certificate.scope != "word":
        return "unresolved"
    if certificate.lexical_status != "eligible":
        return certificate.lexical_status
    if certificate.derived:
        return "eligible" if certificate.final_category in {"noun", "verb", "adjective", "adverb"} else "excluded"
    if certificate.legacy_kind == "nominal_recipient" or certificate.reason == "whole_nominal_recipient":
        return "eligible" if all(_base_tag(tag) in _N_RECIPIENT_NOUNS for tag in certificate.observed_tags) else "excluded"
    return "eligible" if certificate.basis_tag in _N_RECIPIENT_NOUNS | _SIMPLE_PREDICATES | {"MAG"} else "excluded"


def derived_word_role(annotation, start, units, segments, pause_boundaries=(), *, exact_source=False):
    """정확한 파생 품사가 확인된 경우에만 옛 파생 역할 레코드로 투영한다."""
    certificate = certify_word(annotation, start, units, segments, pause_boundaries)
    if (certificate.lexical_status != "eligible" or not certificate.derived
            or certificate.final_category is None
            or len(certificate.core_starts) != 1
            or certificate.authority_kind != "complete_scope" or certificate.grammar_status != "eligible"
            or exact_source and certificate.surface_status != "verified"):
        return None
    return DerivedWordRole(certificate.start, certificate.end, certificate.final_category, certificate.parts)


def lexical_liaison_target(annotation, start, units, segments, pause_boundaries=()):
    """적격 상태만 참으로 바꾸고 상세 상태는 공유 진입점에 보존한다."""
    return lexical_liaison_projection(
        certify_word(annotation, start, units, segments, pause_boundaries)) == "eligible"


def lexical_component_liaison_target(annotation, left, right, units, segments, pause_boundaries=()):
    """내부 성분의 연음 수신 권한만 참으로 투영하며 외부 단어 실패를 우회하지 않는다."""
    return lexical_liaison_projection(certify_component_recipient(
        annotation, left, right, units, segments, pause_boundaries)) == "eligible"
