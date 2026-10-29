"""명시 조건을 물리 경계에 결합하고 실행 근거를 수집한다."""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..errors import InputValidationError
from ..model import Handler
from ..reading_conditions import ReadingBoundaryExecution, _MappedReadingBoundary
from ._shared import _has_hard_boundary, _pair_text
from .hangul import is_modern_syllable


@dataclass(slots=True)
class _ReadingPlan:
    """한 실행 안에서만 사용하는 관계 계획이다."""

    relations: dict[tuple[int, int], str]
    pauses: tuple[int, ...]
    executions: list[ReadingBoundaryExecution]
    before: dict[tuple[int, int], str]
    vowel_pairs: frozenset[tuple[int, int]]


def _word_gap(text: str, offset: int) -> tuple[int, int] | None:
    left, right = offset - 1, offset
    while left >= 0 and text[left] == " ":
        left -= 1
    while right < len(text) and text[right] == " ":
        right += 1
    if (left >= 0 and right < len(text) and right > left + 1
            and is_modern_syllable(text[left]) and is_modern_syllable(text[right])):
        return left, right
    return None


def plan_reading_conditions(units, segments, requests, legacy_pauses) -> _ReadingPlan:
    """소리를 바꾸기 전에 충돌과 경계 우선순위를 확정한다."""

    text = "".join(unit.text for unit in units)
    canonical = {}
    located = []
    for request in requests:
        pair = _word_gap(text, request.output_offset)
        if pair is None and request.relation != "pause":
            raise InputValidationError("비휴지 읽기 조건은 한글 단어 사이 ASCII 공백 경계여야 합니다.")
        key = ("gap", pair) if pair is not None else ("offset", request.output_offset)
        if key in canonical and canonical[key] != request.relation:
            raise InputValidationError("같은 물리 경계에 서로 다른 읽기 조건을 지정했습니다.")
        canonical[key] = request.relation
        if request.relation != "pause" and any(pair[0] < pause <= pair[1] for pause in legacy_pauses):
            raise InputValidationError("기존 휴지 경계와 비휴지 읽기 조건이 충돌합니다.")
        trace_pair = pair
        if pair is None and request.relation == "pause" and 0 < request.output_offset < len(text):
            left, right = request.output_offset - 1, request.output_offset
            if is_modern_syllable(text[left]) and is_modern_syllable(text[right]):
                trace_pair = (left, right)
        located.append((request, trace_pair))

    relations, executions, before, vowel_pairs = {}, [], {}, set()
    pauses = set(legacy_pauses)
    for request, pair in located:
        if request.relation == "pause":
            pauses.add(request.output_offset)
        status, reason = "selected", "caller_selected_recipe"
        applicability = "not_required" if request.relation == "pause" else "pending"
        sound_effect = "barrier" if request.relation == "pause" else "pending"
        if pair is not None:
            left, right = pair
            if _has_hard_boundary(units[left].segment_index, units[right].segment_index, segments):
                status, reason = "blocked", "hard_boundary"
            elif any(unit.handler is not Handler.KOREAN for unit in units[left:right + 1]):
                status, reason = "blocked", "protected_or_non_korean"
            elif units[left].syllable is None or units[right].syllable is None:
                status, reason = "blocked", "protected_or_non_korean"
            elif any(
                segments[units[index].segment_index].handler is Handler.ENGLISH
                and segments[units[index].segment_index].rule_id != "english.conventional.v1"
                for index in (left, right)
            ):
                status, reason = "blocked", "letter_name_word_relation_unsupported"
            if status == "selected":
                before[pair] = _pair_text(units, left, right)
                token, following = units[left].syllable, units[right].syllable
                if token.coda is not None and following.onset == "ㅇ":
                    vowel_pairs.add(pair)
                if request.relation != "pause":
                    relations[pair] = request.relation
        if status == "blocked":
            applicability, sound_effect = "blocked", "unchanged"
        executions.append(ReadingBoundaryExecution(
            request.source_offset, request.nfc_offset, request.output_offset,
            request.relation, pair, status, reason, applicability, sound_effect,
        ))
    return _ReadingPlan(relations, tuple(sorted(pauses)), executions, before, frozenset(vowel_pairs))


def finish_reading_conditions(plan, units, rewrites, annotation, segments, *, formal_events=None) -> tuple[ReadingBoundaryExecution, ...]:
    """동일 실행의 분석과 rewrite로 실제 적용 범위를 정직하게 기록한다."""

    from .morphology import _tag_has_prefix
    from .morphology import _N_INSERTION_VOWELS
    from .word_roles import (certify_word, lexical_liaison_projection,
                             word_n_insertion_projection)

    results = []
    for entry in plan.executions:
        pair = entry.output_pair
        if entry.status == "blocked" or pair is None or entry.relation == "pause":
            results.append(entry)
            continue
        left, right = pair
        if pair in (formal_events or {}):
            event = formal_events[pair]
            results.append(replace(entry, status=event.status, reason=event.reason,
                applicability=event.applicability,
                sound_effect=event.sound_effect, rule_ids=event.rule_ids))
            continue
        status, reason, applicability = "selected", "caller_selected_recipe", "not_required"
        if pair in plan.vowel_pairs:
            previous = annotation.ending_at(left + 1) if annotation is not None else None
            following = annotation.starting_at(right) if annotation is not None else None
            if previous is None or following is None:
                status, reason, applicability = "unknown", "grammatical_evidence_unavailable", "unknown"
            else:
                certificate = certify_word(annotation, right, units, segments, plan.pauses)
                evidence = (lexical_liaison_projection(certificate)
                            if entry.relation == "ordinary_liaison"
                            else word_n_insertion_projection(certificate))
                if evidence == "unresolved":
                    status, reason, applicability = "unknown", certificate.reason, "unknown"
                elif evidence == "excluded":
                    reason, applicability = "word_grammar_or_category_excluded", "ineligible"
                elif entry.relation == "ordinary_liaison":
                    applicability = "eligible"
                else:
                    # 모음·왼쪽 수사 제한은 문법 증명과 별도의 음운 소비 조건이다.
                    token = units[right].syllable
                    applicability = "eligible" if (
                        token.vowel in _N_INSERTION_VOWELS
                        and not _tag_has_prefix(previous.tag, "NR")
                    ) else "ineligible"

        rule_ids = getattr(rewrites, "pair_rules", {}).get(pair, ())
        # 끝 음절의 나중 변화가 아니라 요청한 경계에 실제 귀속된 실행만 보고한다.
        effect = "changed" if rule_ids else "unchanged"
        results.append(replace(entry, status=status, reason=reason, applicability=applicability,
                               sound_effect=effect, rule_ids=tuple(rule_ids)))
    return tuple(results)
