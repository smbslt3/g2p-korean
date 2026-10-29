# SPDX-License-Identifier: MIT
"""원문에서 고정한 수신 역할을 제15·17·29항의 공통 소비자에 전달한다."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..model import Handler
from ._shared import _has_hard_boundary, _has_phonological_barrier, _record, _trace_before
from .hangul import decompose_syllable
from .rules import CODA_TRANSITIONS
from .surface_proof import (SourceAtom, TokenSurfaceProof, surface_proof_conflict,
                            verified_token_surface, licensed_spelling)
from .word_grammar import NOUNS, PARTICLES, SUFFIXES, ENDINGS, GrammarResult, base_tag, parse_parts
from .word_roles import certify_word, certify_component_recipient, lexical_liaison_projection, _certify_owned_scope
from .intrinsic_boundaries import IntrinsicBoundaryFact, INTRINSIC_BOUNDARY_FACTS


_N_VOWELS = frozenset({"ㅣ", "ㅑ", "ㅒ", "ㅕ", "ㅖ", "ㅛ", "ㅠ"})

# 완성 발음 없이 정확한 표제의 내부 성분과 결합 관계만 보충한다.
# 근거는 Verified_Rule_Boundary_Consumers_KO.md의 국립국어원 일차 자료다.
_STRUCTURES = (
    ("값어치", frozenset({"NNG"}), (("값", "NNG"), ("어치", "XSN")),
     1, "semantic_suffix_eochi", "derivation", "korean.go.kr:334443"),
    ("곧이곧대로", frozenset({"MAG"}), (("곧", "VA"), ("이", "XSM"), ("곧대로", "MAG")),
     1, "formal_suffix_i", "adverbial_derivation", "korean.go.kr:314388"),
    ("밭이랑", frozenset({"NNG"}), (("밭", "NNG"), ("이랑", "NNG")),
     1, "lexical_component", "compound", "korean.go.kr:322677"),
)


@dataclass(frozen=True, slots=True)
class CanonicalBoundaryFact:
    """통짜 원형의 내부 역할만 보충하며 원래 분석 출현을 새로 만들지 않는다."""

    id: str
    owner_form: str
    owner_pos: frozenset[str]
    base_span: tuple[int, int]
    affix_span: tuple[int, int]
    role: str
    relation_alternatives: tuple[str, ...]
    base_headword: str | None
    base_category: str | None
    source_ids: tuple[str, ...]


# 승인된 Opaque_Canonical_Lexical_Structure_Facts.json의 다섯 원형 사실만 옮겼다.
# 묻히의 의미 대안과 굳이의 기저 품사 미확정을 그대로 남긴다.
_CANONICAL_FACTS = (
    CanonicalBoundaryFact("butida_causative_i", "붙이", frozenset({"VV"}), (0, 1), (1, 2),
        "formal_suffix_i", ("causative",), "붙다", None,
        ("orthography6_commentary", "qna318232", "opendict31751")),
    CanonicalBoundaryFact("guthida_causative_hi", "굳히", frozenset({"VV"}), (0, 1), (1, 2),
        "formal_suffix_hi", ("causative",), "굳다", None,
        ("orthography6_commentary", "qna336018")),
    CanonicalBoundaryFact("dathida_passive_hi", "닫히", frozenset({"VV"}), (0, 1), (1, 2),
        "formal_suffix_hi", ("passive",), "닫다", None,
        ("orthography6_commentary", "nklife1992_close", "qna336018")),
    CanonicalBoundaryFact("muthida_hi", "묻히", frozenset({"VV"}), (0, 1), (1, 2),
        "formal_suffix_hi", ("passive", "causative"), "묻다", None,
        ("orthography6_commentary", "qna336018", "qna316918", "qna335457")),
    CanonicalBoundaryFact("gudi_adverbial_i", "굳이", frozenset({"MAG"}), (0, 1), (1, 2),
        "formal_suffix_i", ("adverbial_derivation",), None, "root",
        ("orthography6_commentary", "qna323107", "qna319604")),
)


@dataclass(frozen=True, slots=True)
class LexicalComponentFact:
    """형식 이가 아닌 어휘 성분 소유만 보충하며 합성어 분류를 확정하지 않는다."""

    id: str
    owner_form: str
    owner_pos: frozenset[str]
    component_spans: tuple[tuple[int, int], ...]
    component_pos: tuple[frozenset[str], ...]
    source_ids: tuple[str, ...]
    compound_classification: None = None
    deeper_morphology: None = None
    article29_authority: bool = False


# 승인된 Opaque_Lexical_Component_Godieo_Fact_KO.json의 유일한 거친 성분 사실이다.
_LEXICAL_COMPONENT_FACTS = (
    LexicalComponentFact("godieo_lexical_adverb_components", "곧이어", frozenset({"MAG"}),
        ((0, 1), (1, 3)), (frozenset({"MAG"}), frozenset({"MAG"})),
        ("orthography6_commentary", "qna319893", "qna312523", "qna312265")),
)


@dataclass(frozen=True, slots=True)
class RuleBoundary:
    """공유 문법·표면 증명과 실제 음절쌍에 귀속된 한 수신 권한이다."""

    pair: tuple[int, int]
    word_span: tuple[int, int]
    parts: tuple[tuple[str, str], ...]
    role: str | None
    relation: str | None
    source: str
    status: str
    applicability: str
    reason: str
    article: str | None = None
    donor_origin: SourceAtom | None = None
    recipient_origins: tuple[SourceAtom, ...] = ()
    surface_proofs: tuple[TokenSurfaceProof, ...] = ()
    grammar: GrammarResult | None = None
    coda: str | None = None
    onset: str | None = None
    vowel: str | None = None
    remainder: str | None = None
    moved_onset: str | None = None
    attachment_span: tuple[int, int] | None = None
    lexical_fact: CanonicalBoundaryFact | LexicalComponentFact | None = None
    intrinsic_fact: IntrinsicBoundaryFact | None = None
    canonical_owner_occurrence: int | None = None
    intrinsic_mapping: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryEvent:
    """중복 요청과 무관하게 한 물리 경계를 한 번 실행한 결과다."""

    boundary: RuleBoundary
    status: str
    applicability: str
    reason: str
    changed: bool
    rule_ids: tuple[str, ...] = ()


def _word_start(text, offset):
    while offset and text[offset - 1].isalnum():
        offset -= 1
    return offset


def _syntax_scope(annotation, left, units, segments):
    """실제 HARD·보호 분석 섬에서만 문법 범위를 자르며 휴지는 문법에 넣지 않는다."""
    text = annotation.text
    word_start, word_end = _word_start(text, left), left + 1
    while word_end < len(text) and text[word_end].isalnum():
        word_end += 1

    def cut(offset):
        return (_has_hard_boundary(units[offset - 1].segment_index, units[offset].segment_index, segments)
                or units[offset - 1].handler is Handler.PROTECTED or units[offset].handler is Handler.PROTECTED)

    begin, end = left, left + 1
    while begin > word_start and not cut(begin):
        begin -= 1
    while end < word_end and not cut(end):
        end += 1
    return begin, end, begin == word_start and end == word_end


def _owned_atoms(certificate):
    """각 토큰의 지역 출현 번호를 단어 원형열의 출현 번호로 옮긴다."""
    atoms, steps, shift = {}, [], 0
    for proof in certificate.surface_proofs:
        for atom in proof.atoms:
            origins = tuple(replace(origin, occurrence=origin.occurrence + shift)
                            for origin in atom.origins)
            atoms[(atom.offset, atom.role)] = (atom.jamo, origins)
        steps.extend((step.rule_id, (step.boundary[0] + shift, step.boundary[1] + shift),
                      tuple(replace(origin, occurrence=origin.occurrence + shift)
                            for origin in step.deleted)) for step in proof.steps)
        shift += len(proof.parts)
    return atoms, tuple(steps)


def _source_atom(parts, index, offset, role):
    """표면 발음이 아닌 명시 원형에서 해당 자모를 찾는다."""
    import unicodedata
    atoms = unicodedata.normalize("NFD", parts[index][0][offset])
    prefix = {"onset": (0x1100, 0x1112), "vowel": (0x1161, 0x1175),
              "coda": (0x11A8, 0x11C2)}[role]
    jamo = next((jamo for jamo in atoms if prefix[0] <= ord(jamo) <= prefix[1]), None)
    return SourceAtom(index, offset, role, jamo) if jamo is not None else None


def _actual_origin(atom, expected):
    return atom is not None and expected is not None and expected in atom[1]


def _role(parts, index, annotation, right, proofs):
    form, tag = parts[index]
    tag = base_tag(tag)
    if tag in PARTICLES and form.startswith("이"):
        return "formal_particle", "particle_attachment"
    if tag == "VCP" and form == "이":
        return "formal_particle", "copular_attachment"
    if tag in ENDINGS and form == "이":
        return "formal_ending_i", "predicate_inflection"
    if tag in SUFFIXES:
        if form == "어치" and tag == "XSN":
            return "semantic_suffix_eochi", "derivation"
        if form in {"이", "히"}:
            return "formal_suffix_i" if form == "이" else "formal_suffix_hi", "derivation"
    if (tag in NOUNS and base_tag(parts[index - 1][1]) in NOUNS
            and right in annotation.compound_boundaries):
        return "lexical_component", "compound"
    return None, None


def _structural_boundary(certificate, annotation, pair):
    """통짜 원형의 정확한 신원 또는 같은 명시 구조에만 최소 사실을 부가한다."""
    left, right = pair
    text = annotation.text
    for spelling, owner_tags, structure, boundary_index, role, relation, source in _STRUCTURES:
        edge = sum(len(form) for form, _ in structure[:boundary_index])
        start, end = right - edge, right - edge + len(spelling)
        if start < certificate.start or end > certificate.end or text[start:end] != spelling:
            continue
        cursor, matching, opaque = start, [], False
        while cursor < end:
            token = annotation.starting_at(cursor)
            if token is None or token.normalized_end > certificate.end:
                break
            proof = next((proof for proof in certificate.surface_proofs if proof.start == cursor), None)
            if proof is None:
                break
            own_end = cursor
            for form, tag in proof.parts:
                next_end = own_end + len(form)
                if own_end < end:
                    if next_end > end:
                        break
                    matching.append((form, tag))
                own_end = next_end
            cursor = min(token.normalized_end, end)
        if cursor != end or not matching:
            continue
        if matching == [(spelling, next(iter(owner_tags)))] and start == certificate.start:
            opaque = True
        elif tuple(matching) != structure:
            # 명시된 다른 합법적 동형 역할을 표제 사실로 덮어쓰지 않는다.
            continue
        if not opaque and start != certificate.start:
            continue
        # 정확한 내부 구조의 뒤 내용은 등록된 계속 범위만 허용한다.
        # 바깥 꼬리 문법은 그 정확 표제 신원에 귀속하여 공유 전이로 검사한다.
        tail, offset = [], certificate.start
        for form, tag in certificate.parts:
            if offset >= end:
                tail.append((form, tag))
            offset += len(form)
        grammar = parse_parts(((spelling, next(iter(owner_tags))), *tail))
        if grammar.lexical_status != "eligible":
            continue
        donor_index = boundary_index - 1
        donor = _source_atom(structure, donor_index, len(structure[donor_index][0]) - 1, "coda")
        recipient = tuple(atom for atom in (
            _source_atom(structure, boundary_index, 0, "onset"),
            _source_atom(structure, boundary_index, 0, "vowel")) if atom is not None)
        return structure, role, relation, "lexical_structure:" + source, donor, recipient, grammar, (start, certificate.end)
    return None


def _boundary_grammar(certificate, parts, index, role, atoms, right, annotation):
    """전체 단어 권한과 실제 이웃 숙주·꼬리만의 권한을 구별한다."""
    if certificate.lexical_status == "eligible" and certificate.grammar_status == "eligible":
        grammar = parse_parts(parts)
        if role == "formal_ending_i" and not grammar.boundaries[index].inflection:
            return None
        return grammar, (certificate.start, certificate.end), "analysis"
    if parts[index] == ("이", "VCP") or role == "formal_ending_i":
        return None
    if (certificate.grammar_status != "unresolved"
            or certificate.reason != "unowned_content_or_unsupported_structure"
            or not all(base_tag(tag) in NOUNS for _, tag in parts[:index - 1])):
        return None
    # 앞 명사열의 합성이나 접미사 전체 범위를 주장하지 않는다.
    if role == "lexical_component":
        if (right not in annotation.compound_boundaries or base_tag(parts[index - 1][1]) not in NOUNS
                or any(tag not in PARTICLES for _, tag in parts[index + 1:])):
            return None
        grammar = parse_parts(parts[index:])
    else:
        grammar = parse_parts(parts[index - 1:])
    if grammar.lexical_status != "eligible":
        return None
    positions = [offset for (offset, _), (_, origins) in atoms.items()
                 if any(origin.occurrence == index - 1 for origin in origins)]
    if not positions:
        return None
    return grammar, (min(positions), certificate.end), "analysis_local_attachment"


def _owned_non_n_fact(certificate, text, left, right):
    """명시 명사 성분 뒤 조사 꼬리 때문에 기존 정확 비첨가 신원을 잃지 않는다."""
    from .lexicon import NO_N_INSERTION_LEXEMES
    if "".join(form for form, _ in certificate.parts) != text[certificate.start:certificate.end]:
        return False
    ranges, offset = [], certificate.start
    for form, tag in certificate.parts:
        ranges.append((offset, offset + len(form), tag))
        offset += len(form)
    for spelling in NO_N_INSERTION_LEXEMES:
        for start, _, _ in ranges:
            end = start + len(spelling)
            core = [(begin, finish, tag) for begin, finish, tag in ranges if start <= begin < end]
            if (start <= left < right < end and text[start:end] == spelling and core
                    and core[-1][1] == end and all(base_tag(tag) in NOUNS for _, _, tag in core)):
                return True
    return False


def _canonical_boundary(certificate, atoms, steps, pair):
    """정확 원형 사실을 원래 출현·내부 offset과 승인 표면에 연결한다."""
    left, right = pair
    parts = certificate.parts
    for fact in _CANONICAL_FACTS:
        owners = []
        for index, (form, tag) in enumerate(parts):
            if form == fact.owner_form and base_tag(tag) in fact.owner_pos:
                owners.append(tuple((index, offset) for offset in range(len(form))))
            if fact.owner_pos == frozenset({"MAG"}) and tag == "MAG":
                mapping, joined = [], ""
                for current in range(index, len(parts)):
                    own_form, own_tag = parts[current]
                    if own_tag != "MAG":
                        break
                    joined += own_form
                    mapping.extend((current, offset) for offset in range(len(own_form)))
                    if joined == fact.owner_form and current > index:
                        owners.append(tuple(mapping))
                        break
                    if not fact.owner_form.startswith(joined):
                        break
        for owner in owners:
            grammar = parse_parts(parts)
            if certificate.lexical_status != "eligible" or certificate.grammar_status != "eligible":
                # 정확 부사 성분 뒤 조사만의 꼬리는 그 어휘 신원으로 별도 증명한다.
                begin, finish = owner[0][0], owner[-1][0] + 1
                if (fact.owner_pos != frozenset({"MAG"}) or begin != 0
                        or certificate.grammar_status != "unresolved"
                        or certificate.reason != "unowned_content_or_unsupported_structure"
                        or any(tag not in PARTICLES for _, tag in parts[finish:])):
                    continue
                grammar = parse_parts(((fact.owner_form, "MAG"), *parts[finish:]))
                if grammar.lexical_status != "eligible":
                    continue
            donor_index, donor_offset = owner[fact.base_span[1] - 1]
            recipient_index, recipient_offset = owner[fact.affix_span[0]]
            donor = _source_atom(parts, donor_index, donor_offset, "coda")
            onset = _source_atom(parts, recipient_index, recipient_offset, "onset")
            vowel = _source_atom(parts, recipient_index, recipient_offset, "vowel")
            if (not _actual_origin(atoms.get((left, "coda")), donor)
                    or not _actual_origin(atoms.get((right, "onset")), onset)
                    or not _actual_origin(atoms.get((right, "vowel")), vowel)):
                continue
            actual_vowel = atoms[(right, "vowel")][1]
            if len(actual_vowel) > 1 and not any(
                    rule == "맞춤법.36" and boundary == (recipient_index, recipient_index + 1)
                    and recipient_index + 1 < len(parts) and parts[recipient_index + 1][1] in ENDINGS
                    and (ending_vowel := _source_atom(parts, recipient_index + 1, 0, "vowel")) is not None
                    and ending_vowel.jamo == "ᅥ" and ending_vowel in actual_vowel
                    for rule, boundary, _ in steps):
                continue
            owner_occurrences = {index for index, _ in owner}
            positions = [offset for (offset, _), (_, origins) in atoms.items()
                         if any(origin.occurrence in owner_occurrences for origin in origins)]
            relation = fact.relation_alternatives[0] if len(fact.relation_alternatives) == 1 else "derivation_alternatives"
            choice = (parts, fact.role, relation, "canonical_lexical_structure:" + fact.id,
                      donor, (onset, *actual_vowel), grammar, (min(positions), certificate.end))
            return choice, fact
    return None


def _intrinsic_target_mapping(certificate, annotation, pair, fact, donor, onset, vowel):
    """전체 범주 권한과 독립된 원형 내부 두 음절의 실제 자모 대응만 확인한다."""
    first = annotation.starting_at(certificate.start)
    if first is None or annotation.covering(pair[0]) != first or annotation.covering(pair[1]) != first:
        return None
    own = first.morphemes or ((first.form, first.tag),)
    if tuple(certificate.parts[:len(own)]) != tuple(own) or own[0] != certificate.parts[0]:
        return None
    proof = verified_token_surface(first)
    if proof is not None:
        atoms = {(atom.offset, atom.role): atom for atom in proof.atoms}
        if not all((actual := atoms.get(key)) is not None
                   and actual.jamo == expected.jamo and actual.origins == (expected,)
                   for key, expected in (((pair[0], "coda"), donor), ((pair[1], "onset"), onset),
                                         ((pair[1], "vowel"), vowel))):
            return None
        if licensed_spelling(certificate.parts, annotation.text[certificate.start:certificate.end]):
            return "surface_proof"
    if certificate.legacy_kind not in {"licensed_spelling", "simple_inflection", "bare_first_inflection", "opaque_auxiliary"}:
        return None
    parts = certificate.parts
    grammar = parse_parts(parts)
    if len(parts) < 2 or parts[1][1] not in ENDINGS or not grammar.boundaries[1].inflection:
        return None
    # 기존 첫 활용 접합부의 마지막 어간 음절 이전만 직접 대응한다.
    opaque_start = certificate.start + len(fact.canonical_owner) - 1
    if (pair != (certificate.start + fact.boundary_offset - 1, certificate.start + fact.boundary_offset)
            or pair[1] >= opaque_start
            or annotation.text[certificate.start:opaque_start] != fact.canonical_owner[:-1]):
        return None
    supplied, ranges, cursor = [], [], certificate.start
    while cursor < certificate.end:
        token = annotation.starting_at(cursor)
        if (token is None or token.normalized_start != cursor
                or not cursor < token.normalized_end <= certificate.end):
            return None
        token_parts = token.morphemes or ((token.form, token.tag),)
        supplied.extend(token_parts)
        ranges.extend(token.morpheme_spans if token.morpheme_spans else (None,) * len(token_parts))
        cursor = token.normalized_end
    if tuple(supplied) != parts or len(ranges) != len(parts) or ranges[0] is None or ranges[1] is None:
        return None
    owner_span, ending_span = ranges[:2]
    if (owner_span[0] != certificate.start or not owner_span[0] <= pair[0] < pair[1] < owner_span[1]
            or ending_span[0] < opaque_start or not ending_span[0] < ending_span[1] <= certificate.end):
        return None
    tail_start = ending_span[1]
    if any(span is not None and span[0] < tail_start for span in ranges[2:]):
        return None
    tail = annotation.text[tail_start:certificate.end]
    if (parts[2:] and not licensed_spelling(parts[2:], tail)) or (not parts[2:] and tail):
        return None
    return "direct_outside_first_inflection"


def _intrinsic_boundary(certificate, annotation, pair):
    """정확 원형·품사와 전체 합법 꼬리를 확인하고 내재 속성만 부가한다."""
    if (certificate.lexical_status != "eligible" or certificate.grammar_status != "eligible"
            or certificate.surface_status == "conflict" or certificate.authority_kind != "complete_scope"
            or not certificate.parts):
        return None
    parts = certificate.parts
    grammar = parse_parts(parts)
    if grammar.lexical_status != "eligible" or grammar.prefixed or grammar.derived:
        return None
    form, tag = parts[0]
    choices = []
    for fact in INTRINSIC_BOUNDARY_FACTS:
        if form != fact.canonical_owner or base_tag(tag) not in fact.owner_pos:
            continue
        donor = _source_atom(parts, 0, fact.boundary_offset - 1, "coda")
        onset = _source_atom(parts, 0, fact.boundary_offset, "onset")
        vowel = _source_atom(parts, 0, fact.boundary_offset, "vowel")
        if (fact.property != "intrinsic_palatalization" or donor is None or donor.jamo not in {"ᆮ", "ᇀ", "ᆴ"}
                or onset is None or onset.jamo != "ᄋ" or vowel is None or vowel.jamo != "ᅵ"):
            continue
        mapping = _intrinsic_target_mapping(certificate, annotation, pair, fact, donor, onset, vowel)
        if mapping is not None:
            choice = (parts, "intrinsic_palatalization", "intrinsic_lexical_property", "intrinsic_lexical",
                      donor, (onset, vowel), grammar, (certificate.start, certificate.end))
            choices.append((choice, fact, mapping))
    return choices[0] if len(choices) == 1 else None


def _lexical_fact_delegation(certificate, atoms, pair):
    """정확 어휘 성분 사실은 형식 이를 배제할 뿐 새 제29항을 허가하지 않는다."""
    if (certificate.surface_status != "verified" or certificate.lexical_status != "eligible"
            or certificate.grammar_status != "eligible"):
        return None
    parts = certificate.parts
    left, right = pair
    for fact in _LEXICAL_COMPONENT_FACTS:
        owners = []
        for index, (form, tag) in enumerate(parts):
            if form == fact.owner_form and base_tag(tag) in fact.owner_pos:
                owners.append(tuple((index, offset) for offset in range(len(form))))
            count = len(fact.component_spans)
            if index + count <= len(parts) and all(
                    parts[index + number][0] == fact.owner_form[begin:end]
                    and base_tag(parts[index + number][1]) in fact.component_pos[number]
                    for number, (begin, end) in enumerate(fact.component_spans)):
                owners.append(tuple((index + number, offset)
                    for number in range(count) for offset in range(len(parts[index + number][0]))))
        for owner in owners:
            for edge, _ in fact.component_spans[1:]:
                donor_index, donor_offset = owner[edge - 1]
                receiver_index, receiver_offset = owner[edge]
                donor = _source_atom(parts, donor_index, donor_offset, "coda")
                onset = _source_atom(parts, receiver_index, receiver_offset, "onset")
                vowel = _source_atom(parts, receiver_index, receiver_offset, "vowel")
                if (_actual_origin(atoms.get((left, "coda")), donor)
                        and _actual_origin(atoms.get((right, "onset")), onset)
                        and _actual_origin(atoms.get((right, "vowel")), vowel)):
                    return fact, donor, (onset, vowel)
    return None


def _lexical_receiver_class(annotation, left, right, units, segments):
    """원형 세부 정보가 없는 V+E 수신자는 형식 이가 아니라는 낮은 범주 사실만 남긴다."""
    previous, following = annotation.ending_at(right), annotation.starting_at(right)
    if previous is None or following is None or previous == following or previous.normalized_end != right:
        return None
    tags = tuple(following.tag.split("+"))
    if (len(tags) < 2 or base_tag(tags[0]) not in {"VV", "VA", "VX", "VCN"}
            or tags[1] not in ENDINGS or any(tag not in ENDINGS | PARTICLES for tag in tags[1:])
            or surface_proof_conflict(following)):
        return None
    for owner in (previous, following):
        scope = _certify_owned_scope(annotation, owner.normalized_start, units, segments, (),
            end_bound=owner.normalized_end, scope="component")
        if (scope.surface_status == "conflict" or "conflict" in scope.reason
                or scope.reason in {"whole_korean_word_unproven", "word_scope_barrier", "whole_word_ownership_unproven",
                                    "component_range_unproven", "word_start_unproven"}):
            return None
    return following.normalized_start, following.normalized_end


def certify_rule_boundaries(annotation, units, segments, pause_boundaries=(), *, reading_relations=None) -> tuple[RuleBoundary, ...]:
    """원문 내부 제15·17·29항 후보의 소유·문법·역할을 변화 전에 고정한다."""
    if annotation is None:
        return ()
    text, certificates, result = annotation.text, {}, []
    if not isinstance(text, str) or len(units) != len(text):
        return ()
    for right in range(1, len(text)):
        left = right - 1
        if units[left].syllable is None or units[right].syllable is None:
            continue
        donor = decompose_syllable(text[left], units[left].syllable.source_spans)
        recipient = decompose_syllable(text[right], units[right].syllable.source_spans)
        if not (recipient.onset == "ㅇ" or (
                donor.coda == "ㄷ" and recipient.onset == "ㅎ" and recipient.vowel in {"ㅣ", "ㅕ"})):
            continue
        start, end, whole_word = _syntax_scope(annotation, left, units, segments)
        if (start, end) not in certificates:
            certificates[(start, end)] = (certify_word(annotation, start, units, segments, ()) if whole_word else
                _certify_owned_scope(annotation, start, units, segments, (), end_bound=end, scope="component"))
        certificate = certificates[(start, end)]
        parts = certificate.parts
        common = dict(pair=(left, right), word_span=(certificate.start, certificate.end), parts=parts,
                      role=None, relation=None, source="analysis", status="unresolved",
                      applicability="unresolved", reason="boundary_role_unproven",
                      surface_proofs=certificate.surface_proofs,
                      grammar=parse_parts(parts), coda=donor.coda, onset=recipient.onset, vowel=recipient.vowel)
        if _has_phonological_barrier(units, left, right, segments, pause_boundaries):
            result.append(RuleBoundary(**{**common, "applicability": "blocked",
                                         "reason": "phonological_barrier"}))
            continue
        atoms, steps = _owned_atoms(certificate)
        choices, lexical_fact, intrinsic_fact, intrinsic_mapping = [], None, None, None
        if certificate.surface_status == "verified":
            for index in range(1, len(parts)):
                role, relation = _role(parts, index, annotation, right, certificate.surface_proofs)
                if role is None:
                    continue
                grammar_evidence = _boundary_grammar(certificate, parts, index, role, atoms, right, annotation)
                if grammar_evidence is None:
                    continue
                underlying_donor = _source_atom(parts, index - 1, len(parts[index - 1][0]) - 1, "coda")
                underlying_onset = _source_atom(parts, index, 0, "onset")
                underlying_vowel = _source_atom(parts, index, 0, "vowel")
                donor_owned = (_actual_origin(atoms.get((left, "coda")), underlying_donor)
                               if underlying_donor is not None else _actual_origin(
                                   atoms.get((left, "vowel")),
                                   _source_atom(parts, index - 1, len(parts[index - 1][0]) - 1, "vowel")))
                if (not donor_owned
                        or not _actual_origin(atoms.get((right, "onset")), underlying_onset)
                        or not _actual_origin(atoms.get((right, "vowel")), underlying_vowel)):
                    continue
                actual_vowel = atoms[(right, "vowel")]
                joint = len(actual_vowel[1]) > 1
                if joint and not ((role in {"formal_suffix_i", "formal_suffix_hi", "formal_ending_i"}
                                  or relation == "copular_attachment")
                        and any(rule == "맞춤법.36" and boundary == (index, index + 1)
                                and index + 1 < len(parts) and parts[index + 1][1] in ENDINGS
                                for rule, boundary, _ in steps)):
                    continue
                grammar, attachment_span, source = grammar_evidence
                if relation == "copular_attachment":
                    source = "copular_grammar"
                elif role == "formal_ending_i":
                    source = "ending_grammar"
                choices.append((parts, role, relation, source, underlying_donor,
                                (underlying_onset, *actual_vowel[1]), grammar, attachment_span))
            structural = _structural_boundary(certificate, annotation, (left, right))
            if structural is not None and not choices:
                choices.append(structural)
            if not choices:
                canonical = _canonical_boundary(certificate, atoms, steps, (left, right))
                if canonical is not None:
                    choice, lexical_fact = canonical
                    choices.append(choice)
        intrinsic = _intrinsic_boundary(certificate, annotation, (left, right))
        if intrinsic is not None:
            choice, intrinsic_fact, intrinsic_mapping = intrinsic
            choices.append(choice)
        if len(choices) > 1:
            result.append(RuleBoundary(**{**common, "reason": "boundary_role_conflict",
                "intrinsic_fact": intrinsic_fact, "canonical_owner_occurrence": 0 if intrinsic_fact else None,
                "intrinsic_mapping": intrinsic_mapping}))
            continue
        if not choices:
            lexical = _lexical_fact_delegation(certificate, atoms, (left, right))
            if lexical is not None:
                fact, original_donor, original_recipient = lexical
                result.append(RuleBoundary(**{**common, "role": "lexical_component",
                    "relation": "lexical_component_sequence", "source": "lexical_component_fact:" + fact.id,
                    "status": "verified", "applicability": "not_required", "reason": "lexical_component_excludes_formal_i",
                    "donor_origin": original_donor, "recipient_origins": original_recipient, "lexical_fact": fact,
                    "attachment_span": (certificate.start, certificate.end)}))
                continue
            receiver_class = _lexical_receiver_class(annotation, left, right, units, segments)
            if receiver_class is not None:
                result.append(RuleBoundary(**{**common, "source": "existing_lexical_receiver_class",
                    "status": "excluded", "applicability": "not_required",
                    "reason": "lexical_receiver_excludes_standalone_formal_i", "grammar": None,
                    "attachment_span": receiver_class}))
                continue
            # 새 형식·합성 역할이 없다는 사실은 이미 증명한 독립 수신자를 부정하지 않는다.
            existing = certify_component_recipient(annotation, left, right, units, segments, ())
            if (certificate.surface_status != "conflict" and "conflict" not in certificate.reason
                    and lexical_liaison_projection(existing) == "eligible"):
                result.append(RuleBoundary(**{**common, "source": "existing_lexical_recipient",
                    "status": "verified", "applicability": "not_required",
                    "reason": "prior_independent_lexical_recipient",
                    "grammar": parse_parts(existing.parts), "attachment_span": (existing.start, existing.end)}))
                continue
            if certificate.surface_status == "conflict":
                common["reason"] = "surface_evidence_conflict"
            elif certificate.lexical_status != "eligible" or certificate.grammar_status != "eligible":
                common["reason"] = certificate.reason
                if certificate.grammar_status == "excluded":
                    common.update(status="excluded", applicability="blocked")
            elif certificate.surface_status != "verified":
                common["reason"] = "whole_surface_evidence_unavailable"
            elif any(base_tag(tag) in {"VV", "VA", "VX", "MAG"} for _, tag in parts):
                common["reason"] = "unresolved_missing_lexical_structure"
            # 이미 명시된 실질 경계가 없는 일반 어휘 연음 후보는 기존 소비자가 맡는다.
            following = annotation.starting_at(right)
            first = (following.morphemes or ((following.form, following.tag),))[0] if following else None
            potential_suffix = bool(first is not None and base_tag(first[1]) in SUFFIXES
                                    and first[0] in {"이", "히", "어치"})
            if (donor.coda in {"ㄷ", "ㅌ", "ㄾ"} and recipient.vowel in {"ㅣ", "ㅕ"}
                    or potential_suffix):
                result.append(RuleBoundary(**common))
            continue
        own_parts, role, relation, source, original_donor, original_recipient, grammar, attachment_span = choices[0]
        common.update(parts=own_parts, role=role, relation=relation, source=source,
                      donor_origin=original_donor, recipient_origins=original_recipient,
                      grammar=grammar, attachment_span=attachment_span,
                      lexical_fact=lexical_fact,
                      intrinsic_fact=intrinsic_fact,
                      canonical_owner_occurrence=0 if intrinsic_fact else None,
                      intrinsic_mapping=intrinsic_mapping,
                      status="verified", applicability="not_required", reason="sound_condition_absent")
        if (reading_relations or {}).get((left, right)) is not None:
            result.append(RuleBoundary(**{**common, "status": "unresolved", "applicability": "unresolved",
                                         "reason": "explicit_reading_relation_conflict"}))
            continue
        if role == "formal_particle":
            # 기존 제16항의 정확한 이름 소유를 일반 제17항보다 먼저 존중한다.
            from .morphology import _letter_name_onset
            if _letter_name_onset(annotation, left, right) is not None:
                result.append(RuleBoundary(**{**common, "source": "existing_letter_name_policy",
                    "reason": "prior_exact_letter_name_donor"}))
                continue
        if role == "semantic_suffix_eochi":
            common["article"] = "15"
            if recipient.onset == "ㅇ" and recipient.vowel not in _N_VOWELS and donor.coda not in {None, "ㅇ"}:
                transition = CODA_TRANSITIONS.get(donor.coda)
                common.update(applicability="eligible", reason="semantic_suffix_recipient",
                              moved_onset=transition.target if transition else donor.coda)
        elif role == "intrinsic_palatalization":
            # 내재 어휘 속성을 형식 접미사나 제29항 합성 권한으로 바꾸지 않는다.
            common["article"] = "17"
            if recipient.onset == "ㅇ" and recipient.vowel == "ㅣ" and donor.coda in {"ㄷ", "ㅌ", "ㄾ"}:
                common.update(applicability="eligible", reason="canonical_owner_intrinsic_palatalization",
                              remainder="ㄹ" if donor.coda == "ㄾ" else None,
                              moved_onset="ㅈ" if donor.coda == "ㄷ" else "ㅊ")
        elif role in {"formal_particle", "formal_suffix_i", "formal_suffix_hi", "formal_ending_i"}:
            common["article"] = "17"
            if (donor.coda in {"ㄷ", "ㅌ", "ㄾ"} and (
                    recipient.onset == "ㅇ" and role != "formal_suffix_hi"
                    or donor.coda == "ㄷ" and recipient.onset == "ㅎ" and role == "formal_suffix_hi")):
                common.update(applicability="eligible", reason="underlying_formal_i_hi",
                              remainder="ㄹ" if donor.coda == "ㄾ" else None,
                              moved_onset="ㅈ" if donor.coda == "ㄷ" and role != "formal_suffix_hi" else "ㅊ")
        else:
            common["article"] = "29"
            if donor.coda is not None and recipient.onset == "ㅇ" and recipient.vowel in _N_VOWELS:
                # 기존의 정확 비첨가 소유 정책을 복제하지 않고 그대로 소비한다.
                from .morphology import _is_verified_non_n_insertion_boundary
                if (_is_verified_non_n_insertion_boundary(units, left, right, annotation, segments)
                        or _owned_non_n_fact(certificate, text, left, right)):
                    transition = CODA_TRANSITIONS.get(donor.coda)
                    common.update(article="15", applicability="eligible", reason="exact_non_n_insertion",
                                  moved_onset=transition.target if transition else donor.coda)
                else:
                    common.update(applicability="eligible", reason="verified_lexical_composition",
                                  remainder=donor.coda, moved_onset="ㄴ")
        result.append(RuleBoundary(**common))
    return tuple(result)


def apply_rule_boundaries(boundaries, units, rewrites) -> tuple[BoundaryEvent, ...]:
    """고정한 권한만 한 번 실행하고 일반 받침·비음화·경음화에 넘긴다."""
    grouped = {}
    for boundary in boundaries:
        grouped.setdefault(boundary.pair, []).append(boundary)
    events = []
    rules = {"15": "ko.liaison.lexical", "17": "ko.palatalization", "29": "ko.n_insertion.compound"}
    for pair, records in grouped.items():
        boundary = records[0]
        if any(record != boundary for record in records[1:]):
            events.append(BoundaryEvent(boundary, "unresolved", "unresolved", "boundary_role_conflict", False))
            continue
        status, applicability, reason, changed, rule_ids = boundary.status, boundary.applicability, boundary.reason, False, ()
        if status == "verified" and applicability == "eligible":
            left, right = pair
            donor, recipient = units[left].syllable, units[right].syllable
            if (donor is None or recipient is None or donor.coda != boundary.coda
                    or recipient.onset != boundary.onset or recipient.vowel != boundary.vowel):
                status, applicability, reason = "unresolved", "unresolved", "original_pair_changed_before_execution"
            else:
                before = _trace_before(rewrites, units, left, right)
                units[left].syllable = donor.changed(coda=boundary.remainder)
                units[right].syllable = recipient.changed(onset=boundary.moved_onset)
                rule_id = rules[boundary.article]
                _record(rewrites, units, left, right, before, rule_id)
                changed, rule_ids = True, (rule_id,)
        events.append(BoundaryEvent(boundary, status, applicability, reason, changed, rule_ids))
    return tuple(events)
