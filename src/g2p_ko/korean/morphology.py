"""형태소 annotation 검증과 의존 규칙의 보수적 후보 판정을 담당한다."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from typing import Mapping, Protocol

from ..analyzer import KiwiAnalyzer
from ..errors import BackendUnavailableError
from ..model import AnalysisToken, Diagnostic, Handler, Rewrite, RewriteStage, Severity, SourceSpan
from ._shared import (
    _Segment,
    _Unit,
    _has_hard_boundary,
    _has_phonological_barrier,
    _next_syllable,
    _ordered_unique_spans,
    _record,
    _trace_before,
)
from .rules import CODA_TRANSITIONS, RULES, TENSE_ONSET
from .hangul import JUNGSEONG
from .ending_ownership import ending_coda_owner, source_owner
from .owned_sino import owned_sino_spans
from .owned_lexical import registered_owned_roots, owned_root_matches
from .word_roles import (derived_word_role, lexical_liaison_target, certify_word,
                         word_n_insertion_projection, lexical_component_liaison_target,
                         adnominal_core_evidence, contextual_zero_copula)
from .surface_proof import surface_proof_conflict, verified_token_surface
from .boundary_consumers import certify_rule_boundaries, apply_rule_boundaries
from .official import LEXICAL_PRONUNCIATIONS, NOUN_ONLY_PRONUNCIATIONS
from .boundary_policy import licenses_n_insertion, needs_suffix_liquid_analysis
from .attachment_policy import licenses_nominal_attachment
from .word_grammar import ENDINGS as _SHARED_ENDINGS, base_tag as _base_tag, parse_parts
from .nominal_surface import (licensed_positive_copula_tail as _matches_positive_copula_tail,
                              is_vowel_final_nominal_source as _is_vowel_final_nominal_source)
from .semantic_policy import SemanticToken, SENSE_FEATURES, TARGET_SPELLINGS, select_senses
from .lexicon import (
    LEXICAL_STRUCTURES,
    NO_N_INSERTION_COMPONENT_BOUNDARIES,
    NO_N_INSERTION_LEXEMES,
    SAISIOT_COMBINING_FORMS,
    SINO_KOREAN_LEXEMES,
    SINO_ORIGINS,
    SINO_ATTACHMENTS,
    LexicalStructure,
)
from .palatalization_policy import (
    PALATALIZATION_BOUNDARIES,
    PalatalizationBoundary,
    matching_palatalization_boundaries,
)


_MORPHOLOGY_CODAS = frozenset({"ㄴ", "ㄵ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄾ", "ㅁ"})
_LETTER_NAME_CODAS = {"디귿": "ㅅ", "지읒": "ㅅ", "치읓": "ㅅ", "티읕": "ㅅ", "히읗": "ㅅ", "키읔": "ㄱ", "피읖": "ㅂ"}
_N_INSERTION_VOWELS = frozenset({"ㅣ", "ㅑ", "ㅒ", "ㅕ", "ㅖ", "ㅛ", "ㅠ"})
_POSITIVE_COPULA_ENDING_TAGS = _SHARED_ENDINGS
_COMPATIBILITY_TO_TRAILING_JAMO = {"ㄴ": "ᆫ"}
# 실질 형태소 앞의 제15항은 ㅣ·y 계열(제29항 분기)을 제외한
# 현대 한글 모음 inventory 전부에 적용한다.
_LEXICAL_LIAISON_VOWELS = frozenset(JUNGSEONG) - _N_INSERTION_VOWELS
_RIEUL_ENDING_TAILS = frozenset({"걸", "밖에", "세라", "수록", "지라도", "지언정", "진대"})
_ABSENT_NEW_BOUNDARY_EVIDENCE = frozenset({
    "boundary_role_unproven", "unresolved_missing_lexical_structure",
    "whole_surface_evidence_unavailable", "original_parts_unavailable",
    "unowned_content_or_unsupported_structure",
})


@dataclass(frozen=True, slots=True)
class _MorphologyCandidate:
    """분석 적용 또는 보수적 차단에 쓰는 한 음운 후보다."""

    rule_ids: tuple[str, ...]
    left: int
    right: int
    crossed_space: bool


@dataclass(frozen=True, slots=True)
class _Annotation:
    """검증된 분석 token을 normalized offset으로 조회하는 내부 색인이다."""

    _tokens_ending_at: Mapping[int, AnalysisToken]
    _tokens_starting_at: Mapping[int, AnalysisToken]
    _tokens_covering: Mapping[int, AnalysisToken]
    text: str = ""
    compound_boundaries: frozenset[int] = frozenset()
    nasal_liquid_boundaries: frozenset[int] = frozenset()

    @classmethod
    def from_tokens(
        cls,
        tokens: tuple[AnalysisToken, ...],
        text: str = "",
        compound_boundaries: frozenset[int] = frozenset(),
        nasal_liquid_boundaries: frozenset[int] = frozenset(),
    ) -> _Annotation:
        """원래 token 순서를 보존한 offset 색인을 한 번만 만든다."""

        return cls(
            {token.normalized_end: token for token in tokens},
            {token.normalized_start: token for token in tokens},
            {offset: token for token in tokens for offset in range(token.normalized_start, token.normalized_end)},
            text,
            compound_boundaries,
            nasal_liquid_boundaries,
        )

    def ending_at(self, offset: int) -> AnalysisToken | None:
        """지정한 code point 직후에 끝나는 token을 반환한다."""

        return self._tokens_ending_at.get(offset)

    def starting_at(self, offset: int) -> AnalysisToken | None:
        """지정한 code point에서 시작하는 token을 반환한다."""

        return self._tokens_starting_at.get(offset)

    def covering(self, offset: int) -> AnalysisToken | None:
        return self._tokens_covering.get(offset)


def _apply_morphology_rules(
    text: str,
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    analyzer: KiwiAnalyzer,
    rewrites: list[Rewrite] | None,
    *,
    trace: bool,
    pause_boundaries: tuple[int, ...] = (),
    reading_relations: Mapping[tuple[int, int], str] | None = None,
    formal_decisions: dict | None = None,
    boundary_decisions: list | None = None,
    before_rules=None,
) -> tuple[list[Diagnostic], frozenset[tuple[int, int]], frozenset[int], _Annotation | None]:
    """후보 구간별로 한 번 분석하고 확인한 형태소 경계에만 규칙을 적용한다."""

    candidates = _collect_morphology_candidates(units, segments)
    if formal_decisions is not None:
        candidates += tuple(_MorphologyCandidate(("ko.formal.attachment",), left, right, True)
            for (left, right), relation in (reading_relations or {}).items()
            if relation == "ordinary_liaison")
    if not candidates:
        if before_rules is not None:
            before_rules()
        return [], frozenset(), frozenset(), None
    annotation, diagnostics = _analyze_islands(text, analyzer, units, segments, candidates, trace=trace)
    if formal_decisions is not None:
        from .formal_attachment import decide_formal_attachments
        formal_decisions.update(decide_formal_attachments(
            text, units, segments, annotation, reading_relations or {}, pause_boundaries,
            special_donors=_LETTER_NAME_CODAS))
    boundaries = certify_rule_boundaries(annotation, units, segments, pause_boundaries,
                                         reading_relations=reading_relations)
    # 기존의 명시 어휘 경계 사실은 그 원래 범위에서만 별도 보존한다.
    boundaries = tuple(boundary for boundary in boundaries if not (
        ((boundary.status == "unresolved" and "conflict" not in boundary.reason
          and boundary.applicability != "blocked")
         or (boundary.status == "excluded" and boundary.reason == "independent_basis_absent"))
        and not _has_phonological_barrier(units, *boundary.pair, segments, pause_boundaries)
        and annotation is not None and _has_licensed_lexical_palatalization_boundary(units, segments, annotation,
            *boundary.pair, annotation.covering(boundary.pair[0]), pause_boundaries)))
    if boundary_decisions is not None:
        boundary_decisions.extend(boundaries)
    # 새 내부 권한은 소리 변화와 기존 어휘 구조 확장 전에 원 분석에서만 고정한다.
    internal_stem_pairs = frozenset((item.left, item.right) for item in candidates
        if item.rule_ids in {(RULES["ko.stem.rieul_giyeok"].id,),
                             (RULES["ko.stem.tensing.24"].id,), (RULES["ko.stem.tensing.25"].id,)}
        and annotation is not None and annotation.covering(item.left) is not None
        and annotation.covering(item.left) == annotation.covering(item.right)
        and _is_verb_stem_before_ending(annotation, item.left, item.right,
            units=units, segments=segments, pause_boundaries=pause_boundaries))
    if before_rules is not None:
        before_rules()
    if annotation is None:
        # 초기 M2의 호환 진단은 분석 실패를 감추지 않되, 규칙이 적용되지 않았음을
        # 호출자가 기존처럼 식별할 수 있게 함께 남긴다.
        if trace:
            diagnostics.extend(_skipped_rule_diagnostics(units, candidates))
        return (
            diagnostics,
            _blocked_pairs(candidates),
            frozenset(),
            None,
        )

    contextual_structures, contextual_sino, owned_structures, owned_onsets = _contextual_lexical_properties(
        text, units, segments, annotation,
    )
    annotation, structures = _expand_lexical_structures(
        text, units, segments, annotation, contextual_structures,
    )
    structures += owned_structures
    # 새 원문 증명의 부재는 따로 검증된 기존 사전 구조의 소비 권한을 가리지 않는다.
    # 원래 parts·유래는 보존하며, 확장 분석을 원래 직접 분석이라고 보고하지 않는다.
    boundaries = tuple(replace(boundary, applicability="not_required",
        reason="prior_verified_legacy_structure", source="legacy_structure_delegation")
        if (boundary.status == "unresolved" and boundary.applicability == "unresolved"
            and boundary.reason in _ABSENT_NEW_BOUNDARY_EVIDENCE
            and boundary.pair[1] in annotation.compound_boundaries
            and not _has_phonological_barrier(units, *boundary.pair, segments, pause_boundaries))
        else boundary for boundary in boundaries)
    if boundary_decisions is not None:
        # 전체 엔진은 잔존 정확 어휘 치환을 먼저 적용한 뒤 이 결정을 실행한다.
        boundary_decisions[:] = boundaries
        handled_pairs = frozenset(boundary.pair for boundary in boundaries
                                  if boundary.applicability != "not_required")
    else:
        # 형태소 단계만 직접 요청한 호출자는 별도의 정확 치환 단계를 갖지 않는다.
        events = apply_rule_boundaries(boundaries, units, rewrites)
        handled_pairs = frozenset(event.boundary.pair for event in events
                                  if event.applicability != "not_required")
    for candidate in candidates:
        if ((candidate.left, candidate.right) in handled_pairs and candidate.rule_ids in {
                ("ko.palatalization",), ("ko.n_insertion.compound",),
                ("ko.n_insertion.word",), ("ko.liaison.lexical",)}):
            continue
        if _has_phonological_barrier(
            units, candidate.left, candidate.right, segments, pause_boundaries,
        ):
            continue
        if candidate.rule_ids == (RULES["ko.ui.particle"].id,):
            _apply_particle_ui(units, candidate, annotation, rewrites)
        elif candidate.rule_ids == (RULES["ko.stem.rieul_giyeok"].id,):
            _apply_rieul_giyeok_stem(units, candidate, annotation, rewrites,
                verified_internal=(candidate.left, candidate.right) in internal_stem_pairs)
        elif candidate.rule_ids == (RULES["ko.stem.tensing.24"].id,):
            _apply_stem_tensing_24(units, candidate, annotation, rewrites,
                verified_internal=(candidate.left, candidate.right) in internal_stem_pairs)
        elif candidate.rule_ids == (RULES["ko.stem.tensing.25"].id,):
            _apply_stem_tensing_25(units, candidate, annotation, rewrites,
                verified_internal=(candidate.left, candidate.right) in internal_stem_pairs)
        elif candidate.rule_ids == (RULES["ko.modifier.tensing.27"].id,):
            _apply_modifier_tensing_27(units, candidate, annotation, rewrites)
        elif candidate.rule_ids == ("ko.palatalization",):
            _apply_confirmed_palatalization(units, candidate, annotation, rewrites, segments, pause_boundaries)
        elif candidate.rule_ids == ("ko.ending.tensing.27",):
            _apply_ending_tensing_27(units, candidate, annotation, rewrites)
        elif candidate.rule_ids == ("ko.letter_name.16",):
            _apply_letter_name_liaison(units, candidate, annotation, rewrites)
        elif candidate.rule_ids == ("ko.n_insertion.word",):
            # 명시 일반 연음은 이 경계의 단어 ㄴ 첨가와 경쟁하지 않는다.
            if (reading_relations or {}).get((candidate.left, candidate.right)) != "ordinary_liaison":
                _apply_word_n_insertion(units, candidate, annotation, segments, rewrites, pause_boundaries)
        elif candidate.rule_ids == ("ko.n_insertion.compound",):
            _apply_compound_n_insertion(units, candidate, annotation, segments, rewrites)
    _apply_lexical_boundary_tensing(units, structures, rewrites, segments, pause_boundaries, owned_onsets)
    _apply_sino_tensing(units, segments, annotation, rewrites, contextual_sino, pause_boundaries)
    _apply_suffix_liquid_nasalization(units, segments, annotation, rewrites, pause_boundaries)
    return diagnostics, frozenset(), frozenset(), annotation


def _blocked_pairs(
    candidates: tuple[_MorphologyCandidate, ...],
) -> frozenset[tuple[int, int]]:
    """적용을 미룬 후보의 인접 음절 pair를 만든다."""

    return frozenset((item.left, item.right) for item in candidates)


def _is_word_reading(segment: _Segment) -> bool:
    """한글 단어와 관용 읽기는 이어 읽되 영문 문자 이름은 별도 단위로 유지한다."""

    return segment.handler is Handler.KOREAN or (
        segment.handler is Handler.ENGLISH and segment.rule_id == "english.conventional.v1"
    )


_WORD_N_INSERTION_NOUN_TAGS = frozenset({"NNG", "NNP", "NNB", "NNBC", "NP"})
_WORD_N_INSERTION_VERB_TAGS = frozenset(
    tag
    for base in ("VV", "VA", "VX")
    for tag in (base, f"{base}-I", f"{base}-R")
)
_WORD_N_INSERTION_ENDING_TAGS = frozenset({"EP", "EF", "EC", "ETM", "ETN"})


def _collect_morphology_candidates(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
) -> tuple[_MorphologyCandidate, ...]:
    """표면형만으로 가능한 후보를 모으되, 실제 적용은 분석 뒤로 미룬다."""

    candidates: list[_MorphologyCandidate] = []
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is not None:
            right, crossed_space = neighbor
            next_token = units[right].syllable
            assert next_token is not None
            if needs_suffix_liquid_analysis(
                left_coda=token.coda, right_onset=next_token.onset,
                has_two_syllable_base_candidate=_is_adjacent_korean_syllable_before(units, segments, index),
                crossed_space=crossed_space,
            ):
                candidates.append(_MorphologyCandidate(("ko.liquid.suffix.20",), index, right, False))
            if not crossed_space and token.coda in {"ㄷ", "ㅌ", "ㄾ"} and (
                next_token.onset == "ㅇ" and next_token.vowel in {"ㅣ", "ㅕ"}
                or token.coda == "ㄷ" and next_token.onset == "ㅎ" and (
                    next_token.vowel == "ㅣ"
                    or next_token.vowel == "ㅕ" and next_token.coda in {None, "ㅆ"}
                )
            ):
                candidates.append(_MorphologyCandidate(("ko.palatalization",), index, right, False))
            if token.coda and next_token.onset == "ㅇ" and next_token.vowel in _LEXICAL_LIAISON_VOWELS:
                candidates.append(_MorphologyCandidate(("ko.liaison.lexical",), index, right, crossed_space))
            if token.coda == "ㄹ" and not crossed_space and next_token.onset in TENSE_ONSET:
                candidates.append(_MorphologyCandidate(("ko.ending.tensing.27",), index, right, False))
            if token.coda and next_token.onset == "ㅇ":
                if (crossed_space and next_token.vowel in _N_INSERTION_VOWELS
                    and _is_word_reading(segments[unit.segment_index])
                    and _is_word_reading(segments[units[right].segment_index])):
                    candidates.append(_MorphologyCandidate(("ko.n_insertion.word",), index, right, True))
                elif (not crossed_space and next_token.vowel in _N_INSERTION_VOWELS
                    and _is_word_reading(segments[unit.segment_index])
                    and _is_word_reading(segments[units[right].segment_index])):
                    candidates.append(_MorphologyCandidate(("ko.n_insertion.compound",), index, right, False))
                if not crossed_space and index > 0:
                    name = units[index - 1].text + unit.text
                    if name in _LETTER_NAME_CODAS and not _has_hard_boundary(
                        units[index - 1].segment_index, unit.segment_index, segments
                    ):
                        candidates.append(_MorphologyCandidate(("ko.letter_name.16",), index, right, False))
        if _is_adjacent_korean_syllable_before(units, segments, index) and (
            token.onset == "ㅇ" and token.vowel == "ㅢ" and token.coda is None
        ):
            candidates.append(_MorphologyCandidate((RULES["ko.ui.particle"].id,), index, index, False))
        if token.coda not in _MORPHOLOGY_CODAS:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        next_token = units[right].syllable
        assert next_token is not None
        if token.coda == "ㄺ" and next_token.onset == "ㄱ" and not crossed_space:
            candidates.append(
                _MorphologyCandidate((RULES["ko.stem.rieul_giyeok"].id,), index, right, False)
            )
        if (
            token.coda in {"ㄴ", "ㄵ", "ㅁ", "ㄻ"}
            and next_token.onset in {"ㄱ", "ㄷ", "ㅅ", "ㅈ"}
            and not crossed_space
        ):
            candidates.append(
                _MorphologyCandidate((RULES["ko.stem.tensing.24"].id,), index, right, False)
            )
        if (
            token.coda in {"ㄼ", "ㄾ"}
            and next_token.onset in {"ㄱ", "ㄷ", "ㅅ", "ㅈ"}
            and not crossed_space
        ):
            candidates.append(
                _MorphologyCandidate((RULES["ko.stem.tensing.25"].id,), index, right, False)
            )
        if (
            token.coda == "ㄹ"
            and crossed_space
            and next_token.onset in {"ㄱ", "ㄷ", "ㅂ", "ㅅ", "ㅈ"}
        ):
            candidates.append(
                _MorphologyCandidate((RULES["ko.modifier.tensing.27"].id,), index, right, True)
            )
    # 공식 어휘에 조사 등이 붙었을 때는 실제 형태소 단위와 일치하는지 확인한다.
    source = "".join(unit.text for unit in units)
    lexical_words = set(LEXICAL_PRONUNCIATIONS) | set(LEXICAL_STRUCTURES) | SINO_KOREAN_LEXEMES
    owned_words = {root.spelling for root in registered_owned_roots()}
    lexical_words |= owned_words
    for word in sorted(lexical_words):
        start = source.find(word)
        while start >= 0:
            end = start + len(word)
            extended = (start > 0 and "가" <= source[start - 1] <= "힣") or (
                end < len(source) and "가" <= source[end] <= "힣"
            )
            if (extended or word in NOUN_ONLY_PRONUNCIATIONS or word in LEXICAL_STRUCTURES or word in SINO_KOREAN_LEXEMES or word in owned_words) and not _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments):
                candidates.append(_MorphologyCandidate(("ko.official.morpheme",), start, end - 1, False))
            start = source.find(word, start + 1)
    for word in sorted(TARGET_SPELLINGS):
        start = source.find(word)
        while start >= 0:
            end = start + len(word)
            if not _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments):
                candidates.append(_MorphologyCandidate(("ko.semantic.context",), start, end - 1, False))
            start = source.find(word, start + 1)
    return tuple(candidates)


def _is_adjacent_korean_syllable_before(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    index: int,
) -> bool:
    """조사 후보 바로 앞이 같은 한국어 island의 연속 음절인지 확인한다."""

    if index == 0:
        return False
    previous = units[index - 1]
    current = units[index]
    return (
        previous.handler is Handler.KOREAN
        and previous.syllable is not None
        and not _has_hard_boundary(previous.segment_index, current.segment_index, segments)
    )


def _analyze_islands(
    text: str,
    analyzer: KiwiAnalyzer,
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    candidates: tuple[_MorphologyCandidate, ...],
    *,
    trace: bool,
) -> tuple[_Annotation | None, list[Diagnostic]]:
    """HARD 경계 안의 후보를 모아 구간별 한 번 분석하고 원 좌표로 복원한다."""

    try:
        analyze = getattr(analyzer, "analyze_components", analyzer.analyze)
        cuts = [0]
        for index in range(1, len(units)):
            if _has_hard_boundary(units[index - 1].segment_index, units[index].segment_index, segments):
                cuts.append(index)
        cuts.append(len(units))
        candidate_starts = {item.left for item in candidates}
        collected: list[AnalysisToken] = []
        for start, end in zip(cuts, cuts[1:]):
            if not any(index in candidate_starts for index in range(start, end)):
                continue
            island = text[start:end]
            local_tokens = tuple(analyze(island))
            _validate_analysis_tokens(local_tokens, island, require_korean_coverage=True)
            collected.extend(
                AnalysisToken(token.form, token.tag, token.normalized_start + start, token.normalized_end + start,
                              token.morphemes, tuple((a + start, b + start) for a, b in token.morpheme_spans))
                for token in local_tokens
            )
        tokens = tuple(collected)
        _validate_analysis_tokens(tokens, text)
    except BackendUnavailableError:
        if not trace:
            return None, []
        return None, _analyzer_failure_diagnostics(
            units,
            candidates,
            "analyzer_unavailable",
            "형태소 의존 규칙 후보가 있지만 분석기를 사용할 수 없어 적용하지 않았습니다.",
        )
    except Exception:
        if not trace:
            return None, []
        return None, _analyzer_failure_diagnostics(
            units,
            candidates,
            "analyzer_failed",
            "형태소 분석 결과를 검증할 수 없어 후보 규칙을 적용하지 않았습니다.",
        )
    return _Annotation.from_tokens(tokens, text), []


def _validate_analysis_tokens(
    tokens: tuple[AnalysisToken, ...],
    text: str,
    *,
    require_korean_coverage: bool = False,
) -> None:
    """분석 token의 표면형과 normalized 좌표를 현재 문자열에 맞춰 검증한다."""

    previous_end = 0
    for token in tokens:
        if not isinstance(token, AnalysisToken):
            raise ValueError("분석기는 AnalysisToken만 반환해야 합니다.")
        if isinstance(token.normalized_start, bool) or isinstance(token.normalized_end, bool):
            raise ValueError("분석 token 좌표에는 불리언을 사용할 수 없습니다.")
        if not (0 <= token.normalized_start < token.normalized_end <= len(text)):
            raise ValueError("분석 token의 normalized 좌표가 문자열 범위를 벗어났습니다.")
        if token.normalized_start < previous_end:
            raise ValueError("분석 token은 원문 순서의 비중첩 범위여야 합니다.")
        if not isinstance(token.tag, str) or not isinstance(token.form, str) or not token.tag or not token.form:
            raise ValueError("분석 token에는 비어 있지 않은 문자열 form과 tag가 필요합니다.")
        if token.form != text[token.normalized_start : token.normalized_end]:
            raise ValueError("분석 token의 표면형이 normalized 좌표와 다릅니다.")
        if require_korean_coverage and any("가" <= char <= "힣" for char in text[previous_end:token.normalized_start]):
            raise ValueError("분석 결과가 입력의 한글 음절을 누락했습니다.")
        previous_end = token.normalized_end
    if require_korean_coverage and any("가" <= char <= "힣" for char in text[previous_end:]):
        raise ValueError("분석 결과가 입력의 한글 음절을 누락했습니다.")


def _analyzer_failure_diagnostics(
    units: list[_Unit],
    candidates: tuple[_MorphologyCandidate, ...],
    code: str,
    message: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int, int]] = set()
    for candidate in candidates:
        for rule_id in candidate.rule_ids:
            key = (rule_id, candidate.left, candidate.right)
            if key in seen:
                continue
            seen.add(key)
            diagnostics.append(
                Diagnostic(
                    code,
                    message,
                    Severity.WARNING,
                    _candidate_spans(units, candidate),
                    rule_id,
                    RewriteStage.PHONOLOGY,
                )
            )
    return diagnostics


def _skipped_rule_diagnostics(
    units: list[_Unit],
    candidates: tuple[_MorphologyCandidate, ...],
) -> list[Diagnostic]:
    """분석 실패 뒤에도 규칙 미적용을 식별하는 호환 진단을 남긴다."""

    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, int, int]] = set()
    for candidate in candidates:
        for rule_id in candidate.rule_ids:
            key = (rule_id, candidate.left, candidate.right)
            if key in seen:
                continue
            seen.add(key)
            diagnostics.append(
                Diagnostic(
                    "morphology_rule_skipped",
                    "형태소 분석 결과가 없어 형태소 의존 규칙을 적용하지 않았습니다.",
                    Severity.WARNING,
                    _candidate_spans(units, candidate),
                    rule_id,
                    RewriteStage.PHONOLOGY,
                )
            )
    return diagnostics


def _candidate_spans(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
) -> tuple[SourceSpan, ...]:
    return _ordered_unique_spans(
        span for unit in units[candidate.left : candidate.right + 1] for span in unit.source_spans
    )


def _has_tag_ending_at(annotation: _Annotation, offset: int, prefix: str) -> bool:
    item = annotation.ending_at(offset)
    return item is not None and _tag_has_prefix(item.tag, prefix)


def _has_tag_starting_at(annotation: _Annotation, offset: int, prefix: str) -> bool:
    item = annotation.starting_at(offset)
    return item is not None and _tag_has_prefix(item.tag, prefix)


def _tag_has_prefix(tag: str, prefix: str) -> bool:
    """분석기의 결합 품사 태그도 개별 품사로 안전하게 판정한다."""

    return any(part.startswith(prefix) for part in tag.split("+"))


def _is_independent_word_n_insertion_target(
    token: AnalysisToken, *, annotation: _Annotation | None = None,
    units: list[_Unit] | None = None, segments: tuple[_Segment, ...] = (),
    pause_boundaries: tuple[int, ...] = (),
) -> bool:
    """전체 단어의 공유 증명을 ㄴ 첨가 범주 정책으로만 투영한다."""

    if annotation is None or units is None or annotation.starting_at(token.normalized_start) != token:
        return False
    return word_n_insertion_projection(certify_word(
        annotation, token.normalized_start, units, segments, pause_boundaries,
    )) == "eligible"


def _is_simple_word_n_insertion_target(token: AnalysisToken) -> bool:
    """옛 단순 API의 범주 범위 안에서도 꼬리 순서는 공유 문법으로 확인한다."""

    tags = tuple(token.tag.split("+"))
    if not tags or any(not tag for tag in tags):
        return False
    if all(tag in _WORD_N_INSERTION_NOUN_TAGS for tag in tags) or all(tag == "MAG" for tag in tags):
        return True
    if len(tags) == 1:
        return tags[0] in _WORD_N_INSERTION_VERB_TAGS
    parts = token.morphemes
    return (bool(parts) and tags[0] in _WORD_N_INSERTION_VERB_TAGS
            and all(tag in _WORD_N_INSERTION_ENDING_TAGS for tag in tags[1:])
            and tuple(tag for _, tag in parts) == tags
            and parse_parts(parts).lexical_status == "eligible")


def _contextual_lexical_properties(text, units, segments, annotation):
    """독립 선택기의 결과를 해당 출현 좌표의 어휘 속성으로만 전달한다."""
    tokens = tuple(
        SemanticToken(token.form, token.tag, token.normalized_start, token.normalized_end, token.morphemes)
        for token in annotation._tokens_starting_at.values()
    )
    boundaries = frozenset(
        index for index in range(1, len(units))
        if _has_hard_boundary(units[index - 1].segment_index, units[index].segment_index, segments)
    )
    structures = []
    sino = []
    owned_structures = []
    owned_onsets = []
    choices = select_senses(text, tokens, boundaries)
    for choice in choices:
        if choice.sense_id is None:
            continue
        features = SENSE_FEATURES[choice.sense_id]
        if features.spelling != text[choice.start:choice.end]:
            continue
        if features.parts:
            structure = LexicalStructure(features.parts, features.tense_boundaries)
            if structure.spelling == features.spelling:
                structures.append((choice.start, structure))
        if features.sino:
            sino.append((choice.start, choice.end))
    for match in owned_root_matches(
        text, annotation, choices, nominal_tail_validator=_has_intrinsic_nominal_tail, hard_boundaries=boundaries,
    ):
        if _has_hard_boundary(
            units[match.owner_start].segment_index, units[match.owner_end - 1].segment_index, segments,
        ):
            continue
        root = match.root
        if root.tense_boundaries and all(
            units[match.start + offset].syllable is not None
            and units[match.start + offset].syllable.onset == onset
            for offset, onset in root.expected_onsets
        ):
            # 구성 전체를 재분석하지 않고 정확한 어근 범위의 속성만 전달한다.
            owned_structures.append((match.start, root.lexical_structure))
        for constraint in root.internal_onsets:
            if (0 < constraint.offset < len(root.spelling)
                    and all(unit.handler is Handler.KOREAN and unit.syllable is not None
                            for unit in units[match.owner_start:match.owner_end])):
                owned_onsets.append((match.start + constraint.offset,
                                     constraint.source_onset, constraint.required_onset))
        if len(root.hanja) == len(root.spelling):
            # 한자음이 정렬된 어근에 한해 일반 제26항의 입력 범위를 만든다.
            sino.append((match.start, match.end))
    return tuple(structures), tuple(sino), tuple(owned_structures), tuple(owned_onsets)


def _has_adjacent_nominal_fragment(tokens, boundary: int, *, on_left: bool) -> bool:
    """owner 끝에 바로 붙은 명사 조각이 있으면 더 긴 결합으로 본다."""
    nominal_tags = {"NNG", "NNP", "NP", "NR", "SN", "NNB", "XPN", "XSN"}
    for token in tokens:
        if on_left and token.normalized_end != boundary:
            continue
        if not on_left and token.normalized_start != boundary:
            continue
        tags = (part.split("-", 1)[0] for part in token.tag.split("+"))
        if any(tag in nominal_tags for tag in tags):
            return True
    return False


class _ExactStructureOwner(Protocol):
    """모든 정확 소유 소비자가 공유하는 표기와 허용 품사 계약이다."""

    @property
    def spelling(self) -> str: ...

    @property
    def owner_pos(self) -> frozenset[str]: ...


def _valid_exact_structure_owner(
    text: str,
    start: int,
    end: int,
    structure: _ExactStructureOwner,
    original_tokens: tuple[AnalysisToken, ...],
    *,
    allow_owned_composition: bool = False,
) -> bool:
    """공통 소유 증거를 검증하고 성분 재사용은 호출자가 명시할 때만 허용한다."""
    if type(allow_owned_composition) is not bool:
        return False
    allowed = structure.owner_pos
    if not allowed:
        return True
    if (
        not allowed <= {"NNG", "NNP"}
        or not 0 <= start < end <= len(text)
        or text[start:end] != structure.spelling
        or (not allow_owned_composition and (
            _has_adjacent_nominal_fragment(original_tokens, start, on_left=True)
            or _has_adjacent_nominal_fragment(original_tokens, end, on_left=False)
        ))
    ):
        return False

    owned = tuple(
        token for token in original_tokens
        if token.normalized_start < end and start < token.normalized_end
    )
    if not owned or any(
        token.normalized_start < start or token.normalized_end > end
        for token in owned
    ):
        return False
    # 성분 재사용도 정확한 원문 범위와 비중첩 분석을 요구한다.
    cursor = start
    for token in owned:
        if token.form != text[token.normalized_start:token.normalized_end] or token.normalized_start != cursor:
            return False
        cursor = token.normalized_end
    if cursor != end:
        return False

    if len(owned) == 1:
        token = owned[0]
        if token.tag not in allowed:
            return False
        morphemes = token.morphemes or ((token.form, token.tag),)
        return bool(morphemes) and all(tag == token.tag for _, tag in morphemes) and "".join(
            form for form, _ in morphemes
        ) == token.form

    if "NNG" not in allowed:
        return False
    for token in owned:
        if token.tag != "NNG":
            return False
        morphemes = token.morphemes or ((token.form, token.tag),)
        if not morphemes or any(tag != "NNG" for _, tag in morphemes):
            return False
        if "".join(form for form, _ in morphemes) != token.form:
            return False
    return True


def _expand_lexical_structures(
    text: str, units: list[_Unit], segments: tuple[_Segment, ...], annotation: _Annotation,
    contextual_structures: tuple[tuple[int, LexicalStructure], ...] = (),
) -> tuple[_Annotation, tuple[tuple[int, LexicalStructure], ...]]:
    """완전한 어휘 범위 안에서만 검증된 내부 구조를 보충한다.

    조사·어미로 이미 분석된 문자를 명사의 일부로 삼지 않는다. 따라서
    ‘밭+이랑/JC’나 ‘물+질’처럼 문법적·의미적 중의성이 있는 결합을 덮지 않는다.
    """

    original_tokens = tuple(annotation._tokens_starting_at.values())
    tokens = list(original_tokens)
    occupied: set[int] = set()
    compound_boundaries: set[int] = set()
    nasal_liquid_boundaries: set[int] = set()
    matches: list[tuple[int, LexicalStructure]] = []
    # 문맥에서 선택한 구조는 같은 표기의 다른 출현에 전파하지 않는다.
    targets = list(contextual_structures)
    for spelling, structure in LEXICAL_STRUCTURES.items():
        start = text.find(spelling)
        while start >= 0:
            targets.append((start, structure))
            start = text.find(spelling, start + 1)
    for start, structure in sorted(targets, key=lambda item: (-len(item[1].spelling), item[1].spelling, item[0])):
        end = start + len(structure.spelling)
        covered = [token for token in tokens if start <= token.normalized_start < end]
        valid = (
            annotation.starting_at(start) is not None and annotation.ending_at(end) is not None
            and not occupied.intersection(range(start, end))
            and not _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments)
            and all(unit.syllable is not None for unit in units[start:end])
            and all(not any(_tag_has_prefix(token.tag, tag) for tag in ("J", "E")) for token in covered)
            and _valid_exact_structure_owner(
                text, start, end, structure, original_tokens,
                allow_owned_composition=structure.allow_owned_composition,
            )
        )
        if valid:
            tokens = [token for token in tokens if token.normalized_end <= start or token.normalized_start >= end]
            cursor = start
            for number, (form, tag) in enumerate(structure.parts):
                if number:
                    compound_boundaries.add(cursor)
                if number in structure.nasal_liquid_boundaries:
                    nasal_liquid_boundaries.add(cursor)
                tokens.append(AnalysisToken(form, tag, cursor, cursor + len(form)))
                cursor += len(form)
            occupied.update(range(start, end))
            matches.append((start, structure))

    # Kiwi가 앞 성분을 포함한 명사 전체를 한 NNG로 묶더라도, 선언된
    # 사이시옷 결합형 뒤에 모음으로 시작하는 명사 성분이 있으면 경계만 복원한다.
    # 태그가 조사·어미와 결합했거나 HARD 경계를 건너는 경우에는 나누지 않는다.
    for token in tuple(tokens):
        if not _tag_has_prefix(token.tag, "NNG") or any(
            _tag_has_prefix(token.tag, tag) for tag in ("J", "E")
        ):
            continue
        if any(offset in occupied for offset in range(token.normalized_start, token.normalized_end)):
            continue
        for prefix in sorted(SAISIOT_COMBINING_FORMS, key=lambda form: (-len(form), form)):
            boundary = token.normalized_start + len(prefix)
            if (
                not token.form.startswith(prefix)
                or token.normalized_end <= boundary
                or boundary <= token.normalized_start
                or _has_hard_boundary(
                    units[boundary - 1].segment_index, units[boundary].segment_index, segments,
                )
            ):
                continue
            left = units[boundary - 1].syllable
            right = units[boundary].syllable
            if (
                left is None or left.coda != "ㅅ" or right is None
                or right.onset != "ㅇ" or right.vowel not in _N_INSERTION_VOWELS
            ):
                continue
            tokens.remove(token)
            tokens.extend((
                AnalysisToken(prefix, "NNG+Z_SIOT", token.normalized_start, boundary),
                AnalysisToken(
                    token.form[len(prefix):], "NNG", boundary, token.normalized_end,
                ),
            ))
            compound_boundaries.add(boundary)
            occupied.update(range(token.normalized_start, token.normalized_end))
            break
    # 통짜 명사라도 확인한 한자어 기반과 생산적 후행 성분으로 정확히 나뉘면
    # 경계를 복원한다. 이미 조사·어미로 분리된 분석을 다시 명사로 묶지 않는다.
    for token in tuple(tokens):
        if token.tag != "NNG" or token.form in NO_N_INSERTION_LEXEMES or any(
            offset in occupied for offset in range(token.normalized_start, token.normalized_end)
        ):
            continue
        for attachment in SINO_ATTACHMENTS:
            if not token.form.endswith(attachment.form):
                continue
            whole_origin = SINO_ORIGINS.get(token.form)
            if whole_origin is not None and not any(
                variant.endswith(attachment.hanja) for variant in whole_origin.hanja_variants
            ):
                continue
            base = token.form[:-len(attachment.form)]
            if len(base) < 2 or base not in SINO_KOREAN_LEXEMES:
                continue
            boundary = token.normalized_start + len(base)
            if _has_hard_boundary(
                units[token.normalized_start].segment_index,
                units[token.normalized_end - 1].segment_index, segments,
            ):
                continue
            tokens.remove(token)
            tokens.extend((
                AnalysisToken(base, "NNG", token.normalized_start, boundary),
                AnalysisToken(attachment.form, attachment.tag, boundary, token.normalized_end),
            ))
            compound_boundaries.add(boundary)
            if attachment.nasal_liquid and len(base) == 2:
                nasal_liquid_boundaries.add(boundary)
            occupied.update(range(token.normalized_start, token.normalized_end))
            break
    return _Annotation.from_tokens(
        tuple(sorted(tokens, key=lambda token: token.normalized_start)), text, frozenset(compound_boundaries),
        frozenset(nasal_liquid_boundaries),
    ), tuple(matches)


def _apply_lexical_boundary_tensing(
    units: list[_Unit], matches: tuple[tuple[int, LexicalStructure], ...], rewrites: list[Rewrite] | None,
    segments: tuple[_Segment, ...], pause_boundaries: tuple[int, ...],
    owned_onsets: tuple[tuple[int, str, str], ...] = (),
) -> None:
    """어휘 자료가 지정한 경계에서만 일반 된소리 전이를 적용한다."""

    constraints = list(owned_onsets)
    for start, structure in matches:
        cursor = start
        for number, (form, _) in enumerate(structure.parts):
            if number in structure.tense_boundaries:
                right = units[cursor]
                assert right.syllable is not None
                tense = TENSE_ONSET.get(right.syllable.onset)
                if tense is not None:
                    constraints.append((cursor, right.syllable.onset, tense))
            cursor += len(form)
    for cursor, source_onset, required_onset in constraints:
        right = units[cursor]
        if (right.syllable is None or right.syllable.onset != source_onset
                or TENSE_ONSET.get(source_onset) != required_onset
                or _has_phonological_barrier(units, cursor - 1, cursor, segments, pause_boundaries)):
            continue
        before = _trace_before(rewrites, units, cursor - 1, cursor)
        right.syllable = right.syllable.changed(onset=required_onset)
        _record(rewrites, units, cursor - 1, cursor, before, "ko.lexical.tensing")


def _apply_sino_tensing(
    units: list[_Unit], segments: tuple[_Segment, ...], annotation: _Annotation, rewrites: list[Rewrite] | None,
    contextual_spans: tuple[tuple[int, int], ...] = (),
    pause_boundaries: tuple[int, ...] = (),
) -> None:
    """제26항을 한자어로 확인한 형태소 내부의 모든 ㄹ+ㄷ·ㅅ·ㅈ에 적용한다."""

    spans: set[tuple[int, int]] = set(contextual_spans)
    # 전체 부사의 고유어 성분에는 속성을 주지 않고 선언한 한자 어근만 쓴다.
    for root_start, root_end, owner_start, owner_end in owned_sino_spans(
        annotation.text, annotation, nominal_tail_validator=_has_intrinsic_nominal_tail,
    ):
        if not _has_hard_boundary(
            units[owner_start].segment_index, units[owner_end - 1].segment_index, segments,
        ):
            spans.add((root_start, root_end))
    for word in annotation._tokens_starting_at.values():
        nominal = _tag_has_prefix(word.tag, "NN")
        origin = SINO_ORIGINS.get(word.form)
        verified_other_pos = origin is not None and any(
            _tag_has_prefix(word.tag, pos) for pos in origin.pos if not pos.startswith("NN")
        )
        if not (nominal or verified_other_pos):
            continue
        stem = word.form
        # 명칭·장치명으로 한 토큰이 된 -이·-기도 확인한 한자어 어근의 소리를
        # 보존한다. 임의 부분 문자열이나 모든 NNG를 한자어로 간주하지 않는다.
        if stem not in SINO_KOREAN_LEXEMES:
            if not nominal or len(stem) < 3 or stem[-1] not in {"이", "기"} or stem[:-1] not in SINO_KOREAN_LEXEMES:
                continue
            stem = stem[:-1]
        spans.add((word.normalized_start, word.normalized_start + len(stem)))
    # ‘일시’를 일/NR+시/NNB로 나눠도 한자어 속성은 같다. 검증된 어휘의
    # 양 끝과 명사·수사 분석이 모두 일치할 때만 하나의 어휘 범위로 확인한다.
    for stem in SINO_KOREAN_LEXEMES:
        start = annotation.text.find(stem)
        while start >= 0:
            end = start + len(stem)
            if (
                annotation.starting_at(start) is not None
                and annotation.ending_at(end) is not None
                and not _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments)
                and all(
                    (token := annotation.covering(offset)) is not None and _tag_has_prefix(token.tag, "N")
                    for offset in range(start, end)
                )
            ):
                spans.add((start, end))
            start = annotation.text.find(stem, start + 1)
    for start, end in sorted(spans):
        for right in range(start + 1, end):
            left_token, right_token = units[right - 1].syllable, units[right].syllable
            if left_token is None or right_token is None or left_token.coda != "ㄹ" or right_token.onset not in {"ㄷ", "ㅅ", "ㅈ"}:
                continue
            if _has_phonological_barrier(
                units, right - 1, right, segments, pause_boundaries,
            ):
                continue
            # 동일 한자의 중첩은 제외한다. 한자 표기가 없는 자료에서는 동일 음절을
            # 보수적으로 제외하여 허허실실·절절하다 계열의 과잉 적용을 막는다.
            if annotation.text[right - 1] == annotation.text[right]:
                continue
            before = _trace_before(rewrites, units, right - 1, right)
            units[right].syllable = right_token.changed(onset=TENSE_ONSET[right_token.onset])
            _record(rewrites, units, right - 1, right, before, "ko.sino.tensing.26")


def _apply_suffix_liquid_nasalization(
    units: list[_Unit], segments: tuple[_Segment, ...], annotation: _Annotation, rewrites: list[Rewrite] | None,
    pause_boundaries: tuple[int, ...] = (),
) -> None:
    """제20항 단서의 독립 명사와 ㄹ 계열 후행 성분 경계를 보존한다."""

    suffixes = {"란", "량", "력", "령", "례", "로", "론", "료", "류"}
    for following in annotation._tokens_starting_at.values():
        right = following.normalized_start
        previous = annotation.ending_at(right)
        whole_origin = SINO_ORIGINS.get(previous.form + following.form) if previous is not None else None
        confirmed_boundary = (
            _tag_has_prefix(following.tag, "XSN") and following.form in suffixes
            or right in annotation.nasal_liquid_boundaries
            or (
                previous is not None and any(
                    licenses_nominal_attachment(
                        base_form=previous.form, base_tag=previous.tag,
                        tail_form=following.form, tail_tag=following.tag,
                        verified_base=previous.form in SINO_KOREAN_LEXEMES,
                        expected_tail_form=attachment.form, expected_tail_tag=attachment.tag,
                        nasal_liquid=attachment.nasal_liquid,
                        whole_hanja_compatible=whole_origin is None or any(
                            variant.endswith(attachment.hanja) for variant in whole_origin.hanja_variants
                        ),
                    )
                    for attachment in SINO_ATTACHMENTS
                )
            )
        )
        if (previous is None or len(previous.form) < 2 or not _tag_has_prefix(previous.tag, "NN")
            or not confirmed_boundary):
            continue
        left_token, right_token = units[right - 1].syllable, units[right].syllable
        if left_token is None or right_token is None or left_token.coda != "ㄴ" or right_token.onset != "ㄹ":
            continue
        if _has_phonological_barrier(
            units, right - 1, right, segments, pause_boundaries,
        ):
            continue
        before = _trace_before(rewrites, units, right - 1, right)
        units[right].syllable = right_token.changed(onset="ㄴ")
        _record(rewrites, units, right - 1, right, before, "ko.liquid.suffix.20")


def _apply_compound_n_insertion(
    units: list[_Unit], candidate: _MorphologyCandidate, annotation: _Annotation,
    segments: tuple[_Segment, ...], rewrites: list[Rewrite] | None,
) -> None:
    """제29·30항의 복합어·접미사·반복어 경계에서만 ㄴ을 첨가한다."""

    left, right = candidate.left, candidate.right
    left_token, right_token = units[left].syllable, units[right].syllable
    if (left_token is None or right_token is None or left_token.coda is None
        or right_token.onset != "ㅇ" or right_token.vowel not in _N_INSERTION_VOWELS):
        return
    if _is_verified_non_n_insertion_boundary(units, left, right, annotation, segments):
        _apply_representative_coda_before_no_insertion_vowel(units, left, right, rewrites)
        return

    previous, following = annotation.ending_at(left + 1), annotation.starting_at(right)
    saisiot = previous is not None and (
        _tag_has_prefix(previous.tag, "Z_SIOT")
        or previous.form in SAISIOT_COMBINING_FORMS and _tag_has_prefix(previous.tag, "NNG")
    )
    containing = annotation.covering(left)
    repeated = containing is not None and _tag_has_prefix(containing.tag, "MAG") and (
        len(containing.form) % 2 == 0
        and right == containing.normalized_start + len(containing.form) // 2
        and containing.form[:len(containing.form) // 2] == containing.form[len(containing.form) // 2:]
    )
    compound = False
    if previous is not None and following is not None:
        compound = licenses_n_insertion(
            left_form=previous.form, left_tag=previous.tag,
            right_form=following.form, right_tag=following.tag,
            declared_boundary=right in annotation.compound_boundaries,
            saisiot=saisiot,
        )
    if not (compound or repeated):
        return
    before = _trace_before(rewrites, units, left, right)
    units[right].syllable = right_token.changed(onset="ㄴ")
    rule_id = "ko.saisiot.30" if saisiot else "ko.n_insertion.reduplication" if repeated else "ko.n_insertion.compound"
    _record(rewrites, units, left, right, before, rule_id)


def _is_verified_non_n_insertion_boundary(
    units: list[_Unit], left: int, right: int, annotation: _Annotation,
    segments: tuple[_Segment, ...], *, crossed_space: bool = False,
) -> bool:
    """선언한 어휘 경계의 ㄴ 비첨가만 허용한다."""

    if crossed_space:
        return _is_verified_component_non_n_insertion_boundary(
            units, left, right, True, annotation, segments,
        )

    for word in NO_N_INSERTION_LEXEMES:
        start = annotation.text.find(
            word,
            max(0, left - len(word) + 1),
            min(len(annotation.text), left + len(word)),
        )
        if start < 0:
            continue
        end = start + len(word)
        if (
            not start <= left < right < end
            or right != left + 1
            or _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments)
        ):
            continue
        boundaries = [
            offset for offset in range(start, end - 1)
            if units[offset].syllable is not None
            and units[offset + 1].syllable is not None
            and units[offset].syllable.coda is not None
            and units[offset + 1].syllable.onset == "ㅇ"
            and units[offset + 1].syllable.vowel in _N_INSERTION_VOWELS
        ]
        if boundaries != [left]:
            continue
        previous = annotation.ending_at(left + 1)
        following = annotation.starting_at(right)
        visible_parts = (
            previous is not None and following is not None
            and previous.normalized_start >= start and following.normalized_end <= end
            and not any(
                _tag_has_prefix(token.tag, tag)
                for token in (previous, following) for tag in ("J", "E")
            )
        )
        covering = annotation.covering(left)
        whole_nominal = (
            covering is not None and annotation.covering(right) == covering
            and covering.normalized_start == start and covering.normalized_end == end
            and _tag_has_prefix(covering.tag, "NNG")
            and not any(_tag_has_prefix(covering.tag, tag) for tag in ("J", "E"))
        )
        if visible_parts or whole_nominal:
            return True
    return False


def _apply_representative_coda_before_no_insertion_vowel(
    units: list[_Unit], left: int, right: int, rewrites: list[Rewrite] | None,
) -> None:
    """ㄴ은 보태지 않고 받침 대표음만 정한 뒤 일반 연음에 넘긴다."""

    token = units[left].syllable
    assert token is not None and token.coda is not None
    transition = CODA_TRANSITIONS.get(token.coda)
    if transition is None or transition.target == token.coda:
        return
    before = _trace_before(rewrites, units, left, right)
    units[left].syllable = token.changed(coda=transition.target)
    _record(rewrites, units, left, right, before, "ko.liaison.lexical")


def _apply_confirmed_palatalization(
    units: list[_Unit], candidate: _MorphologyCandidate,
    annotation: _Annotation, rewrites: list[Rewrite] | None,
    segments: tuple[_Segment, ...],
    pause_boundaries: tuple[int, ...] = (),
) -> None:
    """조사·접미사·활용형의 경계를 확인한 경우에만 구개음화한다."""

    left, right = candidate.left, candidate.right
    containing = annotation.covering(left)
    lexical_derivation = _has_licensed_lexical_palatalization_boundary(
        units, segments, annotation, left, right, containing, pause_boundaries,
    )
    # 생산적 조사·접미사 권한은 공통 경계 소비자가 이미 판정했다.
    if not lexical_derivation:
        return
    token, next_token = units[left].syllable, units[right].syllable
    assert token is not None and next_token is not None
    before = _trace_before(rewrites, units, left, right)
    units[left].syllable = token.changed(coda="ㄹ" if token.coda == "ㄾ" else None)
    onset = "ㅈ" if token.coda == "ㄷ" and next_token.onset == "ㅇ" else "ㅊ"
    units[right].syllable = next_token.changed(onset=onset)
    _record(rewrites, units, left, right, before, "ko.palatalization")


def _has_licensed_lexical_palatalization_boundary(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    annotation: _Annotation,
    left: int,
    right: int,
    containing: AnalysisToken | None,
    pause_boundaries: tuple[int, ...] = (),
) -> bool:
    """선언한 접두·접미 경계와 정확 owner 경계를 공통 비교기로 찾는다."""
    if containing is not None:
        boundary_offset = right - containing.normalized_start
        if any(
            feature.scope in {"prefix", "suffix"}
            for feature in matching_palatalization_boundaries(
                containing.form, boundary_offset,
            )
        ):
            return True

    # Exact 명사 속성은 source 범위를 먼저 확인하고 원 분석 품사를 그대로 둔다.
    original_tokens = tuple(annotation._tokens_starting_at.values())
    text = annotation.text
    for feature in PALATALIZATION_BOUNDARIES:
        if feature.scope != "exact":
            continue
        start = right - feature.offset
        end = start + len(feature.spelling)
        if (
            start < 0
            or end > len(text)
            or text[start:end] != feature.spelling
            or not feature.matches(text[start:end], right - start)
        ):
            continue
        if not all(
            units[index].handler is Handler.KOREAN
            and units[index].syllable is not None
            for index in range(start, end)
        ) or _has_hard_boundary(
            units[start].segment_index, units[end - 1].segment_index, segments,
        ):
            continue
        if not (
            _valid_exact_structure_owner(text, start, end, feature, original_tokens)
            or _valid_exact_owner_with_particle_tail(
                text, start, end, feature, original_tokens,
            )
        ):
            continue
        return True
    return False


def _valid_exact_owner_with_particle_tail(
    text: str,
    start: int,
    end: int,
    feature: PalatalizationBoundary,
    original_tokens: tuple[AnalysisToken, ...],
) -> bool:
    """하나의 분석 token에 붙은 조사도 원 morpheme 정렬이 맞을 때만 허용한다."""
    if (
        not feature.owner_pos
        or not feature.owner_pos <= {"NNG", "NNP"}
        or not 0 <= start < end <= len(text)
        or text[start:end] != feature.spelling
        or _has_adjacent_nominal_fragment(original_tokens, start, on_left=True)
    ):
        return False

    overlapping = tuple(
        token for token in original_tokens
        if token.normalized_start < end and start < token.normalized_end
    )
    if len(overlapping) != 1:
        return False
    token = overlapping[0]
    if token.normalized_start != start or token.normalized_end <= end:
        return False
    morphemes = token.morphemes
    if not morphemes or "".join(form for form, _ in morphemes) != token.form:
        return False
    if tuple(tag for _, tag in morphemes) != tuple(token.tag.split("+")):
        return False

    cursor = start
    owner_parts: list[tuple[str, str]] = []
    tail_parts: list[tuple[str, str]] = []
    for form, tag in morphemes:
        next_cursor = cursor + len(form)
        if next_cursor <= end and not tail_parts:
            owner_parts.append((form, tag))
        elif cursor >= end and tag.startswith("J"):
            tail_parts.append((form, tag))
        else:
            return False
        cursor = next_cursor
    if cursor != token.normalized_end or not owner_parts or not tail_parts:
        return False
    if "".join(form for form, _ in owner_parts) != feature.spelling:
        return False
    if len(owner_parts) == 1:
        if owner_parts[0][1] not in feature.owner_pos:
            return False
    elif "NNG" not in feature.owner_pos or any(tag != "NNG" for _, tag in owner_parts):
        return False
    return True


def _letter_name_onset(annotation: _Annotation, left: int, right: int) -> str | None:
    """기존 제16항의 정확한 이름·조사 소유 조건을 한 번 공유한다."""
    noun = annotation.ending_at(left + 1)
    particle = annotation.starting_at(right)
    if noun is None or particle is None or not any(
        _tag_has_prefix(particle.tag, tag) for tag in ("J", "VCP")
    ):
        return None
    return _LETTER_NAME_CODAS.get(noun.form.removeprefix("쌍"))


def _apply_letter_name_liaison(
    units: list[_Unit], candidate: _MorphologyCandidate,
    annotation: _Annotation, rewrites: list[Rewrite] | None,
) -> None:
    """제16항 자모 이름의 예외 받침을 모든 모음 조사 앞에서 연음한다."""
    onset = _letter_name_onset(annotation, candidate.left, candidate.right)
    if onset is None:
        return
    left, right = units[candidate.left], units[candidate.right]
    assert left.syllable is not None and right.syllable is not None
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    left.syllable = left.syllable.changed(coda=None)
    right.syllable = right.syllable.changed(onset=onset)
    _record(rewrites, units, candidate.left, candidate.right, before, "ko.letter_name.16")


def _apply_word_n_insertion(
    units: list[_Unit], candidate: _MorphologyCandidate,
    annotation: _Annotation, segments: tuple[_Segment, ...], rewrites: list[Rewrite] | None,
    pause_boundaries: tuple[int, ...] = (),
) -> None:
    """제29항 붙임 2에 따라 이어 읽는 두 단어의 ㄴ을 첨가한다."""

    previous = annotation.ending_at(candidate.left + 1)
    following = annotation.starting_at(candidate.right)
    if previous is None or following is None:
        return
    if _is_verified_non_n_insertion_boundary(
        units, candidate.left, candidate.right, annotation, segments,
        crossed_space=candidate.crossed_space,
    ):
        _prepare_lexical_liaison(units, candidate, annotation, rewrites, segments, pause_boundaries)
        return
    if _tag_has_prefix(previous.tag, "NR"):
        return
    if not _is_independent_word_n_insertion_target(
        following, annotation=annotation, units=units, segments=segments,
        pause_boundaries=pause_boundaries,
    ):
        return
    right = units[candidate.right]
    assert right.syllable is not None
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    right.syllable = right.syllable.changed(onset="ㄴ")
    _record(rewrites, units, candidate.left, candidate.right, before, "ko.n_insertion.word")


def _is_particle_only_tag(tag: str) -> bool:
    """결합 태그가 조사 성분만 포함하는지 확인한다."""

    parts = tuple(part.strip() for part in tag.split("+"))
    return bool(parts) and all(part.startswith("J") for part in parts)


def _owns_component_with_licensed_tail(token: AnalysisToken, form: str, tag: str) -> bool:
    """분석 token이 정확한 명사와 조사 또는 긍정 계사-어미만 소유하는지 확인한다."""

    if token.form == form and token.tag == tag:
        return True
    morphemes = token.morphemes
    tail = morphemes[1:]
    if (
        not morphemes
        or morphemes[0] != (form, tag)
        or not token.form.startswith(form)
    ):
        return False
    tag_parts = tuple(part.strip() for part in token.tag.split("+"))
    if tag_parts != tuple(morpheme_tag for _, morpheme_tag in morphemes):
        return False
    source_tail = token.form[len(form):]
    particle_tail = (
        all(_is_particle_only_tag(morpheme_tag) for _, morpheme_tag in tail)
        and "".join(morpheme_form for morpheme_form, _ in tail) == source_tail
    )
    if parse_parts(morphemes).lexical_status != "eligible":
        return False
    return particle_tail or _matches_positive_copula_tail(
        source_tail, tail,
        vowel_final_nominal=_is_vowel_final_nominal_source(form),
    )


def _is_verified_component_non_n_insertion_boundary(
    units: list[_Unit], left: int, right: int, crossed_space: bool,
    annotation: _Annotation, segments: tuple[_Segment, ...],
) -> bool:
    """선언한 두 명사 성분의 공백 경계에서만 ㄴ 비첨가를 허용한다."""

    if not crossed_space or left >= len(units) or right >= len(units):
        return False
    if _has_hard_boundary(
        units[left].segment_index, units[right].segment_index, segments,
    ):
        return False
    previous = annotation.ending_at(left + 1)
    following = annotation.starting_at(right)
    if (
        previous is None or following is None
        or previous.normalized_end != left + 1
        or following.normalized_start != right
    ):
        return False
    separator = annotation.text[previous.normalized_end:following.normalized_start]
    if not separator or any(character != " " for character in separator):
        return False

    for left_form, left_tag, right_form, right_tag in NO_N_INSERTION_COMPONENT_BOUNDARIES:
        if (
            previous.form != left_form or previous.tag != left_tag
            or previous.normalized_start != left + 1 - len(left_form)
            or annotation.text[previous.normalized_start:previous.normalized_end] != left_form
            or following.normalized_end < right + len(right_form)
            or annotation.text[right:right + len(right_form)] != right_form
            or not _owns_component_with_licensed_tail(following, right_form, right_tag)
        ):
            continue
        if not _has_licensed_nominal_tail(
            annotation, right + len(right_form), following, right_form,
        ):
            continue
        return True
    return False


def _nominal_tail_valid(
    annotation: _Annotation, component_end: int, owner: AnalysisToken, component_form: str, *, internal_properties=False,
) -> bool:
    """이미 소유한 명사 바깥의 전체 꼬리를 표면 사실과 공유 문법으로 확인한다."""

    parts, surface, observed = (), "", []
    cursor = component_end
    if owner.normalized_end > component_end:
        if (not owner.morphemes or owner.morphemes[0][0] != component_form
                or tuple(owner.tag.split("+")) != tuple(tag for _, tag in owner.morphemes)
                or not owner.form.startswith(component_form)):
            return False
        parts, surface = owner.morphemes[1:], owner.form[len(component_form):]
        observed.append(owner)
        cursor = owner.normalized_end
    while cursor < len(annotation.text) and annotation.text[cursor].isalnum():
        token = annotation.starting_at(cursor)
        if (token is None or token.normalized_start != cursor
                or not cursor < token.normalized_end <= len(annotation.text)
                or token.form != annotation.text[cursor:token.normalized_end]
                or any(annotation.covering(i) != token for i in range(cursor, token.normalized_end))):
            return False
        own = token.morphemes or ((token.form, token.tag),)
        if tuple(tag for _, tag in own) != tuple(token.tag.split("+")) or any(not form for form, _ in own):
            return False
        parts += own
        surface += token.form
        observed.append(token)
        cursor = token.normalized_end
    if not parts:
        return True
    grammar = parse_parts(parts, initial_host="nominal")
    conflicts = [token for token in observed
                 if verified_token_surface(token) is None and surface_proof_conflict(token)]
    if conflicts and not (grammar.lexical_status == "eligible" and parts[0] == ("이", "VCP")
            and _matches_positive_copula_tail(surface, parts,
                vowel_final_nominal=_is_vowel_final_nominal_source(component_form))
            and all(contextual_zero_copula(token, component_end, component_form) for token in conflicts)):
        return False
    if grammar.lexical_status != "eligible":
        return (internal_properties and parts[0] == ("이", "VCP")
                and adnominal_core_evidence(parts, surface, nominal_host_form=component_form) is not None)
    if parts[0] == ("이", "VCP"):
        return _matches_positive_copula_tail(
            surface, parts, vowel_final_nominal=_is_vowel_final_nominal_source(component_form),
        )
    return (all(_is_particle_only_tag(tag) for _, tag in parts)
            and surface == "".join(form for form, _ in parts))


def _has_licensed_nominal_tail(annotation, component_end, owner, component_form):
    """전체 부착 권한은 정상적인 전체 꼬리 문법과 실현을 요구한다."""
    return _nominal_tail_valid(annotation, component_end, owner, component_form)


def _has_intrinsic_nominal_tail(annotation, component_end, owner, component_form):
    """이미 증명한 어근 내부 속성에서만 정확한 핵심과 미해결 JX 바깥 꼬리를 분리한다."""
    return _nominal_tail_valid(annotation, component_end, owner, component_form, internal_properties=True)


def _particle_token_has_truthful_morphemes(token: AnalysisToken) -> bool:
    """후행 조사 token의 형태소열이 실제 표면형과 일치하는지 확인한다."""

    if not _is_particle_only_tag(token.tag):
        return False
    if not token.morphemes:
        return True
    if tuple(part.strip() for part in token.tag.split("+")) != tuple(
        tag for _, tag in token.morphemes
    ) or any(not _is_particle_only_tag(tag) for _, tag in token.morphemes):
        return False
    surface = "".join(
        _COMPATIBILITY_TO_TRAILING_JAMO.get(character, character)
        for form, _ in token.morphemes
        for character in form
    )
    return unicodedata.normalize("NFC", token.form) == unicodedata.normalize("NFC", surface)


def _has_verified_particle_suffix(
    annotation: _Annotation, first: AnalysisToken,
) -> bool:
    """진실한 조사 표면과 명사 숙주에서 허용된 전체 조사 사슬을 확인한다."""

    token, cursor, parts = first, first.normalized_start, ()
    while token is not None and token.normalized_start == cursor:
        if not _particle_token_has_truthful_morphemes(token):
            break
        own = token.morphemes or ((token.form, token.tag),)
        if any("+" in tag for _, tag in own):
            return False
        parts += own
        cursor = token.normalized_end
        token = annotation.starting_at(cursor)
    return (bool(parts) and (token is None or token.tag == "SF")
            and parse_parts(parts, initial_host="nominal").lexical_status == "eligible")


def _analysis_morpheme_parts(token: AnalysisToken) -> tuple[tuple[str, str], ...] | None:
    """tag와 일치하는 형태소열 또는 단일 표면 형태소를 반환한다."""

    if token.morphemes:
        parts = token.morphemes
        if tuple(part.strip() for part in token.tag.split("+")) != tuple(tag for _, tag in parts):
            return None
        return parts
    if token.tag == "VCP" or token.tag in _POSITIVE_COPULA_ENDING_TAGS:
        return ((token.form, token.tag),)
    return None


def _has_separate_positive_copula_chain(
    annotation: _Annotation, first: AnalysisToken, component_form: str,
) -> bool:
    """분리 포장의 계사·어미·조사도 하나의 공유 꼬리 문법으로 확인한다."""

    token, cursor, parts, surface = first, first.normalized_start, (), ""
    while token is not None and token.normalized_start == cursor and token.tag != "SF":
        if token.form != annotation.text[cursor:token.normalized_end]:
            return False
        own = token.morphemes or ((token.form, token.tag),)
        if tuple(tag for _, tag in own) != tuple(token.tag.split("+")):
            return False
        parts += own
        surface += token.form
        cursor = token.normalized_end
        token = annotation.starting_at(cursor)
    return ((token is None or token.tag == "SF") and _matches_positive_copula_tail(
        surface, parts, vowel_final_nominal=_is_vowel_final_nominal_source(component_form),
    ))


def _prepare_lexical_liaison(
    units: list[_Unit], candidate: _MorphologyCandidate,
    annotation: _Annotation, rewrites: list[Rewrite] | None,
    segments: tuple[_Segment, ...], pause_boundaries: tuple[int, ...] = (),
) -> None:
    """실질 형태소 앞에서는 제15항의 대표음화를 일반 연음보다 먼저 적용한다."""

    following = annotation.starting_at(candidate.right)
    preceding = annotation.ending_at(candidate.left + 1)
    if following is None or preceding is None:
        return
    eligible = (lexical_liaison_target(annotation, candidate.right, units, segments, pause_boundaries)
                if candidate.crossed_space else lexical_component_liaison_target(
                    annotation, candidate.left, candidate.right, units, segments, pause_boundaries))
    if not eligible:
        return
    left, right = candidate.left, candidate.right
    token, next_token = units[left].syllable, units[right].syllable
    assert token is not None and next_token is not None
    if token.coda is None or token.coda == "ㅇ" or next_token.onset != "ㅇ":
        return
    transition = CODA_TRANSITIONS.get(token.coda)
    onset = transition.target if transition else token.coda
    before = _trace_before(rewrites, units, left, right)
    units[left].syllable = token.changed(coda=None)
    units[right].syllable = next_token.changed(onset=onset)
    _record(rewrites, units, left, right, before, "ko.liaison.lexical")


def _apply_lexical_liaisons(
    units: list[_Unit], segments: tuple[_Segment, ...],
    annotation: _Annotation | None, rewrites: list[Rewrite] | None,
    pause_boundaries: tuple[int, ...] = (),
    reading_relations: Mapping[tuple[int, int], str] | None = None,
    formal_decisions: dict | None = None,
    blocked_pairs: frozenset[tuple[int, int]] = frozenset(),
) -> None:
    """어휘 발음 보완 뒤의 받침도 실질 형태소 앞에서 대표음으로 연결한다."""

    if annotation is None:
        return
    for left, unit in enumerate(units):
        if unit.syllable is None or unit.syllable.coda is None:
            continue
        neighbor = _next_syllable(units, segments, left)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        if (left, right) in blocked_pairs:
            continue
        if (left, right) in (formal_decisions or {}):
            continue
        if _has_phonological_barrier(
            units, left, right, segments, pause_boundaries,
        ):
            continue
        following = units[right].syllable
        assert following is not None
        selected_ordinary = (reading_relations or {}).get((left, right)) == "ordinary_liaison"
        if following.onset == "ㅇ" and (following.vowel in _LEXICAL_LIAISON_VOWELS or selected_ordinary):
            candidate = _MorphologyCandidate(("ko.liaison.lexical",), left, right, crossed_space)
            _prepare_lexical_liaison(units, candidate, annotation, rewrites, segments, pause_boundaries)


def _apply_ending_tensing_27(
    units: list[_Unit], candidate: _MorphologyCandidate,
    annotation: _Annotation, rewrites: list[Rewrite] | None,
) -> None:
    """붙여 쓴 -(으)ㄹ 어미 내부도 관형형과 같은 된소리를 적용한다."""

    containing = annotation.covering(candidate.left)
    following = annotation.covering(candidate.right)
    if containing is None or following is None:
        return
    coda_owner = ending_coda_owner(containing, candidate.left)
    onset_owner = source_owner(following, candidate.right, "onset")
    ending = coda_owner is not None and onset_owner is not None and (
        _tag_has_prefix(onset_owner.tag, "E")
        or onset_owner.form in _RIEUL_ENDING_TAILS
        and any(_tag_has_prefix(onset_owner.tag, tag) for tag in ("JX", "NNB"))
        or _tag_has_prefix(coda_owner.tag, "ETM") and _tag_has_prefix(onset_owner.tag, "NN")
    )
    # ‘갈수록’처럼 어미가 결합한 전체가 부사로 굳어진 경우에도 같은 경계를 쓴다.
    lexicalized_ending = containing == following and _tag_has_prefix(containing.tag, "MAG") and (
        annotation.text[candidate.right:containing.normalized_end] in _RIEUL_ENDING_TAILS
    )
    if not (ending or lexicalized_ending):
        return
    right = units[candidate.right]
    token = right.syllable
    assert token is not None
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    right.syllable = token.changed(onset=TENSE_ONSET[token.onset])
    _record(rewrites, units, candidate.left, candidate.right, before, "ko.ending.tensing.27")


def _apply_particle_ui(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
    annotation: _Annotation,
    rewrites: list[Rewrite] | None,
) -> None:
    unit = units[candidate.left]
    token = unit.syllable
    assert token is not None
    item = annotation.starting_at(candidate.left)
    scalar_particle = (
        item is not None
        and item.normalized_end == candidate.left + 1
        and _tag_has_prefix(item.tag, "J")
    )
    if not scalar_particle:
        item = annotation.covering(candidate.left)
        # 물리 토큰 포장과 무관하게 전체 증명 안의 정확한 조사 중성만 소비한다.
        if item is None or verified_token_surface(item) is None:
            return
        owner = source_owner(item, candidate.left, "vowel")
        if owner is None or owner.form != "의" or not _tag_has_prefix(owner.tag, "J"):
            return
    before = unit.text if rewrites is not None else ""
    unit.syllable = token.changed(vowel="ㅔ")
    _record(rewrites, units, candidate.left, candidate.left, before, RULES["ko.ui.particle"].id)


def _is_verb_stem_before_ending(
    annotation: _Annotation,
    left: int,
    right: int,
    *,
    units=None,
    segments=None,
    pause_boundaries: tuple[int, ...] = (),
) -> bool:
    if annotation is None:
        return False
    following = annotation.starting_at(right)
    # 명사 파생 -기는 어간의 된소리를 보존한다. 사동·피동 -기-/XSV는
    # 포함하지 않아 안기다·감기다·옮기다를 과잉 경음화하지 않는다.
    if _has_tag_ending_at(annotation, left + 1, "V") and following is not None:
        return _tag_has_prefix(following.tag, "E") or (
            following.form == "기" and _tag_has_prefix(following.tag, "XSN"))
    if (units is None or segments is None or isinstance(left, bool) or isinstance(right, bool)
            or not isinstance(left, int) or not isinstance(right, int) or right != left + 1
            or not 0 <= left < right < len(annotation.text) or len(units) != len(annotation.text)
            or any(units[offset].handler is not Handler.KOREAN or units[offset].syllable is None
                   for offset in (left, right))
            or _has_phonological_barrier(units, left, right, segments, pause_boundaries)):
        return False
    containing = annotation.covering(left)
    if (containing is None or annotation.covering(right) != containing
            or not containing.morphemes or not containing.morpheme_spans):
        return False
    proof = verified_token_surface(containing)
    if proof is None:
        return False
    start = left
    while start and annotation.text[start - 1].isalnum():
        start -= 1
    # 휴지는 실제 쌍에서 검사한다. 먼 휴지를 전체 문법의 실패로 바꾸지 않는다.
    certificate = certify_word(annotation, start, units, segments, ())
    if (certificate.scope != "word" or certificate.authority_kind != "complete_scope"
            or certificate.lexical_status != "eligible" or certificate.grammar_status != "eligible"
            or certificate.surface_status != "verified"):
        return False
    shift, located = 0, False
    for member in certificate.surface_proofs:
        if member == proof:
            located = True
            break
        shift += len(member.parts)
    if not located:
        return False
    donor = next((atom for atom in proof.atoms if atom.offset == left and atom.role == "coda"), None)
    recipient = next((atom for atom in proof.atoms if atom.offset == right and atom.role == "onset"), None)
    if donor is None or recipient is None or len(donor.origins) != 1 or len(recipient.origins) != 1:
        return False
    origin, receiver = donor.origins[0], recipient.origins[0]
    if (origin.role != "coda" or receiver.role != "onset" or donor.jamo != origin.jamo
            or recipient.jamo != receiver.jamo or receiver.occurrence != origin.occurrence + 1
            or not 0 <= origin.occurrence < receiver.occurrence < len(proof.parts)):
        return False
    stem, stem_tag = proof.parts[origin.occurrence]
    ending, ending_tag = proof.parts[receiver.occurrence]
    if (_base_tag(stem_tag) not in {"VV", "VA", "VX"}
            or origin.source_offset != len(stem) - 1 or receiver.source_offset != 0):
        return False
    parts = certificate.parts
    stem_index, ending_index = shift + origin.occurrence, shift + receiver.occurrence
    if parts[stem_index:ending_index + 1] != ((stem, stem_tag), (ending, ending_tag)):
        return False
    grammar = parse_parts(parts)
    if grammar.lexical_status != "eligible":
        return False
    boundary = grammar.boundaries[ending_index]
    if ending_tag in _SHARED_ENDINGS:
        return boundary.inflection and stem_index >= boundary.stem_start
    if (ending, ending_tag) != ("기", "XSN") or boundary.causative:
        return False
    before = parse_parts(parts[:ending_index])
    nominal = parse_parts(parts[:ending_index + 1])
    return (before.lexical_status == "eligible" and before.host_state == "predicate"
            and nominal.lexical_status == "eligible" and nominal.derived
            and nominal.final_category == "noun" and nominal.host_state == "nominal"
            and nominal.tail_state == "derivation")


def _apply_rieul_giyeok_stem(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
    annotation: _Annotation,
    rewrites: list[Rewrite] | None,
    *,
    verified_internal: bool = False,
) -> None:
    if not verified_internal and not _is_verb_stem_before_ending(annotation, candidate.left, candidate.right):
        return
    left = units[candidate.left]
    right = units[candidate.right]
    token = left.syllable
    next_token = right.syllable
    if token is None or next_token is None or token.coda != "ㄺ" or next_token.onset != "ㄱ":
        return
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    left.syllable = token.changed(coda="ㄹ")
    right.syllable = next_token.changed(onset="ㄲ")
    _record(
        rewrites,
        units,
        candidate.left,
        candidate.right,
        before,
        RULES["ko.stem.rieul_giyeok"].id,
    )


def _apply_stem_tensing_24(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
    annotation: _Annotation,
    rewrites: list[Rewrite] | None,
    *,
    verified_internal: bool = False,
) -> None:
    if not verified_internal and not _is_verb_stem_before_ending(annotation, candidate.left, candidate.right):
        return
    left = units[candidate.left]
    right = units[candidate.right]
    token = left.syllable
    next_token = right.syllable
    if (token is None or next_token is None or token.coda not in {"ㄴ", "ㄵ", "ㅁ", "ㄻ"}
            or next_token.onset not in {"ㄱ", "ㄷ", "ㅅ", "ㅈ"}):
        return
    coda = {"ㄴ": "ㄴ", "ㄵ": "ㄴ", "ㅁ": "ㅁ", "ㄻ": "ㅁ"}[token.coda or ""]
    tense = TENSE_ONSET.get(next_token.onset)
    if tense is None:
        return
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    left.syllable = token.changed(coda=coda)
    right.syllable = next_token.changed(onset=tense)
    _record(
        rewrites,
        units,
        candidate.left,
        candidate.right,
        before,
        RULES["ko.stem.tensing.24"].id,
    )


def _apply_stem_tensing_25(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
    annotation: _Annotation,
    rewrites: list[Rewrite] | None,
    *,
    verified_internal: bool = False,
) -> None:
    if not verified_internal and not _is_verb_stem_before_ending(annotation, candidate.left, candidate.right):
        return
    left = units[candidate.left]
    right = units[candidate.right]
    token = left.syllable
    next_token = right.syllable
    if (token is None or next_token is None or token.coda not in {"ㄼ", "ㄾ"}
            or next_token.onset not in {"ㄱ", "ㄷ", "ㅅ", "ㅈ"}):
        return
    tense = TENSE_ONSET.get(next_token.onset)
    if tense is None:
        return
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    left.syllable = token.changed(coda="ㄹ")
    right.syllable = next_token.changed(onset=tense)
    _record(
        rewrites,
        units,
        candidate.left,
        candidate.right,
        before,
        RULES["ko.stem.tensing.25"].id,
    )


def _apply_modifier_tensing_27(
    units: list[_Unit],
    candidate: _MorphologyCandidate,
    annotation: _Annotation,
    rewrites: list[Rewrite] | None,
) -> None:
    containing = annotation.ending_at(candidate.left + 1)
    owner = ending_coda_owner(containing, candidate.left) if containing is not None else None
    if owner is None or not _tag_has_prefix(owner.tag, "ETM"):
        return
    right = units[candidate.right]
    next_token = right.syllable
    assert next_token is not None
    tense = TENSE_ONSET.get(next_token.onset)
    if tense is None:
        return
    before = _trace_before(rewrites, units, candidate.left, candidate.right)
    right.syllable = next_token.changed(onset=tense)
    _record(
        rewrites,
        units,
        candidate.left,
        candidate.right,
        before,
        RULES["ko.modifier.tensing.27"].id,
    )
