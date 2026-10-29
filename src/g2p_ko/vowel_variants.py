"""정준 표기에서 확인한 제5항 지역 모음 변이를 별도 결과로 제공한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from .alignment import G2PAlignedResult, AlignmentRelation
from .analyzer import KiwiAnalyzer
from .korean.hangul import decompose_syllable, is_modern_syllable
from .model import AnalysisToken, SourceSpan
from .unicode import normalize_nfc

PROFILE_ID = "standard_vowels_v1"
SCOPE = "standard_rule5_local_vowel_variants_only"


@dataclass(frozen=True, slots=True)
class VowelAlternative:
    """다른 음운 성분을 보존한 한 음절 대안이다."""

    text: str
    vowel: str

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "vowel": self.vowel}


@dataclass(frozen=True, slots=True)
class VowelVariantSlot:
    """검증한 단일 출력 음절과 실제 원문 범위의 선택 슬롯이다."""

    slot_id: int
    source_span: SourceSpan
    output_start: int
    output_end: int
    original: str
    base: str
    alternatives: tuple[VowelAlternative, ...]
    rule_id: str
    condition: str
    role: str
    owner_span: SourceSpan
    analyzer_tag: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id, "source_span": self.source_span.to_dict(),
            "output_start": self.output_start, "output_end": self.output_end,
            "original": self.original, "base": self.base,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "rule_id": self.rule_id, "condition": self.condition, "role": self.role,
            "owner_span": self.owner_span.to_dict(), "analyzer_tag": self.analyzer_tag,
        }


@dataclass(frozen=True, slots=True)
class VowelVariantDecision:
    """슬롯 생성 제외와 미확정도 원문 단위로 기록한다."""

    source_span: SourceSpan
    original: str
    state: str
    reason: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"source_span": self.source_span.to_dict(), "original": self.original,
                "state": self.state, "reason": self.reason, "rule_id": self.rule_id}


@dataclass(frozen=True, slots=True)
class G2PVowelVariantResult:
    """기존 변환·정렬과 유한 슬롯을 묶으며 재변환 없이 선택을 적용한다."""

    aligned: G2PAlignedResult
    slots: tuple[VowelVariantSlot, ...]
    decisions: tuple[VowelVariantDecision, ...]
    auxiliary_analysis_calls: int
    auxiliary_analysis_status: str
    profile_id: str = PROFILE_ID

    @property
    def coverage_status(self) -> str:
        return "partial_unknown" if any(x.state == "unknown" for x in self.decisions) else "scoped_supported"

    def render(self, selections: Mapping[int, int] | None = None) -> str:
        """slot_id에서 대안 인덱스로 가는 명시적 선택만 적용한다."""

        if selections is None:
            selections = {}
        if not isinstance(selections, Mapping):
            raise ValueError("선택은 slot_id와 대안 인덱스의 mapping이어야 합니다.")
        by_id = {slot.slot_id: slot for slot in self.slots}
        if len(by_id) != len(self.slots):
            raise ValueError("중복 슬롯 ID입니다.")
        surface = self.aligned.result.surface_pronunciation
        replacements: list[tuple[int, int, str]] = []
        for slot_id, alternative_index in selections.items():
            if type(slot_id) is not int or type(alternative_index) is not int:
                raise ValueError("선택 좌표와 인덱스는 불리언이 아닌 정수여야 합니다.")
            slot = by_id.get(slot_id)
            if slot is None or not 0 <= alternative_index < len(slot.alternatives):
                raise ValueError("지원하지 않는 슬롯 또는 대안 인덱스입니다.")
            if not 0 <= slot.output_start < slot.output_end <= len(surface):
                raise ValueError("슬롯 출력 범위가 올바르지 않습니다.")
            if surface[slot.output_start:slot.output_end] != slot.base:
                raise ValueError("슬롯이 기본 변환과 일치하지 않습니다.")
            replacements.append((slot.output_start, slot.output_end, slot.alternatives[alternative_index].text))
        replacements.sort()
        parts: list[str] = []
        cursor = 0
        for start, end, text in replacements:
            if start < cursor:
                raise ValueError("겹치는 슬롯은 선택할 수 없습니다.")
            parts.extend((surface[cursor:start], text))
            cursor = end
        parts.append(surface[cursor:])
        return "".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "g2p_local_vowel_variants.v1", "profile_id": self.profile_id,
            "input_contract": "canonical_written", "scope": SCOPE,
            "coverage_status": self.coverage_status,
            "complete_semantics": "base_pipeline_only",
            "aligned": {"result": self.aligned.result.to_dict(), "alignment": self.aligned.alignment.to_dict()},
            "slots": [slot.to_dict() for slot in self.slots],
            "decisions": [item.to_dict() for item in self.decisions],
            "analysis_provenance": {
                "auxiliary_provider": "KiwiAnalyzer.analyze",
                "auxiliary_coordinates": "nfc_raw_source_before_english_expansion",
                "auxiliary_analysis_calls": self.auxiliary_analysis_calls,
                "auxiliary_analysis_status": self.auxiliary_analysis_status,
                "base_pipeline_analyzer_calls": None,
                "base_pipeline_analyzer_calls_status": "not_instrumented",
                "cache_scope": "one_variant_result_construction",
            },
            "unsupported_scope": ["colloquial_reconstruction", "phrase_n_insertion",
                                  "loanword_usage", "vowel_length", "global_variant_enumeration"],
        }


def _validated_tokens(text: str) -> tuple[AnalysisToken, ...]:
    """보조 분석의 좌표와 원문 소유권을 별도로 검증한다."""

    tokens = tuple(KiwiAnalyzer().analyze(text))
    previous_end = 0
    for token in tokens:
        if not isinstance(token, AnalysisToken):
            raise ValueError("분석 token 형식이 다릅니다.")
        start, end = token.normalized_start, token.normalized_end
        if (type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or start < previous_end or
                token.form != text[start:end] or not isinstance(token.tag, str) or not token.tag):
            raise ValueError("분석 token의 원문 대응을 확인하지 못했습니다.")
        previous_end = end
    return tokens



@dataclass(frozen=True, slots=True)
class _VowelOwner:
    """원문 단어 안에서 검증한 역할과 어휘 전체 범위다."""

    form: str
    tag: str
    normalized_start: int
    normalized_end: int
    lexical_start: int | None = None
    lexical_end: int | None = None


def _word_owners(text: str, tokens: tuple[AnalysisToken, ...]) -> dict[int, _VowelOwner]:
    """정확한 표기 결합과 명사·조사 순서로만 단어 소유를 확정한다."""

    # 성분 좌표는 일치하는 전체 문자열을 왼쪽부터 한 번씩 소비하여 만든다.
    components: dict[int, tuple[int, tuple[_VowelOwner, ...] | None]] = {}
    for token in tokens:
        parts = token.morphemes or ((token.form, token.tag),)
        tags = tuple(token.tag.split("+"))
        valid = (tuple(tag for _, tag in parts) == tags and
                 "".join(form for form, _ in parts) == token.form and
                 all(form and tag and "+" not in tag for form, tag in parts))
        cursor = token.normalized_start
        expanded: list[_VowelOwner] = []
        if valid:
            for form, tag in parts:
                end = cursor + len(form)
                if text[cursor:end] != form:
                    valid = False
                    break
                expanded.append(_VowelOwner(form, tag, cursor, end))
                cursor = end
            valid = valid and cursor == token.normalized_end
        components[token.normalized_start] = (token.normalized_end, tuple(expanded) if valid else None)
    owners: dict[int, _VowelOwner] = {}
    particles = {"JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC"}
    lexical = {"NNG", "NNP", "NP", "NR", "MAG", "MM"}
    # 공백·인용부호 등 실제 원문 경계를 넘지 않고, 전체 덮기가 실패하면 보류한다.
    for word in re.finditer("[가-힣]+", text):
        cursor = word.start()
        parts: list[_VowelOwner] = []
        while cursor < word.end():
            item = components.get(cursor)
            if item is None or item[0] > word.end() or item[1] is None:
                break
            parts.extend(item[1])
            cursor = item[0]
        if cursor != word.end() or not parts:
            continue
        split = next((i for i, part in enumerate(parts) if part.tag in particles), len(parts))
        head, tail = parts[:split], parts[split:]
        if not head or any(part.tag not in particles for part in tail):
            continue
        if len(head) == 1:
            if head[0].tag not in lexical:
                # 비명사 단일 역할의 ㅖ 판정은 기존 범위를 보존하되 의는 승인하지 않는다.
                if tail or "+" in head[0].tag:
                    continue
                owner = head[0]
                for index in range(owner.normalized_start, owner.normalized_end):
                    owners[index] = owner
                continue
        else:
            # 인접만으로 부사·관형사·대명사를 복합어로 만들지 않는다.
            # 접두사* + 명사+ + 접미사*의 정확한 표기 결합만 어휘 부분으로 인정한다.
            state = "prefix"
            noun_seen = False
            valid = True
            for part in head:
                if part.tag == "XPN" and state == "prefix":
                    continue
                if part.tag in {"NNG", "NNP"} and state != "suffix":
                    state, noun_seen = "noun", True
                elif part.tag == "XSN" and noun_seen:
                    state = "suffix"
                else:
                    valid = False
                    break
            if not valid or not noun_seen:
                continue
        lexical_start, lexical_end = head[0].normalized_start, head[-1].normalized_end
        for part in parts:
            is_lexical = part.normalized_start < lexical_end
            owner = _VowelOwner(part.form, part.tag, part.normalized_start, part.normalized_end,
                                lexical_start if is_lexical else None,
                                lexical_end if is_lexical else None)
            for index in range(part.normalized_start, part.normalized_end):
                owners[index] = owner
    return owners


def build_vowel_variants(aligned: G2PAlignedResult) -> G2PVowelVariantResult:
    """단일 기존 trace를 재사용하고 별도 분석 한 번으로 원래 음절 역할을 확인한다."""

    source = aligned.result.source
    normalized = normalize_nfc(source, max_length=len(source))
    candidates: list[tuple[int, Any]] = []
    for index, char in enumerate(normalized.text):
        if not is_modern_syllable(char):
            continue
        syllable = decompose_syllable(char, (normalized.character_spans[index],))
        if syllable.vowel in {"ㅢ", "ㅖ"} or syllable.vowel == "ㅕ" and syllable.onset in {"ㅈ", "ㅉ", "ㅊ"}:
            candidates.append((index, syllable))
    tokens: tuple[AnalysisToken, ...] = ()
    analysis_status = "not_needed"
    calls = int(bool(candidates))
    if candidates:
        try:
            tokens = _validated_tokens(normalized.text)
            analysis_status = "validated"
        except Exception as error:
            analysis_status = "unavailable:" + type(error).__name__
    # 실제 raw span의 완전 일치만 연결하며 길이 비례나 단어별 위치를 가정하지 않는다.
    entries: dict[tuple[int, int], list[Any]] = {}
    for entry in aligned.alignment.entries:
        if len(entry.source_spans) == 1:
            span = entry.source_spans[0]
            entries.setdefault((span.start, span.end), []).append(entry)
    owners = _word_owners(normalized.text, tokens)
    slots: list[VowelVariantSlot] = []
    decisions: list[VowelVariantDecision] = []
    for index, original in candidates:
        raw_span = normalized.character_spans[index]
        def record(state: str, reason: str, rule_id: str | None = None) -> None:
            decisions.append(VowelVariantDecision(raw_span, original.text, state, reason, rule_id))
        matches = entries.get((raw_span.start, raw_span.end), [])
        if (len(matches) != 1 or matches[0].output_end - matches[0].output_start != 1 or
                matches[0].relation in {AlignmentRelation.UNAVAILABLE, AlignmentRelation.INSERTION}):
            record("unknown", "raw_source_single_syllable_alignment_unavailable")
            continue
        entry = matches[0]
        base_text = aligned.result.surface_pronunciation[entry.output_start:entry.output_end]
        if not is_modern_syllable(base_text):
            record("unknown", "output_is_not_single_hangul_syllable")
            continue
        base = decompose_syllable(base_text, (raw_span,))
        if original.vowel == "ㅕ":
            record("mandatory" if base.vowel == "ㅓ" else "unknown", "no_optional_jyeo_reversal", "standard.rule5.1")
            continue
        if original.vowel == "ㅢ" and original.onset != "ㅇ":
            record("mandatory" if base.vowel == "ㅣ" else "unknown", "original_consonant_ui_is_mandatory", "standard.rule5.3")
            continue
        if original.vowel == "ㅖ" and original.onset in {"ㅇ", "ㄹ"}:
            record("excluded", "original_ye_rye_excluded", "standard.rule5.2")
            continue
        owner = owners.get(index)
        if owner is None or analysis_status != "validated":
            record("unknown", "unverified_or_merged_morphological_role")
            continue
        role = "original_ye"
        condition = "original_ye_except_ye_rye"
        rule_id = "standard.rule5.2"
        allowed = ("ㅖ", "ㅔ")
        if original.vowel == "ㅢ":
            if owner.tag == "JKG" and owner.form == "의" and owner.normalized_start == index:
                role, condition, rule_id, allowed = "JKG", "verified_genitive_particle", "standard.rule5.4.particle", ("ㅢ", "ㅔ")
            elif owner.lexical_start is not None:
                if owner.lexical_start == index:
                    record("excluded", "verified_lexical_initial_ui", "standard.rule5.4.noninitial")
                    continue
                role, condition, rule_id, allowed = "lexical_noninitial", "inside_verified_lexical_owner", "standard.rule5.4.noninitial", ("ㅢ", "ㅣ")
            else:
                record("unknown", "unsupported_ui_morphological_role")
                continue
        if base.vowel not in allowed:
            record("unknown", "base_vowel_outside_local_rule_domain", rule_id)
            continue
        alternatives = tuple(VowelAlternative(base.changed(vowel=vowel).text, vowel) for vowel in allowed if vowel != base.vowel)
        owner_span = normalized.source_span(
            owner.lexical_start if owner.lexical_start is not None else owner.normalized_start,
            owner.lexical_end if owner.lexical_end is not None else owner.normalized_end,
        )
        slots.append(VowelVariantSlot(len(slots), raw_span, entry.output_start, entry.output_end,
                                      original.text, base_text, alternatives, rule_id, condition,
                                      role, owner_span, owner.tag))
        record("supported", condition, rule_id)
    return G2PVowelVariantResult(aligned, tuple(slots), tuple(decisions), calls, analysis_status)
