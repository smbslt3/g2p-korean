# SPDX-License-Identifier: MIT
"""원문 소유로 고정한 형식 부착 결정과 물리 경계 이벤트를 실행한다."""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from ..model import Handler
from ._shared import _has_phonological_barrier, _pair_text, _record, _trace_before
from .ending_ownership import verified_morpheme_surfaces, verified_source_owners
from .hangul import decompose_syllable, is_modern_syllable
from .rules import HIEUH_REMAINDER, LIAISON_CLUSTER
from .word_roles import _normalized_owned_parts
from .surface_proof import certified_formal_recipient, surface_proof_conflict, verified_token_surface

PARTICLES = frozenset({"JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC"})
ENDINGS = frozenset({"EP", "EF", "EC", "ETM", "ETN"})
SUFFIXES = frozenset({"XSN", "XSV", "XSA", "XSM"})
FORMAL = PARTICLES | ENDINGS | SUFFIXES | {"VCP"}
BASES = frozenset({"NNG", "NNP", "NNB", "NNBC", "NP", "NR", "VV", "VA", "VX",
                   "MAG", "MAJ", "MM", "IC", "XR", "VCN"})


def _base(tag):
    """규칙·불규칙 표지는 원래 품사를 바꾸지 않는다."""
    return tag[:-2] if tag.endswith(("-I", "-R")) else tag


@dataclass(frozen=True, slots=True)
class FormalDecision:
    """소리 변화 이전의 표면·품사·자모 소유를 보관한 불변 결정이다."""
    pair: tuple[int, int]
    kind: str
    role: str | None
    status: str
    reason: str
    applicability: str
    coda: str | None = None
    onset: str | None = None
    vowel: str | None = None
    remainder: str | None = None
    moved_onset: str | None = None
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class FormalEvent:
    """하나의 실제 pair를 정확히 한 번 소비한 실행 결과다."""
    decision: FormalDecision
    status: str
    reason: str
    applicability: str
    sound_effect: str
    rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Word:
    start: int
    end: int
    parts: tuple[tuple[str, str], ...]
    owners: dict
    proofs: dict


def _observed_parts(token):
    """기존 검증을 재사용하며 융합 뒤 정확한 성분의 품사를 제한하지 않는다."""
    proof = verified_token_surface(token)
    if proof is not None:
        return proof.parts
    if surface_proof_conflict(token):
        return None
    own = _normalized_owned_parts(token)
    if own is not None:
        return own
    if verified_morpheme_surfaces(token) is not None:
        return token.morphemes
    parts = token.morphemes
    if not parts or tuple(tag for _, tag in parts) != tuple(token.tag.split("+")):
        return None
    for index, (_, tag) in enumerate(parts[:-1]):
        if _base(tag) not in {"VV", "VA", "VX", "XSV", "XSA", "VCP"} or parts[index+1][1] not in ENDINGS:
            continue
        tail = index + 1
        while tail < len(parts) and parts[tail][1] in ENDINGS:
            tail += 1
        prefix = "".join(form for form, _ in parts[:index])
        suffix = "".join(form for form, _ in parts[tail:])
        if (token.form.startswith(prefix) and token.form.endswith(suffix)
                and len(token.form) > len(prefix) + len(suffix)):
            return parts
    return None


def _word(annotation, position, text, units, segments, pauses):
    """관측한 전체 원문 단위와 필요한 직접 자모 소유를 함께 확인한다."""
    start = position
    while start and is_modern_syllable(text[start-1]):
        start -= 1
    end = position + 1
    while end < len(text) and is_modern_syllable(text[end]):
        end += 1
    parts, owners, proofs, cursor = [], {}, {}, start
    for offset in range(start, end):
        unit = units[offset]
        if unit.handler is not Handler.KOREAN or unit.syllable is None:
            return None
        # 생성된 발음이나 다른 원문의 annotation은 형식 성분 근거가 아니다.
        if segments[unit.segment_index].handler is not Handler.KOREAN:
            return None
        if unit.source_spans and unicodedata.normalize("NFC", "".join(
                span.surface for span in unit.source_spans)) != text[offset]:
            return None
        if offset > start and _has_phonological_barrier(units, offset-1, offset, segments, pauses):
            return None
    while cursor < end:
        token = annotation.starting_at(cursor)
        if (token is None or not cursor < token.normalized_end <= end
                or token.form != text[cursor:token.normalized_end]
                or any(annotation.covering(i) != token for i in range(cursor, token.normalized_end))):
            return None
        own = _observed_parts(token)
        if own is None:
            return None
        parts.extend(own)
        owners.update(verified_source_owners(token))
        proof = verified_token_surface(token)
        if proof is not None:
            proofs[token.normalized_start] = proof
        cursor = token.normalized_end
    return _Word(start, end, tuple(parts), owners, proofs)


def decide_formal_attachments(text, units, segments, annotation, relations, pauses, *, special_donors=()):
    """제공된 정확 분석과 명시 ordinary pair를 원문에서 한 번 판정한다."""
    decisions = {}
    for pair, relation in sorted(relations.items()):
        if relation != "ordinary_liaison":
            continue
        left, right = pair
        if annotation is None:
            decisions[pair] = FormalDecision(pair, "unknown", None, "unknown",
                "grammatical_evidence_unavailable", "unknown")
            continue
        following = annotation.starting_at(right)
        first_parts = following.morphemes if following is not None else ()
        declared_tags = tuple(following.tag.split("+")) if following is not None else ()
        first_roles = (declared_tags[0], first_parts[0][1]) if first_parts else ()
        formal_involvement = any(tag in FORMAL or tag.startswith(("J", "E"))
            or tag.startswith("X") and tag not in {"XPN", "XR"} for tag in first_roles)
        if (first_parts and formal_involvement
                and tuple(tag for _, tag in first_parts) != declared_tags):
            # 성분 태그를 먼저 골라 상위 선언과의 모순을 지우지 않는다.
            # 첫 수신자가 어휘 역할이면 기존 어휘 증명·불적격 판정에 맡긴다.
            decisions[pair] = FormalDecision(pair, "unknown", declared_tags[0], "unknown",
                "morphological_identity_conflict", "unknown")
            continue
        first_tag = (first_parts[0][1] if first_parts else following.tag.split("+")[0]) if following else None
        if first_tag is None or _base(first_tag) not in FORMAL:
            # 알 수 없는 형식 태그를 어휘 역할로 추정하지 않는다.
            suspicious = first_tag and (first_tag.startswith(("J", "E"))
                or first_tag.startswith("X") and first_tag not in {"XPN", "XR"})
            if suspicious:
                decisions[pair] = FormalDecision(pair, "unknown", first_tag, "unknown",
                    "formal_role_unsupported", "unknown")
            continue
        def unknown(reason):
            return FormalDecision(pair, "formal", first_tag, "unknown", reason, "unknown")
        if _has_phonological_barrier(units, left, right, segments, pauses):
            decisions[pair] = FormalDecision(pair, "formal", first_tag, "blocked",
                "phonological_barrier", "blocked")
            continue
        previous = _word(annotation, left, text, units, segments, pauses)
        following_word = _word(annotation, right, text, units, segments, pauses)
        if previous is None or following_word is None or previous.end != left+1 or following_word.start != right:
            decisions[pair] = unknown("whole_source_ownership_unresolved")
            continue
        host_parts = tuple(part for part in previous.parts if part[1] != "XPN")
        anchored = bool(host_parts and _base(host_parts[0][1]) in BASES)
        if (not anchored and first_tag in ENDINGS and host_parts
                and host_parts[0] == ("이", "VCP")):
            # 어미의 실제 계사 어간을 완성 명사 숙주 조건으로 거부하지 않는다.
            anchored = True
        if not anchored:
            # 앞서 증명한 실제 연결만 공유한다. 미확인 J/E 조각을 숙주로 만들지 않는다.
            anchored = any(old_pair[1] == previous.start and old.kind == "formal"
                and old.status == "selected" for old_pair, old in decisions.items())
        if not anchored:
            decisions[pair] = unknown("host_attachment_unproven")
            continue
        if text[previous.start:previous.end] in special_donors:
            decisions[pair] = unknown("letter_name_relation_not_frozen")
            continue
        donor = decompose_syllable(text[left], units[left].syllable.source_spans)
        recipient = decompose_syllable(text[right], units[right].syllable.source_spans)
        if donor.coda is not None and previous.owners.get((left, "coda")) is None:
            decisions[pair] = unknown("donor_ownership_unresolved")
            continue
        first_form, first_tag = following_word.parts[0]
        first_category = _base(first_tag)
        expected_owner = (first_form, first_tag)
        recipient_owners = [following_word.owners.get((right, role)) for role in ("onset", "vowel")]
        singleton_recipient = all(owner is not None and (owner.form, owner.tag) == expected_owner
                                  for owner in recipient_owners)
        chain_recipient = certified_formal_recipient(
            following_word.proofs.get(right), right, chain_parts=following_word.parts)
        if not singleton_recipient and not chain_recipient:
            decisions[pair] = unknown("recipient_ownership_unresolved")
            continue
        coda, onset, vowel = donor.coda, recipient.onset, recipient.vowel
        common = dict(pair=pair, kind="formal", role=first_tag, status="selected",
                      coda=coda, onset=onset, vowel=vowel)
        if coda is None:
            decisions[pair] = FormalDecision(**common, reason="no_original_coda", applicability="not_required")
            continue
        # ㄷ+접미사 히는 모음 초성 부착과 다른 제17항 붙임이다.
        if coda == "ㄷ" and onset == "ㅎ" and vowel == "ㅣ" and first_category in SUFFIXES and first_form == "히":
            decisions[pair] = FormalDecision(**common, reason="formal_palatalization_hi",
                applicability="eligible", moved_onset="ㅊ", rule_id="ko.palatalization")
            continue
        if onset != "ㅇ":
            decisions[pair] = FormalDecision(**common, reason="no_vowel_attachment", applicability="not_required")
            continue
        if (not singleton_recipient and chain_recipient and coda in {"ㄷ", "ㅌ", "ㄾ"}
                and first_category in SUFFIXES and first_form == "이"):
            # 제17항의 이 접미사 문맥을 일반 연음으로 우회해 다른 소리를 만들지 않는다.
            decisions[pair] = unknown("palatalization_chain_not_frozen")
            continue
        if coda in HIEUH_REMAINDER:
            if first_category not in ENDINGS | SUFFIXES:
                decisions[pair] = unknown("hieuh_relation_not_frozen")
            else:
                decisions[pair] = FormalDecision(**common, reason="formal_hieuh_deletion",
                    applicability="eligible", moved_onset=HIEUH_REMAINDER[coda], rule_id="ko.hieuh.vowel")
            continue
        if (singleton_recipient and vowel == "ㅣ" and first_category in PARTICLES | SUFFIXES | {"VCP"}
                and coda in {"ㄷ", "ㅌ", "ㄾ"}):
            decisions[pair] = FormalDecision(**common, reason="formal_palatalization_i",
                applicability="eligible", remainder="ㄹ" if coda == "ㄾ" else None,
                moved_onset="ㅈ" if coda == "ㄷ" else "ㅊ", rule_id="ko.palatalization")
            continue
        if coda == "ㅇ":
            decisions[pair] = FormalDecision(**common, reason="immovable_original_coda", applicability="not_required")
            continue
        if coda in LIAISON_CLUSTER:
            remainder, moved = LIAISON_CLUSTER[coda]
            decisions[pair] = FormalDecision(**common, reason="formal_original_cluster", applicability="eligible",
                remainder=remainder, moved_onset=moved, rule_id="ko.liaison.cluster")
        else:
            decisions[pair] = FormalDecision(**common, reason="formal_original_single", applicability="eligible",
                moved_onset=coda, rule_id="ko.liaison.single")
    return decisions


def apply_formal_attachments(decisions, units, rewrites):
    """중복 요청 수와 무관하게 각 물리 pair의 불변 결정을 한 번 소비한다."""
    events = {}
    for pair, decision in decisions.items():
        left, right = pair
        status, reason, applicability = decision.status, decision.reason, decision.applicability
        changed, rules = "unchanged", ()
        if status == "selected" and applicability == "eligible" and decision.rule_id:
            donor, recipient = units[left].syllable, units[right].syllable
            if (donor.coda != decision.coda or recipient.onset != decision.onset
                    or recipient.vowel != decision.vowel):
                status, reason, applicability = "unknown", "original_pair_changed_before_execution", "unknown"
            else:
                before = _trace_before(rewrites, units, left, right)
                units[left].syllable = donor.changed(coda=decision.remainder)
                if decision.moved_onset is not None:
                    units[right].syllable = recipient.changed(onset=decision.moved_onset)
                _record(rewrites, units, left, right, before, decision.rule_id)
                changed, rules = "changed", (decision.rule_id,)
        events[pair] = FormalEvent(decision, status, reason, applicability, changed, rules)
    return events
