"""정확 어근 범위와 조사·실제 어미의 소유 증거로 규범 장단음을 판정한다."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Literal

from .alignment import G2PAlignedResult, AlignmentPrecision, AlignmentRelation
from .analyzer import KiwiAnalyzer
from .korean.hangul import decompose_syllable, is_modern_syllable
from .model import AnalysisToken, RewriteStage, SourceSpan
from .unicode import normalize_nfc

PROFILE_ID = "standard_vowel_length_v1"
_ENDINGS = frozenset({"EP", "EF", "EC", "ETN", "ETM"})
_PARTICLES = frozenset({"JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC"})
_CODA_INITIALS = {"ᆫ": "ㄴ", "ᆯ": "ㄹ", "ᆷ": "ㅁ", "ᆸ": "ㅂ",
                  "ㄴ": "ㄴ", "ㄹ": "ㄹ", "ㅁ": "ㅁ", "ㅂ": "ㅂ"}

@dataclass(frozen=True, slots=True)
class _RootFeature:
    """완성 발음 대신 어근의 길이와 확인한 활용 부류를 선언한다."""

    root: str
    tag: Literal["NNG", "VV", "VA"]
    lemma: str
    lexeme_id: str
    length: Literal["long", "short"]
    shorten_before_vowel: bool = False
    rieul_drop: bool = False

    def __post_init__(self) -> None:
        if not self.root or not all(is_modern_syllable(char) for char in self.root):
            raise ValueError("어근은 비어 있지 않은 한글 음절열이어야 합니다.")
        if self.tag not in {"NNG", "VV", "VA"} or self.length not in {"long", "short"}:
            raise ValueError("어근 품사와 장단 속성이 올바르지 않습니다.")
        if any(type(value) is not bool for value in (self.shorten_before_vowel, self.rieul_drop)):
            raise ValueError("활용 정책은 불리언으로 선언해야 합니다.")
        if self.tag == "NNG" and (self.shorten_before_vowel or self.rieul_drop):
            raise ValueError("명사에 용언 활용 정책을 지정하지 않습니다.")

    @property
    def pos(self) -> str:
        return {"NNG": "noun", "VV": "verb", "VA": "adjective"}[self.tag]


# 자체 동결한 어휘 속성만 추가하며 활용 표면형 목록은 두지 않는다.
_ROOTS = {(feature.root, feature.tag): feature for feature in (
    _RootFeature("알", "VV", "알다", "KRD_AL", "long", True, True),
    _RootFeature("좋", "VA", "좋다", "KRD_JOH", "long"),
    _RootFeature("없", "VA", "없다", "KRD_EOP", "long"),
    _RootFeature("사람", "NNG", "사람", "R18_SARAM_NOUN", "long"),
    _RootFeature("마음", "NNG", "마음", "R18_MAEUM_NOUN", "short"),
    _RootFeature("신", "VV", "신다", "R18_SIN_PREDICATE", "long", True),
    _RootFeature("끌", "VV", "끌다", "R18_KKEUL_PREDICATE", "long", rieul_drop=True),
)}
# 같은 표기·품사만으로는 어느 길이도 선택하지 않는 조건부 어휘 사실이다.
_HOMOGRAPHS = {
    ("눈", "NNG"): (("R18_NUN_EYE", "short"), ("R18_NUN_SNOW", "long")),
    ("밤", "NNG"): (("R18_BAM_NIGHT", "short"), ("R18_BAM_CHESTNUT", "long")),
}


@dataclass(frozen=True, slots=True)
class VowelLengthDecision:
    """원문 모음 핵과 그 출력 음절을 연결한 불변 장단음 판정이다."""

    value: Literal["long", "short", "unknown"]
    status: Literal["supported", "unknown", "unsupported"]
    owner_source_span: SourceSpan
    nucleus_source_span: SourceSpan
    nucleus_source_atoms: tuple[SourceSpan, ...]
    output_nucleus_syllable_span: tuple[int, int] | None
    lemma: str | None
    pos: str | None
    lexeme_id: str | None
    rule_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    reason: str
    analyzer_morphemes: tuple[tuple[str, str], ...]
    actual_ending: str | None = None
    ending_initial: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """원문 좌표와 미확정 사유를 빠짐없이 JSON 값으로 옮긴다."""

        return {
            "value": self.value, "status": self.status,
            "owner_source_span": self.owner_source_span.to_dict(),
            "nucleus_source_span": self.nucleus_source_span.to_dict(),
            "nucleus_source_atoms": [x.to_dict() for x in self.nucleus_source_atoms],
            "output_nucleus_syllable_span": list(self.output_nucleus_syllable_span) if self.output_nucleus_syllable_span else None,
            "lemma": self.lemma, "pos": self.pos, "lexeme_id": self.lexeme_id,
            "rule_ids": list(self.rule_ids), "source_ids": list(self.source_ids),
            "reason": self.reason, "analyzer_morphemes": [list(x) for x in self.analyzer_morphemes],
            "actual_ending": self.actual_ending, "ending_initial": self.ending_initial,
        }


@dataclass(frozen=True, slots=True)
class G2PVowelLengthResult:
    """기존 변환과 정렬을 보존하고 장단 지원 범위를 별도로 보고한다."""

    aligned: G2PAlignedResult
    decisions: tuple[VowelLengthDecision, ...]
    auxiliary_analysis_calls: int
    auxiliary_analysis_status: str
    profile_id: str = PROFILE_ID

    @property
    def coverage_status(self) -> str:
        if not self.decisions:
            return "no_applicable_nuclei"
        if any(x.status == "unknown" for x in self.decisions):
            return "partial_unknown"
        if any(x.status == "unsupported" for x in self.decisions):
            return "partial_unsupported"
        return "scoped_supported"

    def to_dict(self) -> dict[str, Any]:
        """파이프라인 완료와 장단 지원의 서로 다른 의미를 보존한다."""

        return {
            "schema": "g2p_vowel_length.v1", "profile_id": self.profile_id,
            "scope": "registered_nominal_roots_and_verified_predicate_inflections",
            "coverage_status": self.coverage_status,
            "complete_semantics": "base_pipeline_only",
            "aligned": {"result": self.aligned.result.to_dict(), "alignment": self.aligned.alignment.to_dict()},
            "decisions": [x.to_dict() for x in self.decisions],
            "analysis_provenance": {
                "auxiliary_provider": "KiwiAnalyzer.analyze",
                "auxiliary_coordinates": "nfc_raw_source_before_english_expansion",
                "auxiliary_analysis_calls": self.auxiliary_analysis_calls,
                "auxiliary_analysis_status": self.auxiliary_analysis_status,
                "base_pipeline_analyzer_calls": None,
                "base_pipeline_analyzer_calls_status": "not_instrumented",
            },
            "unsupported_scope": ["unregistered_lexemes", "compounds", "derivation", "contraction"],
        }


def _validated_tokens(text: str) -> tuple[AnalysisToken, ...]:
    """한 번 받은 분석의 비중첩 표면 좌표와 기본형 보존을 확인한다."""

    tokens = tuple(KiwiAnalyzer().analyze(text))
    previous_end = 0
    for token in tokens:
        if not isinstance(token, AnalysisToken):
            raise ValueError("보조 분석 token 형식이 다릅니다.")
        start, end = token.normalized_start, token.normalized_end
        if (type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or start < previous_end or
                token.form != text[start:end] or not token.morphemes):
            raise ValueError("보조 분석의 원문 소유권이 불명확합니다.")
        if "+".join(tag for _, tag in token.morphemes) != token.tag:
            raise ValueError("보조 분석 품사와 기본형 목록이 다릅니다.")
        previous_end = end
    return tokens


def _syllable(char: str):
    """지역 음운 성분만 읽으며 공개 정렬 근거로 이 임시 span을 쓰지 않는다."""

    return decompose_syllable(char, (SourceSpan.from_source(char, 0, 1),))


def _nucleus_anchor(aligned: G2PAlignedResult, raw: SourceSpan, original: str) -> tuple[int, int] | None:
    """받침의 이동 근거가 아닌 원래 모음 핵의 단일 문자 대응만 선택한다."""

    matches = [entry for entry in aligned.alignment.entries
               if len(entry.source_spans) == 1 and entry.source_spans[0] == raw
               and entry.output_start < entry.output_end]
    if len(matches) != 1:
        return None
    entry = matches[0]
    codepoint = entry.precision is AlignmentPrecision.CODEPOINT and entry.relation in {
        AlignmentRelation.IDENTITY, AlignmentRelation.SUBSTITUTION,
    }
    # 기존 정렬은 NFD 한 원자의 NFC 조합도 operation으로 표시한다.
    # 한 원자가 정확히 한 원래 음절이 되는 경우만 지역 핵 대응을 증명한다.
    canonical_atom = (len(raw.surface) > 1 and
        unicodedata.normalize("NFC", raw.surface) == original and
        entry.relation is AlignmentRelation.CONTRACTION and
        entry.precision is AlignmentPrecision.OPERATION)
    if not (codepoint or canonical_atom) or entry.output_end - entry.output_start != 1:
        return None
    output = aligned.result.surface_pronunciation[entry.output_start:entry.output_end]
    if not is_modern_syllable(output):
        return None
    if not is_modern_syllable(original) or unicodedata.normalize("NFC", raw.surface) != original:
        return None
    provenance = entry._nucleus_provenance
    if provenance is not None:
        # 마지막 자음 규칙의 표시와 핵 소유 근거는 별개지만 같은 실행에 결속한다.
        if (not provenance.valid or provenance.source_span != raw or provenance.original != original
                or provenance.realized != output
                or provenance.alignment_rule_id != (entry.rule_id if entry.stage is RewriteStage.PHONOLOGY else None)):
            return None
    elif (_syllable(output).vowel != _syllable(original).vowel
          or entry.stage is RewriteStage.PHONOLOGY):
        return None
    return entry.output_start, entry.output_end


@dataclass(frozen=True, slots=True)
class _RootOwnership:
    """어근 끝과 첫 실제 어미의 소유 좌표를 분리한 내부 증거다."""

    root_start: int
    root_end: int
    first_ending_start: int | None
    actual_ending: str | None
    ending_initial: str | None


def _valid_tail_roles(parts: tuple[tuple[str, str], ...], *, predicate: bool) -> bool:
    """명사는 조사열, 용언은 어미열 뒤의 선택적인 조사열만 허용한다."""
    if predicate and (len(parts) < 2 or parts[1][1] not in _ENDINGS):
        return False
    particle_tail = not predicate
    for _, tag in parts[1:]:
        if tag in _PARTICLES:
            particle_tail = True
        elif not predicate or tag not in _ENDINGS or particle_tail:
            return False
    return True


def _first_ending_forms(form: str, root_last: str) -> tuple[str, ...]:
    """으 탈락과 아/어 이형태만 음운 조건으로 제시하고 축약은 추정하지 않는다."""
    if form[0] in _CODA_INITIALS or not is_modern_syllable(form[0]):
        return (form,)
    first, stem = _syllable(form[0]), _syllable(root_last)
    if first.onset == "ㅇ" and first.vowel == "ㅡ" and stem.coda in {None, "ㄹ"}:
        # 으면→면, 은→ㄴ처럼 실제 첫 어미의 모음 실현을 구별한다.
        prefix = first.coda or ""
        actual = prefix + form[1:]
        return (actual,) if actual else ()
    if first.onset == "ㅇ" and first.vowel == "ㅓ" and stem.vowel in {"ㅏ", "ㅗ"}:
        return (first.changed(vowel="ㅏ").text + form[1:],)
    return (form,)


def _tokens_own_parts(
    start: int,
    tokens: tuple[AnalysisToken, ...],
    ranges: tuple[tuple[int, int], ...],
) -> bool:
    """형태소별 실현 범위와 각 결합·분리 token의 전체 범위를 대조한다."""
    index = 0
    for token in tokens:
        next_index = index + len(token.morphemes)
        if next_index > len(ranges) or token.normalized_start != start + ranges[index][0] or token.normalized_end != start + ranges[next_index - 1][1]:
            return False
        index = next_index
    return index == len(ranges)


def _prove_root_owner(
    word: str,
    start: int,
    tokens: tuple[AnalysisToken, ...],
    parts: tuple[tuple[str, str], ...],
    feature: _RootFeature,
) -> _RootOwnership | None:
    """표면 전체와 각 token의 실현 좌표가 일치할 때만 정확 어근을 소유한다."""
    width = len(feature.root)
    if not parts or parts[0] != (feature.root, feature.tag) or len(word) < width:
        return None
    predicate = feature.tag != "NNG"
    if not _valid_tail_roles(parts, predicate=predicate):
        return None
    first_forms = _first_ending_forms(parts[1][0], feature.root[-1]) if predicate else (None,)
    for first in first_forms:
        root_surface = feature.root
        ranges = [(0, width)]
        cursor = width
        rendered_tail = ""
        ending_start = initial = None
        if first is not None:
            coda = _CODA_INITIALS.get(first[0])
            last = _syllable(feature.root[-1])
            ending_start = width
            if coda is not None:
                if last.coda is None or feature.rieul_drop and last.coda == "ㄹ" and coda in {"ㄴ", "ㄹ", "ㅂ"}:
                    root_surface = feature.root[:-1] + last.changed(coda=coda).text
                else:
                    continue
                rendered_tail = first[1:]
                ending_start = width - 1
                initial = "consonant"
            elif is_modern_syllable(first[0]):
                onset = _syllable(first[0]).onset
                if feature.rieul_drop and last.coda == "ㄹ" and onset in {"ㄴ", "ㅂ", "ㅅ"}:
                    root_surface = feature.root[:-1] + last.changed(coda=None).text
                rendered_tail = first
                initial = "vowel" if onset == "ㅇ" else "consonant"
            else:
                continue
            cursor += len(rendered_tail)
            ranges.append((ending_start, cursor))
        for form, _ in parts[2:] if predicate else parts[1:]:
            ranges.append((cursor, cursor + len(form)))
            cursor += len(form)
            rendered_tail += form
        if word != root_surface + rendered_tail or not _tokens_own_parts(start, tokens, tuple(ranges)):
            continue
        return _RootOwnership(start, start + width, None if ending_start is None else start + ending_start, first, initial)
    return None


def build_vowel_length(aligned: G2PAlignedResult) -> G2PVowelLengthResult:
    """기존 정렬을 재실행하지 않고 단 한 번의 보조 분석을 재사용한다."""

    source = aligned.result.source
    normalized = normalize_nfc(source, max_length=max(1, len(source)))
    owners = tuple(re.finditer(r"[가-힣]+", normalized.text))
    tokens: tuple[AnalysisToken, ...] = ()
    calls = int(bool(owners))
    analysis_status = "not_needed"
    if owners:
        try:
            tokens = _validated_tokens(normalized.text)
            analysis_status = "validated"
        except Exception as error:
            analysis_status = "unavailable:" + type(error).__name__
    decisions = []
    for owner in owners:
        start, end = owner.span()
        word = owner.group()
        owner_raw = normalized.source_span(start, end)
        raw = normalized.source_span(start, start + 1)
        atoms = tuple(SourceSpan.from_source(source, i, i + 1) for i in range(raw.start, raw.end))
        selected = tuple(t for t in tokens if start <= t.normalized_start and t.normalized_end <= end)
        parts = tuple(p for t in selected for p in t.morphemes)
        anchor = _nucleus_anchor(aligned, raw, word[0])
        lemma = pos = lexeme_id = None
        rules: tuple[str, ...] = ()
        sources: tuple[str, ...] = ()
        ending = initial = None
        status: Literal["supported", "unknown", "unsupported"] = "unknown"
        value: Literal["long", "short", "unknown"] = "unknown"
        reason = "lemma_or_pos_unresolved"
        contiguous = bool(selected) and selected[0].normalized_start == start and selected[-1].normalized_end == end
        contiguous = contiguous and all(a.normalized_end == b.normalized_start for a, b in zip(selected, selected[1:]))
        if analysis_status != "validated" or not contiguous:
            reason = "analysis_or_whole_owner_unresolved"
        elif parts and parts[0] in _ROOTS:
            feature = _ROOTS[parts[0]]
            lemma, pos, lexeme_id = feature.lemma, feature.pos, feature.lexeme_id
            sources = (lexeme_id, "NIKL_6_7")
            rules = ("R6_WORD_INITIAL",)
            predicate = feature.tag != "NNG"
            proof = _prove_root_owner(word, start, selected, parts, feature)
            if not _valid_tail_roles(parts, predicate=predicate):
                status, reason = "unsupported", "derivation_or_nonending_owner_out_of_scope"
            elif proof is None:
                reason = "root_or_tail_realization_unresolved"
            elif anchor is None:
                reason = "nucleus_output_anchor_unresolved"
            else:
                ending, initial = proof.actual_ending, proof.ending_initial
                status = "supported"
                if not predicate:
                    value, rule = feature.length, "R6_NOMINAL_PARTICLE_RETAIN"
                elif feature.length == "short":
                    value, rule = "short", "LEXICAL_SHORT_RETAIN"
                elif initial == "vowel" and len(feature.root) == 1 and feature.shorten_before_vowel:
                    value, rule = "short", "R7_1_SHORTEN"
                elif initial == "vowel" and len(feature.root) == 1:
                    value, rule = "long", "R7_1_LEXICAL_EXCEPTION"
                elif initial == "vowel":
                    value, rule = "long", "R7_1_POLYSYLLABIC_ROOT_RETAIN"
                else:
                    value, rule = "long", "R7_1_ENDING_CONSONANT_RETAIN"
                rules += (rule,)
                reason = "verified_nominal_root_and_particle_tail" if not predicate else "verified_lexical_root_and_actual_ending"
        elif parts and parts[0] in _HOMOGRAPHS:
            lemma, pos = parts[0][0], "noun"
            sources = tuple(item[0] for item in _HOMOGRAPHS[parts[0]])
            if not _valid_tail_roles(parts, predicate=False):
                status, reason = "unsupported", "derivation_or_nonending_owner_out_of_scope"
            else:
                # 길이를 선택하지 않고 공통 표기 소유 증거만 검증한다.
                shape = _RootFeature(lemma, "NNG", lemma, sources[0], "short")
                reason = "lexical_sense_unresolved" if _prove_root_owner(word, start, selected, parts, shape) is not None else "root_or_tail_realization_unresolved"
        elif parts and parts[0][1] in {"VV", "VA"}:
            lemma, pos = parts[0][0] + "다", "verb" if parts[0][1] == "VV" else "adjective"
            status, reason = "unsupported", "lexeme_out_of_scope"
        elif parts and any((form, tag) in _ROOTS for form, tag in parts[1:]):
            status, reason = "unsupported", "compound_noninitial_root_requires_whole_owner_evidence"
        elif parts and parts[0][1] not in {"MAG", "IC"}:
            status, reason = "unsupported", "lexeme_out_of_scope"
        decisions.append(VowelLengthDecision(value, status, owner_raw, raw, atoms, anchor,
            lemma, pos, lexeme_id, rules, sources, reason, parts, ending, initial))
    return G2PVowelLengthResult(aligned, tuple(decisions), calls, analysis_status)
