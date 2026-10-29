"""경계와 trace를 보존하는 첫 한국어 음운 엔진이다."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import StringIO

from ..analyzer import KiwiAnalyzer
from ..merge import _TextSegment
from ..model import (
    Diagnostic,
    Handler,
    OutputSegment,
    Rewrite,
    SourceSpan,
)
from ._shared import (
    _Segment,
    _Unit,
    _RewriteLog,
    _has_hard_boundary,
    _is_blocked_pair,
    _has_phonological_barrier,
    _is_blocked_phonological_pair,
    _next_syllable,
    _pair_text,
    _record,
    _trace_before,
)
from .hangul import character_source_spans, decompose_syllable, is_modern_syllable
from .morphology import _Annotation, _apply_lexical_liaisons, _apply_morphology_rules
from .official import LEXICAL_PRONUNCIATIONS, NOUN_ONLY_PRONUNCIATIONS
from .rules import (
    CODA_TRANSITIONS,
    HIEUH_ASSIMILATION,
    HIEUH_FINALS,
    HIEUH_REMAINDER,
    LIAISON_CLUSTER,
    NASAL_CODA,
    PALATAL_J_ONSETS,
    PALATAL_J_VOWELS,
    RULES,
    TENSE_ONSET,
)
from ..validation import normalize_pause_boundaries
from ..reading_conditions import ReadingBoundaryExecution, _MappedReadingBoundary
from .reading_conditions import plan_reading_conditions, finish_reading_conditions
from .formal_attachment import apply_formal_attachments
from .boundary_consumers import apply_rule_boundaries


_SINO_N_INSERTION_LEFT = frozenset({"십", "백", "천", "만", "억"})
_NATIVE_N_INSERTION_LEFT = frozenset({"열", "물", "른", "흔", "쉰", "순", "든"})
# 문자열 경로의 토큰은 유효성 검사에만 필요한 하나의 빈 span을 공유한다.
_NO_PROVENANCE = (SourceSpan(0, 0, "", 0),)


@dataclass(frozen=True, slots=True)
class _LexicalPronunciation:
    """원문 어절 또는 확인한 형태소 범위의 어휘 발음 후보다."""

    left: int
    right: int
    pronunciation: str
    rule_id: str = "ko.lexical.verified"


@dataclass(frozen=True, slots=True)
class _Pronunciation:
    """내장 음운 규칙이 파이프라인에 넘기는 최소 결과다."""

    segments: tuple[OutputSegment, ...]
    rewrites: tuple[Rewrite, ...]
    diagnostics: tuple[Diagnostic, ...]
    condition_executions: tuple[ReadingBoundaryExecution, ...] = ()

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)


def pronounce(
    segments: Sequence[OutputSegment],
    *,
    pause_boundaries: Iterable[int] = (),
    reading_conditions: tuple[_MappedReadingBoundary, ...] = (),
) -> _Pronunciation:
    """정규화 segment에 한국어 음운 규칙과 확인한 형태소 문맥을 적용한다.

    ``HARD`` 경계와 한국어 이외 segment는 절대로 넘지 않는다. 공백은 보존하되,
    문장부호는 음운 이웃 관계를 끊는다. 형태소 분석에 실패하면 의존 규칙을
    차단하고 해당 원문 범위에 진단을 남긴다.
    """

    items = tuple(segments)
    pauses = normalize_pause_boundaries(
        pause_boundaries,
        sum(len(segment.text) for segment in items),
    )
    condition_executions: list[ReadingBoundaryExecution] = []
    units, rewrites, diagnostics = _run_rules(
        items,
        trace=True,
        pause_boundaries=pauses,
        reading_conditions=reading_conditions,
        condition_executions=condition_executions,
    )
    assert rewrites is not None
    pronunciation_segments = _render_segments(units, items)
    return _Pronunciation(pronunciation_segments, tuple(rewrites), tuple(diagnostics), tuple(condition_executions))


def pronounce_text(
    segments: Sequence[_TextSegment],
    *,
    pause_boundaries: Iterable[int] = (),
) -> str:
    """상세 추적 없이 동일한 음운 규칙을 적용한 발음 문자열을 반환한다."""

    # 이전 상세 경로도 빈 조각을 생략했으므로 경계 판정을 같은 입력으로 수행한다.
    items = tuple(item for item in segments if item.text)
    pauses = normalize_pause_boundaries(
        pause_boundaries,
        sum(len(segment.text) for segment in items),
    )
    units, _, _ = _run_rules(items, trace=False, pause_boundaries=pauses)
    return "".join(unit.text for unit in units)


def _run_rules(
    items: tuple[_Segment, ...],
    *,
    trace: bool,
    pause_boundaries: tuple[int, ...] = (),
    reading_conditions: tuple[_MappedReadingBoundary, ...] = (),
    condition_executions: list[ReadingBoundaryExecution] | None = None,
) -> tuple[list[_Unit], list[Rewrite] | None, list[Diagnostic]]:
    """두 출력 경로에 같은 순서와 같은 음운 규칙을 실행한다."""

    text = "".join(item.text for item in items)
    units = _build_units(items, trace=trace)
    rewrites: list[Rewrite] | None = _RewriteLog() if trace else None
    plan = plan_reading_conditions(units, items, reading_conditions, pause_boundaries)
    pause_boundaries = plan.pauses

    lexical_matches = _collect_exact_lexical_pronunciations(units, items)
    # 구개음화는 종성+ㅎ 격음화보다 먼저 판정해야 ‘굳히다’를 [구치다]로 만든다.
    morphology_kwargs = {"reading_relations": plan.relations} if plan.relations else {}
    formal_decisions = {} if plan.relations else None
    boundary_decisions = []
    def prepare_sounds():
        # 형식 경계는 원문 결정을 먼저 고정하고 제10항 어휘 단순화를 미룬다.
        _apply_consonant_ui(units, rewrites)
        _apply_balb_neolb(units, items, rewrites, pause_boundaries,
            frozenset(left for (left, _), decision in (formal_decisions or {}).items()
                      if decision.kind == "formal" and decision.status == "selected"
                      and decision.applicability == "eligible")
            | frozenset(decision.pair[0] for decision in boundary_decisions
                        if decision.status == "verified" and decision.applicability == "eligible"))
    diagnostics, blocked_pairs, blocked_units, annotation = _apply_morphology_rules(
        text, units, items, KiwiAnalyzer(), rewrites, trace=trace,
        pause_boundaries=pause_boundaries, formal_decisions=formal_decisions,
        boundary_decisions=boundary_decisions, before_rules=prepare_sounds, **morphology_kwargs,
    )
    lexical_matches += _collect_morpheme_pronunciations(text, units, items, annotation, lexical_matches)
    # 형태소 규칙으로 결정하지 못한 어휘 내부 발음을 검증된 자료로 보완한다.
    _apply_lexical_pronunciations(units, lexical_matches, rewrites, items, pause_boundaries)
    # 소유·역할은 원문에서 고정하되 살아 있는 정확 예외가 받침을 복원한 뒤 한 번 옮긴다.
    boundary_events = apply_rule_boundaries(boundary_decisions, units, rewrites)
    # 새 문법 미해결은 경쟁 경계 소비만 예약한다. 음절 자체의 받침·비음화는 독립이다.
    reserved_pairs = frozenset(event.boundary.pair for event in boundary_events
                               if event.applicability in {"unresolved", "blocked"})
    formal_events = apply_formal_attachments(formal_decisions or {}, units, rewrites)
    _apply_lexical_liaisons(units, items, annotation, rewrites, pause_boundaries,
                           formal_decisions=formal_decisions, blocked_pairs=blocked_pairs | reserved_pairs, **morphology_kwargs)
    _apply_hieuh_consonants(units, items, rewrites, blocked_pairs | reserved_pairs | frozenset(formal_events),
                           blocked_units, pause_boundaries)
    # 구개음화·격음화로 새로 생긴 ‘쳐’도 같은 호출에서 ‘처’로 실현한다.
    _apply_jyeo(units, rewrites)
    _apply_hieuh_before_vowel(units, items, rewrites, blocked_pairs | reserved_pairs, blocked_units, pause_boundaries)
    _apply_numeral_n_insertion(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    _apply_liaison(units, items, rewrites, blocked_pairs | reserved_pairs, blocked_units, pause_boundaries)
    _apply_cluster_tensification(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    _apply_coda_neutralization(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    _apply_liquid_assimilation(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    _apply_nasalization(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    _apply_tensification(units, items, rewrites, blocked_pairs, blocked_units, pause_boundaries)
    # 연음·경음화 뒤의 현재 성분으로 정규 표기를 확정한다. 이미 바뀐 음절은 건너뛴다.
    _apply_palatal_j_glide(units, rewrites)

    if condition_executions is not None:
        condition_executions.extend(finish_reading_conditions(plan, units, rewrites, annotation, items,
                                                             formal_events=formal_events))

    return units, rewrites, diagnostics


def _build_units(segments: tuple[_Segment, ...], *, trace: bool) -> list[_Unit]:
    units: list[_Unit] = []
    for segment_index, segment in enumerate(segments):
        if trace:
            assert isinstance(segment, OutputSegment)
            provenance = segment.source_spans or ((segment.anchor,) if segment.anchor is not None else ())
            char_spans = character_source_spans(segment.text, provenance)
        else:
            char_spans = None
        # 영어 provenance는 출력 segment에 유지하되, 영문 읽기 규칙으로 생성된 한글만
        # 한국어 음운 이웃으로 취급한다. 미변환 Latin segment에는 적용하지 않는다.
        phonological_handler = (
            Handler.KOREAN
            if segment.handler is Handler.ENGLISH and segment.rule_id in {
                "english.letter_names.v1", "english.conventional.v1",
            }
            else segment.handler
        )
        for offset, character in enumerate(segment.text):
            spans = char_spans[offset] if char_spans is not None else ()
            if phonological_handler is Handler.KOREAN and is_modern_syllable(character):
                units.append(
                    _Unit(
                        segment_index,
                        phonological_handler,
                        spans,
                        syllable=decompose_syllable(character, spans or _NO_PROVENANCE),
                    )
                )
            else:
                units.append(_Unit(segment_index, phonological_handler, spans, raw=character))
    return units


def _render_segments(
    units: list[_Unit],
    segments: tuple[OutputSegment, ...],
) -> tuple[OutputSegment, ...]:
    rendered: list[str] = []
    unit_index = 0
    for segment_index in range(len(segments)):
        buffer = StringIO()
        while unit_index < len(units) and units[unit_index].segment_index == segment_index:
            buffer.write(units[unit_index].text)
            unit_index += 1
        rendered.append(buffer.getvalue())
    return tuple(
        OutputSegment(
            rendered[index],
            segment.source_spans,
            segment.handler,
            segment.reason,
            segment.rule_id,
            segment.boundary_before,
            segment.boundary_after,
            segment.insertion_rule,
            segment.anchor,
        )
        for index, segment in enumerate(segments)
    )


def _collect_exact_lexical_pronunciations(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
) -> tuple[_LexicalPronunciation, ...]:
    """원문에서 남겨 둔 어휘 예외와 정확히 일치하는 한글 어절을 찾는다."""

    matches: list[_LexicalPronunciation] = []
    run_start: int | None = None

    def collect_run(left: int, right: int) -> None:
        word = _pair_text(units, left, right)
        if word in NOUN_ONLY_PRONUNCIATIONS:
            return
        pronunciation = LEXICAL_PRONUNCIATIONS.get(word)
        if pronunciation is None:
            return
        if len(pronunciation) != right - left + 1:
            raise AssertionError("어휘 발음은 표기와 같은 음절 수여야 합니다.")
        matches.append(_LexicalPronunciation(left, right, pronunciation))

    for index, unit in enumerate(units):
        is_korean_syllable = unit.handler is Handler.KOREAN and unit.syllable is not None
        if is_korean_syllable:
            if run_start is None:
                run_start = index
            elif _has_hard_boundary(
                units[index - 1].segment_index,
                unit.segment_index,
                segments,
            ):
                collect_run(run_start, index - 1)
                run_start = index
            continue
        if run_start is not None:
            collect_run(run_start, index - 1)
            run_start = None

    if run_start is not None:
        collect_run(run_start, len(units) - 1)
    return tuple(matches)


def _collect_morpheme_pronunciations(
    text: str, units: list[_Unit], segments: tuple[_Segment, ...],
    annotation: _Annotation | None, exact: tuple[_LexicalPronunciation, ...],
) -> tuple[_LexicalPronunciation, ...]:
    """복합어를 여러 형태소로 분석해도 양 끝의 경계가 확인되면 발음을 보완한다."""

    if annotation is None:
        return ()
    matches: list[_LexicalPronunciation] = []
    occupied = [False] * len(units)
    for item in exact:
        occupied[item.left : item.right + 1] = [True] * (item.right - item.left + 1)
    for word, pronunciation in sorted(LEXICAL_PRONUNCIATIONS.items(), key=lambda item: -len(item[0])):
        start = text.find(word)
        while start >= 0:
            end = start + len(word)
            noun = annotation.starting_at(start)
            noun_confirmed = word not in NOUN_ONLY_PRONUNCIATIONS or (
                noun is not None and noun.form == word
                and all(tag.startswith("NN") for tag in noun.tag.split("+"))
            )
            if (
                noun_confirmed and annotation.starting_at(start) is not None
                and annotation.ending_at(end) is not None
                and not any(occupied[start:end])
                and not _has_hard_boundary(units[start].segment_index, units[end - 1].segment_index, segments)
                and all(unit.syllable is not None for unit in units[start:end])
            ):
                # 조사 앞에서는 어말 대표음 대신 기저 받침으로 연음한다.
                original = decompose_syllable(word[-1], _NO_PROVENANCE)
                final = decompose_syllable(pronunciation[-1], _NO_PROVENANCE)
                transition = CODA_TRANSITIONS.get(original.coda or "")
                replacement = pronunciation
                if transition is not None and final.coda == transition.target:
                    replacement = pronunciation[:-1] + final.changed(coda=original.coda).text
                matches.append(_LexicalPronunciation(start, end - 1, replacement, "ko.official.morpheme"))
                occupied[start:end] = [True] * len(word)
            start = text.find(word, start + 1)
    return tuple(matches)


def _apply_balb_neolb(
    units: list[_Unit], segments: tuple[_Segment, ...], rewrites: list[Rewrite] | None,
    pause_boundaries: tuple[int, ...],
    deferred_donors: frozenset[int] = frozenset(),
) -> None:
    """제10항의 밟- 및 넓죽·넓둥글·넓적 계열을 처리한다."""

    for index, unit in enumerate(units):
        if index in deferred_donors:
            continue
        if unit.text not in {"밟", "넓"} or unit.syllable is None:
            continue
        neighbor = _next_syllable(units, segments, index)
        if unit.text == "밟" and neighbor is not None:
            right, crossed_space = neighbor
            following = units[right].syllable
            assert following is not None
            # ‘밟아’와 ‘밟히다’는 각각 연음·격음화 규칙에서 ㄹ을 보존한다.
            if (
                not crossed_space
                and not _has_phonological_barrier(
                    units, index, right, segments, pause_boundaries,
                )
                and following.onset in {"ㅇ", "ㅎ"}
            ):
                continue
        if unit.text == "넓":
            if neighbor is None or neighbor[1]:
                continue
            tail = "".join(item.text for item in units[index : index + 3])
            prefix = next((word for word in ("넓죽", "넓둥글", "넓적") if tail.startswith(word)), None)
            if prefix is None or _has_phonological_barrier(
                units, index, index + len(prefix) - 1, segments, pause_boundaries,
            ):
                continue
        before = unit.text if rewrites is not None else ""
        unit.syllable = unit.syllable.changed(coda="ㅂ")
        _record(rewrites, units, index, index, before, "ko.lexical.balb_neolb")


def _apply_lexical_pronunciations(
    units: list[_Unit],
    matches: tuple[_LexicalPronunciation, ...],
    rewrites: list[Rewrite] | None,
    segments: tuple[_Segment, ...],
    pause_boundaries: tuple[int, ...],
) -> None:
    """확인한 어휘 범위의 발음을 적용하고 근거 규칙을 기록한다."""

    for match in matches:
        if _has_phonological_barrier(
            units, match.left, match.right, segments, pause_boundaries,
        ):
            continue
        before = _trace_before(rewrites, units, match.left, match.right)
        for unit, character in zip(
            units[match.left : match.right + 1],
            match.pronunciation,
        ):
            unit.syllable = decompose_syllable(character, unit.source_spans or _NO_PROVENANCE)
        _record(
            rewrites,
            units,
            match.left,
            match.right,
            before,
            match.rule_id,
        )


def _apply_jyeo(units: list[_Unit], rewrites: list[Rewrite] | None) -> None:
    """기존 ㅕ 처리 시점과 ko.vowel.jyeo 추적을 유지한다."""

    _apply_palatal_j_glide(units, rewrites, legacy_jyeo=True)


def _apply_palatal_j_glide(
    units: list[_Unit], rewrites: list[Rewrite] | None, *, legacy_jyeo: bool = False,
) -> None:
    """한국어 음운 단위의 경구개음 뒤 j계 모음을 정규 표기로 바꾼다."""

    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or unit.handler is not Handler.KOREAN or token.onset not in PALATAL_J_ONSETS:
            continue
        vowel = PALATAL_J_VOWELS.get(token.vowel)
        if vowel is None or (legacy_jyeo and token.vowel != "ㅕ"):
            continue
        rule_id = "ko.vowel.jyeo" if legacy_jyeo else "ko.vowel.palatal_j_canonical"
        before = unit.text if rewrites is not None else ""
        unit.syllable = token.changed(vowel=vowel)
        _record(rewrites, units, index, index, before, RULES[rule_id].id)


def _apply_consonant_ui(units: list[_Unit], rewrites: list[Rewrite] | None) -> None:
    """자음 초성 음절의 ㅢ를 문맥 없이 ㅣ로 실현한다."""

    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.onset == "ㅇ" or token.vowel != "ㅢ":
            continue
        before = unit.text if rewrites is not None else ""
        unit.syllable = token.changed(vowel="ㅣ")
        _record(rewrites, units, index, index, before, RULES["ko.vowel.consonant_ui"].id)


def _apply_hieuh_consonants(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    aspiration = {"ㄱ": "ㅋ", "ㄷ": "ㅌ", "ㅈ": "ㅊ"}
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or (
            token.coda not in HIEUH_FINALS and token.coda not in HIEUH_ASSIMILATION
        ):
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if token.coda in HIEUH_FINALS:
            remainder = HIEUH_REMAINDER[token.coda]
            if next_token.onset not in aspiration and next_token.onset not in {"ㅅ", "ㄴ"}:
                continue
            before = _trace_before(rewrites, units, index, right)
            if next_token.onset in aspiration:
                unit.syllable = token.changed(coda=remainder)
                units[right].syllable = next_token.changed(onset=aspiration[next_token.onset])
            elif next_token.onset == "ㅅ":
                unit.syllable = token.changed(coda=remainder)
                units[right].syllable = next_token.changed(onset="ㅆ")
            elif next_token.onset == "ㄴ":
                # 홑받침 ㅎ은 ㄴ 앞에서 [ㄴ]이 되고, ㄶ·ㅀ은 ㅎ만 탈락한다.
                unit.syllable = token.changed(coda="ㄴ" if token.coda == "ㅎ" else remainder)
            else:
                continue
            _record(rewrites, units, index, right, before, RULES["ko.hieuh.consonant"].id)
            continue
        if next_token.onset != "ㅎ" or token.coda not in HIEUH_ASSIMILATION:
            continue
        before = _trace_before(rewrites, units, index, right)
        # ‘꽂히다·밝히다’의 접미사 앞과 ‘낮 한때·닭 한 마리’의
        # 실질 형태소 앞은 다르다. 후자에서는 대표음화를 먼저 적용한다.
        suffix = not crossed_space and (
            next_token.vowel == "ㅣ"
            or next_token.vowel == "ㅕ" and next_token.coda in {None, "ㅆ"}
        )
        coda = token.coda
        if not suffix and coda in CODA_TRANSITIONS:
            coda = CODA_TRANSITIONS[coda].target
        assimilation = HIEUH_ASSIMILATION.get(coda)
        if assimilation is None:
            continue
        remainder, onset = assimilation
        unit.syllable = token.changed(coda=remainder)
        units[right].syllable = next_token.changed(onset=onset)
        _record(rewrites, units, index, right, before, RULES["ko.hieuh.consonant"].id)


def _apply_hieuh_before_vowel(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda not in HIEUH_FINALS:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if crossed_space or next_token.onset != "ㅇ":
            continue
        before = _trace_before(rewrites, units, index, right)
        remainder = HIEUH_REMAINDER[token.coda]
        unit.syllable = token.changed(coda=None)
        if remainder is not None:
            units[right].syllable = next_token.changed(onset=remainder)
        _record(rewrites, units, index, right, before, RULES["ko.hieuh.vowel"].id)


def _apply_liaison(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        # 종성 ㅇ은 초성으로 옮길 수 없으므로 모음 앞에서도 그대로 둔다.
        if token is None or token.coda is None or token.coda == "ㅇ":
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if crossed_space or next_token.onset != "ㅇ":
            continue
        before = _trace_before(rewrites, units, index, right)
        if token.coda in LIAISON_CLUSTER:
            remaining, onset = LIAISON_CLUSTER[token.coda]
            unit.syllable = token.changed(coda=remaining)
            units[right].syllable = next_token.changed(onset=onset)
            rule_id = RULES["ko.liaison.cluster"].id
        else:
            unit.syllable = token.changed(coda=None)
            units[right].syllable = next_token.changed(onset=token.coda)
            rule_id = RULES["ko.liaison.single"].id
        _record(rewrites, units, index, right, before, rule_id)


def _apply_numeral_n_insertion(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    """노멀라이저가 만드는 수사 합성어에만 보수적으로 ㄴ을 첨가한다."""

    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda is None:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, crossed_space = neighbor
        if crossed_space or _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if next_token.onset != "ㅇ":
            continue

        left_text = unit.text
        right_text = units[right].text
        sino = right_text == "육" and left_text in _SINO_N_INSERTION_LEFT
        native = (
            right_text == "여"
            and left_text in _NATIVE_N_INSERTION_LEFT
            and right + 1 < len(units)
            and units[right + 1].syllable is not None
            and units[right + 1].text in {"섯", "덟"}
        )
        if native and _has_phonological_barrier(
            units, index, right + 1, segments, pause_boundaries,
        ):
            continue
        if not sino and not native:
            continue
        before = _trace_before(rewrites, units, index, right)
        units[right].syllable = next_token.changed(onset="ㄴ")
        _record(
            rewrites,
            units,
            index,
            right,
            before,
            RULES["ko.n_insertion.numeral"].id,
        )


def _apply_coda_neutralization(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda not in CODA_TRANSITIONS:
            continue
        if index in blocked_units:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is not None:
            right, crossed_space = neighbor
            if _is_blocked_pair(blocked_pairs, blocked_units, index, right):
                continue
            if _has_phonological_barrier(units, index, right, segments, pause_boundaries):
                last = index
            else:
                next_token = units[right].syllable
                assert next_token is not None
                if not crossed_space and next_token.onset == "ㅇ":
                    continue
                last = right
        else:
            last = index
        transition = CODA_TRANSITIONS[token.coda]
        before = _trace_before(rewrites, units, index, last)
        unit.syllable = token.changed(coda=transition.target)
        _record(rewrites, units, index, last, before, transition.rule_id)


def _apply_cluster_tensification(
    units: list[_Unit], segments: tuple[_Segment, ...], rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]], blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    """ㄾ의 폐쇄음 단서가 사라지기 전에 뒤 자음을 경음화한다.

    개미핥기처럼 용언에서 파생된 명사를 분석기가 한 토큰으로 반환해도
    ㄾ의 ㅌ이 경음화를 유발한다. ㄼ까지 확장하면 여덟과를 잘못 바꾸므로
    ㄼ은 형태소 어간 조건이 있는 제25항 경로에 유지한다.
    """

    for left, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda != "ㄾ":
            continue
        neighbor = _next_syllable(units, segments, left)
        if neighbor is None or neighbor[1]:
            continue
        right = neighbor[0]
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, left, right, pause_boundaries,
        ):
            continue
        following = units[right].syllable
        assert following is not None
        tense = TENSE_ONSET.get(following.onset)
        if tense is None:
            continue
        before = _trace_before(rewrites, units, left, right)
        units[right].syllable = following.changed(onset=tense)
        _record(rewrites, units, left, right, before, "ko.cluster.tensing")


def _apply_liquid_assimilation(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda not in {"ㄱ", "ㄴ", "ㄹ", "ㅁ", "ㅂ", "ㅇ"}:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, _ = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if token.coda == "ㄴ" and next_token.onset == "ㄹ":
            before = _trace_before(rewrites, units, index, right)
            unit.syllable = token.changed(coda="ㄹ")
            units[right].syllable = next_token.changed(onset="ㄹ")
            _record(rewrites, units, index, right, before, RULES["ko.liquid.20"].id)
        elif token.coda == "ㄹ" and next_token.onset == "ㄴ":
            before = _trace_before(rewrites, units, index, right)
            units[right].syllable = next_token.changed(onset="ㄹ")
            _record(rewrites, units, index, right, before, RULES["ko.liquid.20"].id)
        elif next_token.onset == "ㄹ" and token.coda in {"ㄱ", "ㅂ"}:
            before = _trace_before(rewrites, units, index, right)
            unit.syllable = token.changed(coda="ㅇ" if token.coda == "ㄱ" else "ㅁ")
            units[right].syllable = next_token.changed(onset="ㄴ")
            _record(rewrites, units, index, right, before, RULES["ko.liquid.19"].id)
        elif next_token.onset == "ㄹ" and token.coda in {"ㅁ", "ㅇ"}:
            before = _trace_before(rewrites, units, index, right)
            units[right].syllable = next_token.changed(onset="ㄴ")
            _record(rewrites, units, index, right, before, RULES["ko.liquid.19"].id)


def _apply_nasalization(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda not in NASAL_CODA:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, _ = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        if next_token.onset not in {"ㄴ", "ㅁ"}:
            continue
        before = _trace_before(rewrites, units, index, right)
        unit.syllable = token.changed(coda=NASAL_CODA[token.coda])
        _record(rewrites, units, index, right, before, RULES["ko.nasalization"].id)


def _apply_tensification(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    rewrites: list[Rewrite] | None,
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    pause_boundaries: tuple[int, ...],
) -> None:
    for index, unit in enumerate(units):
        token = unit.syllable
        if token is None or token.coda not in {"ㄱ", "ㄷ", "ㅂ"}:
            continue
        neighbor = _next_syllable(units, segments, index)
        if neighbor is None:
            continue
        right, _ = neighbor
        if _is_blocked_phonological_pair(
            blocked_pairs, blocked_units, units, segments, index, right, pause_boundaries,
        ):
            continue
        next_token = units[right].syllable
        assert next_token is not None
        tense = TENSE_ONSET.get(next_token.onset)
        if tense is None:
            continue
        before = _trace_before(rewrites, units, index, right)
        units[right].syllable = next_token.changed(onset=tense)
        _record(rewrites, units, index, right, before, RULES["ko.tensification"].id)
