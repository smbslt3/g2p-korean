"""원문 code point 좌표에 고정된 발음 정렬 sidecar 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .model import G2PResult, Rewrite, RewriteStage, SourceSpan
from .unicode import NormalizedText


@dataclass(frozen=True, slots=True)
class _NucleusProvenance:
    """정렬 표시와 독립적으로 재생한 한 원문 모음 핵의 소유 근거다."""

    source_span: SourceSpan
    original: str
    realized: str
    owner_rule_id: str | None
    alignment_rule_id: str | None
    valid: bool


class AlignmentStatus(str, Enum):
    """정렬 근거의 전체 품질을 나타낸다."""

    EXACT = "exact"
    COARSE = "coarse"
    UNAVAILABLE = "unavailable"


class AlignmentRelation(str, Enum):
    """source와 output 사이에 trace가 뒷받침하는 관계다."""

    IDENTITY = "identity"
    SUBSTITUTION = "substitution"
    EXPANSION = "expansion"
    CONTRACTION = "contraction"
    INSERTION = "insertion"
    DELETION = "deletion"
    GROUPED = "grouped"
    UNAVAILABLE = "unavailable"


class AlignmentPrecision(str, Enum):
    """문자 대응인지 작업 단위 대응인지 나타낸다."""

    CODEPOINT = "codepoint"
    OPERATION = "operation"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AlignmentEntry:
    """표면 발음 구간과 원문 근거 또는 명시적 근거 부재를 연결한다."""

    output_start: int
    output_end: int
    source_spans: tuple[SourceSpan, ...]
    relation: AlignmentRelation
    stage: RewriteStage | None = None
    kind: str = "identity"
    rule_id: str | None = None
    anchor: SourceSpan | None = None
    insertion_rule: str | None = None
    precision: AlignmentPrecision = AlignmentPrecision.CODEPOINT
    _nucleus_provenance: _NucleusProvenance | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_spans", tuple(self.source_spans))
        if self.output_start < 0 or self.output_end < self.output_start:
            raise ValueError("정렬 출력 span이 올바르지 않습니다.")
        if tuple(sorted(self.source_spans, key=lambda item: (item.start, item.end))) != self.source_spans:
            raise ValueError("정렬 원문 span은 원문 순서여야 합니다.")
        if self.relation is AlignmentRelation.INSERTION:
            if (
                self.output_start == self.output_end
                or self.source_spans
                or self.anchor is None
                or not self.insertion_rule
            ):
                raise ValueError("삽입에는 빈 source span, anchor, insertion_rule이 필요합니다.")
        elif self.anchor is not None or self.insertion_rule is not None:
            raise ValueError("anchor와 insertion_rule은 삽입 관계에서만 허용됩니다.")
        if self.relation is AlignmentRelation.UNAVAILABLE:
            if self.precision is not AlignmentPrecision.UNAVAILABLE:
                raise ValueError("근거 부재 관계의 precision은 unavailable이어야 합니다.")
        elif self.precision is AlignmentPrecision.UNAVAILABLE:
            raise ValueError("근거가 있는 관계를 unavailable precision으로 표시할 수 없습니다.")

    def to_dict(self) -> dict[str, Any]:
        """JSON 호환 사전을 반환한다."""

        return {
            "output_start": self.output_start,
            "output_end": self.output_end,
            "source_spans": [span.to_dict() for span in self.source_spans],
            "relation": self.relation.value,
            "stage": self.stage.value if self.stage is not None else None,
            "kind": self.kind,
            "rule_id": self.rule_id,
            "anchor": self.anchor.to_dict() if self.anchor is not None else None,
            "insertion_rule": self.insertion_rule,
            "precision": self.precision.value,
        }


@dataclass(frozen=True, slots=True)
class TargetExtraction:
    """원문 target에서 연속 발음 구간을 꺼내거나 실패 이유를 보존한다."""

    aligned: bool
    pronunciation: str | None = None
    output_start: int | None = None
    output_end: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.aligned:
            if self.pronunciation is None or self.output_start is None or self.output_end is None:
                raise ValueError("성공한 target 추출에는 발음과 출력 좌표가 필요합니다.")
            if self.reason is not None:
                raise ValueError("성공한 target 추출에는 실패 이유가 없습니다.")
        elif self.reason is None or self.pronunciation is not None:
            raise ValueError("실패한 target 추출에는 이유만 지정해야 합니다.")


@dataclass(frozen=True, slots=True)
class PronunciationAlignment:
    """원문과 표면 발음 전체에 대한 빈틈없는 출력 정렬이다."""

    source: str
    output: str
    entries: tuple[AlignmentEntry, ...]
    source_coverage_unavailable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        if not isinstance(self.source_coverage_unavailable, bool):
            raise ValueError("source coverage 상태는 불리언이어야 합니다.")
        cursor = 0
        previous_start = -1
        for entry in self.entries:
            if entry.output_end > len(self.output):
                raise ValueError("정렬 출력 span이 발음 문자열 범위를 벗어났습니다.")
            if entry.output_start < previous_start:
                raise ValueError("정렬 항목은 출력 순서여야 합니다.")
            previous_start = entry.output_start
            for span in entry.source_spans:
                if (
                    span.source_length != len(self.source)
                    or self.source[span.start : span.end] != span.surface
                ):
                    raise ValueError("정렬 source span이 원문 문자열과 일치하지 않습니다.")
            if entry.anchor is not None and (
                entry.anchor.source_length != len(self.source)
                or entry.anchor.start != entry.anchor.end
                or entry.anchor.surface
            ):
                raise ValueError("삽입 anchor는 원문 좌표의 0길이 span이어야 합니다.")
            if entry.output_start == entry.output_end:
                if entry.relation is not AlignmentRelation.DELETION:
                    raise ValueError("0길이 출력 정렬은 deletion 관계여야 합니다.")
                if not entry.source_spans:
                    raise ValueError("deletion에는 소비된 원문 span이 필요합니다.")
                if entry.output_start > cursor:
                    raise ValueError("deletion 출력 위치가 앞선 출력 범위와 떨어져 있습니다.")
                continue
            if entry.output_start != cursor:
                raise ValueError("정렬 출력 구간에 빈틈이나 겹침이 있습니다.")
            cursor = entry.output_end
        if cursor != len(self.output):
            raise ValueError("정렬 항목이 표면 발음 전체를 덮지 않습니다.")
        source_cursor = 0
        source_gaps = False
        for start, end in sorted(
            (span.start, span.end)
            for entry in self.entries
            for span in entry.source_spans
            if span.start < span.end
        ):
            if start > source_cursor:
                source_gaps = True
            source_cursor = max(source_cursor, end)
        if source_cursor < len(self.source):
            source_gaps = True
        if source_gaps != self.source_coverage_unavailable:
            raise ValueError(
                "원문 code point 전체를 대응 항목/deletion으로 덮거나, 누락 근거를 명시해야 합니다."
            )

    @property
    def status(self) -> AlignmentStatus:
        """complete와 독립적인 정렬 근거 상태를 계산한다."""

        if self.source_coverage_unavailable:
            return AlignmentStatus.UNAVAILABLE
        if any(
            entry.relation is AlignmentRelation.UNAVAILABLE
            or entry.precision is AlignmentPrecision.UNAVAILABLE
            for entry in self.entries
        ):
            return AlignmentStatus.UNAVAILABLE
        if any(entry.precision is AlignmentPrecision.OPERATION for entry in self.entries):
            return AlignmentStatus.COARSE
        return AlignmentStatus.EXACT

    def to_dict(self) -> dict[str, Any]:
        """JSON 호환 사전을 반환한다."""

        return {
            "source": self.source,
            "output": self.output,
            "status": self.status.value,
            "source_coverage_unavailable": self.source_coverage_unavailable,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def extract_target(self, start: int, end: int) -> TargetExtraction:
        """원문 target 전체가 완전한 작업 단위일 때 연속 발음을 반환한다."""

        if not (0 <= start < end <= len(self.source)):
            return TargetExtraction(False, reason="invalid_target_span")

        selected: list[AlignmentEntry] = []
        for entry in self.entries:
            if entry.source_spans:
                intersects = any(span.start < end and start < span.end for span in entry.source_spans)
                if not intersects:
                    continue
                if any(not (start <= span.start and span.end <= end) for span in entry.source_spans):
                    return TargetExtraction(False, reason="partial_operation")
                if entry.relation is AlignmentRelation.UNAVAILABLE:
                    return TargetExtraction(False, reason="unavailable_alignment")
                selected.append(entry)
            elif (
                entry.relation is AlignmentRelation.INSERTION
                and entry.anchor is not None
                and start <= entry.anchor.start < end
            ):
                selected.append(entry)

        if not selected:
            return TargetExtraction(False, reason="uncovered_source")

        intervals = sorted(
            (span.start, span.end)
            for entry in selected
            for span in entry.source_spans
            if span.start < span.end
        )
        covered = start
        for left, right in intervals:
            if left > covered:
                return TargetExtraction(False, reason="uncovered_source")
            covered = max(covered, right)
        if covered < end:
            return TargetExtraction(False, reason="uncovered_source")

        output_entries = sorted(
            (entry for entry in selected if entry.output_start < entry.output_end),
            key=lambda item: (item.output_start, item.output_end),
        )
        if output_entries:
            output_start = output_entries[0].output_start
            output_end = output_entries[-1].output_end
            cursor = output_start
            selected_ids = {id(entry) for entry in output_entries}
            for entry in self.entries:
                if entry.output_start == entry.output_end:
                    continue
                if entry.output_end <= output_start or entry.output_start >= output_end:
                    continue
                if id(entry) not in selected_ids or entry.output_start != cursor:
                    return TargetExtraction(False, reason="noncontiguous_output")
                cursor = entry.output_end
            if cursor != output_end:
                return TargetExtraction(False, reason="noncontiguous_output")
        else:
            deletions = [entry for entry in selected if entry.relation is AlignmentRelation.DELETION]
            if not deletions:
                return TargetExtraction(False, reason="no_output_for_target")
            output_start = output_end = deletions[0].output_start

        return TargetExtraction(
            True,
            self.output[output_start:output_end],
            output_start,
            output_end,
        )


@dataclass(frozen=True, slots=True)
class G2PAlignedResult:
    """기존 변환 결과를 보존하며 opt-in 정렬 sidecar를 더한다."""

    result: G2PResult
    alignment: PronunciationAlignment

    def __post_init__(self) -> None:
        if self.alignment.source != self.result.source:
            raise ValueError("sidecar 원문이 G2PResult 원문과 다릅니다.")
        if self.alignment.output != self.result.surface_pronunciation:
            raise ValueError("sidecar 출력이 G2PResult 표면 발음과 다릅니다.")


def _raw_spans(
    normalized: NormalizedText,
    spans: tuple[SourceSpan, ...],
) -> tuple[SourceSpan, ...] | None:
    """NFC 단계 source span을 원문 provenance로 합성한다."""

    if not spans:
        return ()
    mapped: list[SourceSpan] = []
    for span in spans:
        if span.source_length != len(normalized.text) or span.start == span.end:
            return None
        try:
            mapped.append(normalized.source_span(span.start, span.end))
        except ValueError:
            return None
    return _coalesce_spans(normalized.source, tuple(mapped))


def _coalesce_spans(source: str, spans: tuple[SourceSpan, ...]) -> tuple[SourceSpan, ...]:
    """겹치거나 맞닿은 provenance span만 연속 원문 span으로 묶는다."""

    if not spans:
        return ()
    ordered = sorted(spans, key=lambda item: (item.start, item.end))
    result: list[SourceSpan] = []
    start = ordered[0].start
    end = ordered[0].end
    for span in ordered[1:]:
        if span.start <= end:
            end = max(end, span.end)
        else:
            result.append(SourceSpan.from_source(source, start, end))
            start, end = span.start, span.end
    result.append(SourceSpan.from_source(source, start, end))
    return tuple(result)


def _source_coverage_is_complete(source: str, entries: list[AlignmentEntry]) -> bool:
    """모든 원문 code point가 출력 대응이나 deletion trace에 포함됐는지 확인한다."""

    cursor = 0
    for start, end in sorted(
        (span.start, span.end)
        for entry in entries
        for span in entry.source_spans
        if span.start < span.end
    ):
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor == len(source)


def _per_character_nfc_spans(
    segment_text: str,
    spans: tuple[SourceSpan, ...],
    nfc_text: str,
) -> tuple[SourceSpan, ...] | None:
    """기존 segment trace가 허용하는 경우에만 문자별 NFC span을 만든다."""

    if not segment_text or len(spans) != len(segment_text):
        return None
    if all(span.end - span.start == 1 for span in spans):
        characters = spans
    elif all(span == spans[0] for span in spans):
        span = spans[0]
        if span.surface != segment_text or span.end - span.start != len(segment_text):
            return None
        characters = tuple(
            SourceSpan.from_source(nfc_text, span.start + index, span.start + index + 1)
            for index in range(len(segment_text))
        )
    else:
        return None
    if any(
        span.source_length != len(nfc_text)
        or span.end - span.start != 1
        or nfc_text[span.start : span.end] != segment_text[index]
        for index, span in enumerate(characters)
    ):
        return None
    if any(left.end != right.start for left, right in zip(characters, characters[1:])):
        return None
    return characters


def _matching_rewrite(
    span: SourceSpan,
    rewrites: tuple[Rewrite, ...],
    stage: RewriteStage,
) -> Rewrite | None:
    """지정된 NFC 입력 문자에 실제로 trace된 마지막 규칙을 찾는다."""

    matches = [
        rewrite
        for rewrite in rewrites
        if rewrite.stage is stage
        and any(source.start <= span.start and span.end <= source.end for source in rewrite.source_spans)
    ]
    return matches[-1] if matches else None


def _raw_anchor(normalized: NormalizedText, anchor: SourceSpan) -> SourceSpan | None:
    """NFC 경계를 원문 경계로 옮길 근거가 단일할 때만 anchor를 만든다."""

    if anchor.source_length != len(normalized.text) or anchor.start != anchor.end:
        return None
    position = anchor.start
    if position == 0:
        raw_position = 0
    elif position == len(normalized.text):
        raw_position = len(normalized.source)
    else:
        left = normalized.character_spans[position - 1]
        right = normalized.character_spans[position]
        if left.end != right.start:
            return None
        raw_position = left.end
    return SourceSpan.from_source(normalized.source, raw_position, raw_position)


def _deletion_rewrite(
    source_spans: tuple[SourceSpan, ...],
    rewrites: tuple[Rewrite, ...],
    *,
    stage: RewriteStage | None = None,
) -> Rewrite | None:
    """source 구간을 소비하고 빈 결과를 낸 실제 rewrite trace만 찾는다."""

    for rewrite in reversed(rewrites):
        if rewrite.after or (stage is not None and rewrite.stage is not stage):
            continue
        if source_spans and all(
            any(trace.start <= span.start and span.end <= trace.end for trace in rewrite.source_spans)
            for span in source_spans
        ):
            return rewrite
    return None


def _nucleus_provenance(
    raw_span: SourceSpan,
    nfc_span: SourceSpan,
    nfc_text: str,
    output_character: str,
    rewrites: tuple[Rewrite, ...],
    alignment_rule_id: str | None,
) -> _NucleusProvenance | None:
    """실제 성분 변화만 재생하며 자음 변화 뒤에도 핵의 소유자를 보존한다."""

    # 한국어 패키지의 읽기 조건 모듈이 이 정렬 모델을 참조하므로 실행 때 읽는다.
    from .korean.hangul import decompose_syllable, is_modern_syllable
    from .korean.rules import RULES

    original = nfc_text[nfc_span.start:nfc_span.end]
    if not is_modern_syllable(original) or not is_modern_syllable(output_character):
        return None
    current = original
    owner_rule_id = None
    valid = True
    for rewrite in rewrites:
        if rewrite.stage is not RewriteStage.PHONOLOGY:
            continue
        if not any(span.start < nfc_span.end and nfc_span.start < span.end for span in rewrite.source_spans):
            continue
        # 길이 비율이나 반복 문자의 검색 위치로 대응을 추측하지 않는다.
        start = rewrite.source_spans[0].start
        cursor = start
        for span in rewrite.source_spans:
            if (span.start != cursor or span.source_length != len(nfc_text)
                    or nfc_text[span.start:span.end] != span.surface):
                valid = False
                break
            cursor = span.end
        if (not valid or not start <= nfc_span.start < nfc_span.end <= cursor
                or len(rewrite.before) != len(rewrite.after)
                or len(rewrite.before) != cursor - start):
            valid = False
            break
        offset = nfc_span.start - start
        before, after = rewrite.before[offset], rewrite.after[offset]
        if before != current or not is_modern_syllable(before) or not is_modern_syllable(after):
            valid = False
            break
        previous = decompose_syllable(before, (nfc_span,))
        following = decompose_syllable(after, (nfc_span,))
        if previous.vowel != following.vowel:
            definition = RULES.get(rewrite.rule_id)
            declaration = definition.nucleus_transfer if definition is not None else None
            if (declaration is None or previous.onset != following.onset
                    or previous.coda != following.coda or previous.onset not in declaration.onsets
                    or (previous.vowel, following.vowel) not in declaration.vowels):
                valid = False
                break
            owner_rule_id = rewrite.rule_id
        current = after
    return _NucleusProvenance(raw_span, original, output_character, owner_rule_id,
                              alignment_rule_id, valid and current == output_character)


def _entry_for_character(
    *,
    source: str,
    output_start: int,
    raw_span: SourceSpan | None,
    nfc_span: SourceSpan | None,
    nfc_text: str,
    output_character: str,
    normalization: NormalizedText,
    pipeline_rewrites: tuple[Rewrite, ...],
) -> AlignmentEntry:
    """한 output code point의 trace를 정확 또는 unavailable로 기록한다."""

    if raw_span is None or nfc_span is None:
        return AlignmentEntry(
            output_start,
            output_start + 1,
            (),
            AlignmentRelation.UNAVAILABLE,
            kind="unavailable",
            precision=AlignmentPrecision.UNAVAILABLE,
        )
    normalized_character = nfc_text[nfc_span.start]
    pronunciation_rewrite = (
        _matching_rewrite(nfc_span, pipeline_rewrites, RewriteStage.PHONOLOGY)
        if normalized_character != output_character
        else None
    )
    unicode_rewrite = _matching_rewrite(
        raw_span,
        normalization.rewrites,
        RewriteStage.UNICODE,
    )
    if normalized_character != output_character and pronunciation_rewrite is None:
        return AlignmentEntry(
            output_start,
            output_start + 1,
            (raw_span,),
            AlignmentRelation.UNAVAILABLE,
            kind="unavailable",
            precision=AlignmentPrecision.UNAVAILABLE,
        )
    nucleus = _nucleus_provenance(
        raw_span, nfc_span, nfc_text, output_character, pipeline_rewrites,
        pronunciation_rewrite.rule_id if pronunciation_rewrite is not None else None,
    )
    raw_character = source[raw_span.start : raw_span.end]
    if len(raw_character) == 1:
        if raw_character == output_character:
            relation = AlignmentRelation.IDENTITY
            stage = None
            kind = "identity"
            rule_id = None
        else:
            relation = AlignmentRelation.SUBSTITUTION
            if pronunciation_rewrite is not None:
                stage = RewriteStage.PHONOLOGY
                kind = "phonological_rule"
                rule_id = pronunciation_rewrite.rule_id
            elif unicode_rewrite is not None:
                stage = RewriteStage.UNICODE
                kind = "unicode_normalization"
                rule_id = unicode_rewrite.rule_id
            else:
                return AlignmentEntry(
                    output_start,
                    output_start + 1,
                    (raw_span,),
                    AlignmentRelation.UNAVAILABLE,
                    kind="unavailable",
                    precision=AlignmentPrecision.UNAVAILABLE,
                )
        return AlignmentEntry(
            output_start,
            output_start + 1,
            (raw_span,),
            relation,
            stage,
            kind,
            rule_id,
            precision=AlignmentPrecision.CODEPOINT,
            _nucleus_provenance=nucleus,
        )

    # 정준 조합 단위는 원문의 여러 code point가 가진 가장 좁은 실재 trace다.
    if pronunciation_rewrite is not None:
        stage = RewriteStage.PHONOLOGY
        kind = "phonological_rule"
        rule_id = pronunciation_rewrite.rule_id
    else:
        stage = RewriteStage.UNICODE
        kind = "unicode_normalization"
        rule_id = unicode_rewrite.rule_id if unicode_rewrite is not None else None
    return AlignmentEntry(
        output_start,
        output_start + 1,
        (raw_span,),
        AlignmentRelation.CONTRACTION,
        stage,
        kind,
        rule_id,
        precision=AlignmentPrecision.OPERATION,
        _nucleus_provenance=nucleus,
    )


def build_pronunciation_alignment(
    source: str,
    normalization: NormalizedText,
    pipeline_result: Any,
) -> PronunciationAlignment:
    """한 번 실행한 pipeline의 실제 segment/rewrite trace를 원문 좌표로 합성한다."""

    output = pipeline_result.surface_pronunciation
    normalized_segments = pipeline_result.normalized_segments
    pronunciation_segments = pipeline_result.pronunciation_segments
    if len(normalized_segments) != len(pronunciation_segments):
        raise ValueError("발음 전후 segment trace 수가 다릅니다.")

    entries: list[AlignmentEntry] = []
    output_cursor = 0
    segment_pairs = tuple(zip(normalized_segments, pronunciation_segments))
    coalesced_indices: set[int] = set()
    for segment_index, (segment, pronounced) in enumerate(segment_pairs):
        if segment_index in coalesced_indices:
            continue
        if not segment.source_spans and segment.insertion_rule and segment.anchor is not None:
            anchor = _raw_anchor(normalization, segment.anchor)
            if anchor is not None and pronounced.text:
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor + len(pronounced.text),
                        (),
                        AlignmentRelation.INSERTION,
                        RewriteStage.PHONOLOGY,
                        "phonological_rule",
                        segment.insertion_rule,
                        anchor,
                        segment.insertion_rule,
                        AlignmentPrecision.OPERATION,
                    )
                )
            elif pronounced.text:
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor + len(pronounced.text),
                        (),
                        AlignmentRelation.UNAVAILABLE,
                        kind="unavailable",
                        precision=AlignmentPrecision.UNAVAILABLE,
                    )
                )
            output_cursor += len(pronounced.text)
            continue

        if len(segment.text) != len(pronounced.text):
            raw_spans = _raw_spans(normalization, segment.source_spans)
            rewrite = _deletion_rewrite(segment.source_spans, pipeline_result.rewrites)
            if not pronounced.text and raw_spans and rewrite is not None:
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor,
                        raw_spans,
                        AlignmentRelation.DELETION,
                        rewrite.stage,
                        "phonological_rule" if rewrite.stage is RewriteStage.PHONOLOGY else "lexical_pronunciation",
                        rewrite.rule_id,
                        precision=AlignmentPrecision.OPERATION,
                    )
                )
            elif pronounced.text:
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor + len(pronounced.text),
                        raw_spans or (),
                        AlignmentRelation.UNAVAILABLE,
                        kind="unavailable",
                        precision=AlignmentPrecision.UNAVAILABLE,
                    )
                )
            output_cursor += len(pronounced.text)
            continue
        if segment.handler.value == "english" and segment.rule_id is not None:
            raw_spans = _raw_spans(normalization, segment.source_spans)
            if raw_spans is None or not raw_spans:
                for offset in range(len(pronounced.text)):
                    entries.append(
                        AlignmentEntry(
                            output_cursor + offset,
                            output_cursor + offset + 1,
                            (),
                            AlignmentRelation.UNAVAILABLE,
                            kind="unavailable",
                            precision=AlignmentPrecision.UNAVAILABLE,
                        )
                    )
            elif pronounced.text:
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor + len(pronounced.text),
                        raw_spans,
                        AlignmentRelation.GROUPED,
                        RewriteStage.LEXICAL,
                        "lexical_reading",
                        segment.rule_id,
                        precision=AlignmentPrecision.OPERATION,
                    )
                )
            else:
                rewrite = _deletion_rewrite(
                    segment.source_spans,
                    pipeline_result.rewrites,
                    stage=RewriteStage.LEXICAL,
                )
                if raw_spans and rewrite is not None:
                    entries.append(
                        AlignmentEntry(
                            output_cursor,
                            output_cursor,
                            raw_spans,
                            AlignmentRelation.DELETION,
                            rewrite.stage,
                            "lexical_reading",
                            rewrite.rule_id,
                            precision=AlignmentPrecision.OPERATION,
                        )
                    )
            output_cursor += len(pronounced.text)
            continue

        nfc_spans = _per_character_nfc_spans(
            segment.text,
            segment.source_spans,
            normalization.text,
        )
        if nfc_spans is None:
            raw_spans = _raw_spans(normalization, segment.source_spans)
            grouped_segments = [(segment_index, segment, pronounced)]
            if raw_spans is not None and len(raw_spans) == 1:
                for following_index in range(segment_index + 1, len(segment_pairs)):
                    following_segment, following_pronounced = segment_pairs[following_index]
                    if (
                        not following_segment.source_spans
                        or following_segment.insertion_rule
                        or following_segment.handler.value == "english"
                        and following_segment.rule_id is not None
                        or len(following_segment.text) != len(following_pronounced.text)
                    ):
                        break
                    following_raw_spans = _raw_spans(
                        normalization,
                        following_segment.source_spans,
                    )
                    if following_raw_spans != raw_spans:
                        break
                    grouped_segments.append(
                        (following_index, following_segment, following_pronounced)
                    )
            grouped_output = "".join(item[2].text for item in grouped_segments)
            raw_span = raw_spans[0] if raw_spans is not None and len(raw_spans) == 1 else None
            has_group_trace = (
                len(grouped_segments) > 1
                or raw_span is not None
                and raw_span.end - raw_span.start > 1
                or segment.rule_id is not None
            )
            if raw_span is not None and grouped_output and has_group_trace:
                raw_length = raw_span.end - raw_span.start
                if raw_length > len(grouped_output):
                    relation = AlignmentRelation.CONTRACTION
                elif raw_length < len(grouped_output):
                    relation = AlignmentRelation.EXPANSION
                else:
                    relation = AlignmentRelation.GROUPED
                normalization_rewrite = _matching_rewrite(
                    raw_span,
                    normalization.rewrites,
                    RewriteStage.UNICODE,
                )
                entries.append(
                    AlignmentEntry(
                        output_cursor,
                        output_cursor + len(grouped_output),
                        (raw_span,),
                        relation,
                        RewriteStage.UNICODE,
                        "unicode_normalization",
                        normalization_rewrite.rule_id if normalization_rewrite else None,
                        precision=AlignmentPrecision.OPERATION,
                    )
                )
                coalesced_indices.update(index for index, _, _ in grouped_segments[1:])
                output_cursor += len(grouped_output)
                continue

            for offset, _character in enumerate(pronounced.text):
                entries.append(
                    AlignmentEntry(
                        output_cursor + offset,
                        output_cursor + offset + 1,
                        raw_spans or (),
                        AlignmentRelation.UNAVAILABLE,
                        kind="unavailable",
                        precision=AlignmentPrecision.UNAVAILABLE,
                    )
                )
            output_cursor += len(pronounced.text)
            continue

        character_entries: list[AlignmentEntry] = []
        raw_character_spans: list[SourceSpan | None] = []
        # 상세 엔진은 입력 code point마다 하나의 unit을 유지하며 순서대로 재조립한다.
        # 아래 연결은 trace가 확인한 1:1 unit 경로에만 쓰고 길이 비율을 계산하지 않는다.
        for offset, (nfc_span, output_character) in enumerate(
            zip(nfc_spans, pronounced.text)
        ):
            try:
                raw_span = normalization.source_span(nfc_span.start, nfc_span.end)
            except ValueError:
                raw_span = None
            raw_character_spans.append(raw_span)
            character_entries.append(
                _entry_for_character(
                    source=source,
                    output_start=output_cursor + offset,
                    raw_span=raw_span,
                    nfc_span=nfc_span,
                    nfc_text=normalization.text,
                    output_character=output_character,
                    normalization=normalization,
                    pipeline_rewrites=pipeline_result.rewrites,
                )
            )

        offset = 0
        while offset < len(character_entries):
            raw_span = raw_character_spans[offset]
            run_end = offset + 1
            if raw_span is not None:
                while run_end < len(character_entries) and raw_character_spans[run_end] == raw_span:
                    run_end += 1
            group_length = run_end - offset
            if raw_span is not None and (raw_span.end - raw_span.start > 1 or group_length > 1):
                pronunciations = pronounced.text[offset:run_end]
                if raw_span.end - raw_span.start > len(pronunciations):
                    relation = AlignmentRelation.CONTRACTION
                elif raw_span.end - raw_span.start < len(pronunciations):
                    relation = AlignmentRelation.EXPANSION
                else:
                    relation = AlignmentRelation.GROUPED
                matching = [entry for entry in character_entries[offset:run_end]]
                changed = [
                    entry
                    for entry in matching
                    if entry.relation is AlignmentRelation.SUBSTITUTION
                    or entry.stage is RewriteStage.PHONOLOGY
                ]
                exemplar = changed[-1] if changed else matching[0]
                if any(entry.relation is AlignmentRelation.UNAVAILABLE for entry in matching):
                    relation = AlignmentRelation.UNAVAILABLE
                    precision = AlignmentPrecision.UNAVAILABLE
                    stage = None
                    kind = "unavailable"
                    rule_id = None
                else:
                    precision = AlignmentPrecision.OPERATION
                    stage = exemplar.stage
                    kind = exemplar.kind if changed else "unicode_normalization"
                    rule_id = exemplar.rule_id if changed else None
                entries.append(
                    AlignmentEntry(
                        output_cursor + offset,
                        output_cursor + run_end,
                        (raw_span,),
                        relation,
                        stage,
                        kind,
                        rule_id,
                        precision=precision,
                        _nucleus_provenance=(exemplar._nucleus_provenance if group_length == 1 else None),
                    )
                )
            else:
                entries.extend(character_entries[offset:run_end])
            offset = run_end
        output_cursor += len(pronounced.text)

    if output_cursor != len(output):
        raise ValueError("pipeline segment trace가 표면 발음 전체를 덮지 않습니다.")
    entries.sort(key=lambda item: (item.output_start, item.output_end == item.output_start))
    source_coverage_unavailable = not _source_coverage_is_complete(source, entries)
    return PronunciationAlignment(
        source,
        output,
        tuple(entries),
        source_coverage_unavailable=source_coverage_unavailable,
    )
