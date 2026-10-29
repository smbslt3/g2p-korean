"""단계 순서·실패 격리·trace 병합을 담당하는 정규화 파이프라인이다."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import cast

from .errors import InputValidationError, InternalInvariantError
from .english import resolve_english
from .english.classify import ascii_letter_form
from .english.context import is_standalone_latin_word
from .english.conventional import CONVENTIONAL_READINGS
from .english.structures import scan_english_structures
from .korean.engine import pronounce, pronounce_text
from .merge import Marker, join_segments, merge_segments, merge_text_segments
from .model import (
    Boundary,
    Diagnostic,
    Handler,
    OutputSegment,
    Rewrite,
    RewriteStage,
    Severity,
    SourceSpan,
)
from .validation import normalize_pause_boundaries, validate_output
from .routing import Candidate, route_spelling_candidates
from .scanner import ProtectedRange
from .unicode import NormalizedText, normalize_nfc, normalize_nfc_text
from .reading_conditions import ReadingBoundaryExecution, _MappedReadingBoundary
from .number_normalizer import normalize_numbers


@dataclass(frozen=True, slots=True)
class _Resolution:
    """외국어 후보의 치환 결과다."""

    replacement: str
    reason: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class _PipelineResult:
    """내부 G2P 단계의 중간 결과와 검증 정보를 묶는다."""

    normalized_text: str
    surface_pronunciation: str
    normalized_segments: tuple[OutputSegment, ...]
    pronunciation_segments: tuple[OutputSegment, ...]
    rewrites: tuple[Rewrite, ...]
    diagnostics: tuple[Diagnostic, ...]
    complete: bool
    condition_executions: tuple[ReadingBoundaryExecution, ...] = ()


class Pipeline:
    """발화형 문자열을 영문 읽기와 표면 발음 결과로 조합한다."""

    def __init__(
        self,
        *,
        max_length: int,
    ) -> None:
        self._max_length = max_length

    def run(
        self,
        source: str,
        *,
        pause_boundaries: Iterable[int] = (),
    ) -> _PipelineResult:
        """영문 읽기와 한국어 표면 발음 단계를 모두 실행한다."""

        return cast(
            _PipelineResult,
            self._run(source, trace=True, pause_boundaries=pause_boundaries),
        )

    def run_text(self, source: str, *, pause_boundaries: Iterable[int] = ()) -> str:
        """trace와 상세 결과 model 없이 표면 발음 문자열만 반환한다."""

        return cast(str, self._run(source, trace=False, pause_boundaries=pause_boundaries))

    def run_normalized(
        self, source: str, *, pause_boundaries: Iterable[int] = (),
        reading_conditions: tuple[_MappedReadingBoundary, ...] = (),
    ) -> _PipelineResult:
        """공개 진입점에서 원문 길이를 검증한 NFC 입력의 상세 결과를 만든다."""

        return cast(
            _PipelineResult,
            self._run(
                source,
                trace=True,
                input_already_validated=True,
                pause_boundaries=pause_boundaries,
                reading_conditions=reading_conditions,
            ),
        )

    def _run(
        self,
        source: str,
        *,
        trace: bool,
        input_already_validated: bool = False,
        pause_boundaries: Iterable[int] = (),
        reading_conditions: tuple[_MappedReadingBoundary, ...] = (),
    ) -> _PipelineResult | str:
        """라우팅 의미를 공유하고 상세 model 생성만 선택적으로 수행한다."""

        # NFC가 늘린 길이에는 원문 예산을 다시 적용하지 않는다.
        input_limit = len(source) if input_already_validated else self._max_length
        if trace:
            normalized = normalize_nfc(source, max_length=input_limit)
            text = normalized.text
        else:
            normalized = None
            text = normalize_nfc_text(source, max_length=input_limit)
        text = normalize_numbers(text)
        pauses = normalize_pause_boundaries(pause_boundaries, len(text))
        routed = route_spelling_candidates(text)
        protected = scan_english_structures(text) if any(
            candidate.handler is Handler.ENGLISH for candidate in routed.candidates
        ) else ()

        diagnostics: list[Diagnostic] | None = [] if trace else None
        unresolved: list[SourceSpan] | None = [] if trace else None
        rewrites: list[Rewrite] | None = (
            list(normalized.rewrites) if normalized is not None else None
        )
        markers = self._numeric_markers(text, routed.numeric_ranges)
        if normalized is not None and diagnostics is not None and unresolved is not None:
            for start, end in routed.numeric_ranges:
                span = normalized.source_span(start, end)
                self._diagnose(
                    diagnostics, "unconverted_numeric",
                    "숫자는 앞단의 korean-number-reader에서 한글로 변환해야 합니다.",
                    span, "input.number_reader_required",
                )
                unresolved.append(span)

        for candidate in routed.candidates:
            resolution = self._resolve_candidate(text, candidate, protected)
            if resolution is None:
                markers.append(self._preserved_marker(text, candidate))
                if normalized is not None and diagnostics is not None and unresolved is not None:
                    self._diagnose_unresolved_candidate(
                        diagnostics,
                        unresolved,
                        normalized,
                        candidate,
                    )
                continue
            markers.append(
                Marker(
                    candidate.start,
                    candidate.end,
                    resolution.replacement,
                    candidate.handler,
                    resolution.reason,
                    resolution.rule_id,
                    Boundary.MORPHEME,
                )
            )
            if normalized is not None and rewrites is not None:
                span = normalized.source_span(candidate.start, candidate.end)
                rewrites.append(
                    Rewrite(
                        (span,),
                        text[candidate.start : candidate.end],
                        resolution.replacement,
                        candidate.handler,
                        resolution.rule_id,
                        RewriteStage.LEXICAL,
                    )
                )

        mapped_pauses = self._map_pause_boundaries(text, markers, pauses)
        mapped_conditions = tuple(
            replace(request, output_offset=self._map_pause_boundaries(
                text, markers, (request.nfc_offset,),
            )[0]) for request in reading_conditions
        )
        if normalized is None:
            text_segments = merge_text_segments(text, markers)
            pronunciation_text = pronounce_text(
                text_segments,
                pause_boundaries=mapped_pauses,
            )
            if sum(len(segment.text) for segment in text_segments) != len(
                pronunciation_text
            ):
                raise InternalInvariantError(
                    "정규화문과 표면 발음의 code point 길이가 다릅니다."
                )
            return pronunciation_text

        assert diagnostics is not None and unresolved is not None and rewrites is not None
        segments = merge_segments(normalized, markers)
        normalized_text = join_segments(segments)
        validation_diagnostics = validate_output(
            segments,
            known_unresolved=unresolved,
        )
        diagnostics.extend(validation_diagnostics)
        complete = not unresolved and not validation_diagnostics

        pronounced = pronounce(
            segments, pause_boundaries=mapped_pauses, reading_conditions=mapped_conditions,
        ) if mapped_conditions else pronounce(segments, pause_boundaries=mapped_pauses)
        pronunciation_text = join_segments(pronounced.segments)
        pronunciation_segments = pronounced.segments
        if len(normalized_text) != len(pronunciation_text):
            raise InternalInvariantError(
                "정규화문과 표면 발음의 code point 길이가 다릅니다."
            )
        rewrites.extend(pronounced.rewrites)
        diagnostics.extend(pronounced.diagnostics)
        pronunciation_validation_diagnostics = validate_output(
            pronunciation_segments,
            known_unresolved=unresolved,
        )
        diagnostics.extend(pronunciation_validation_diagnostics)
        complete = (
            complete
            and not any(
                item.severity is Severity.WARNING
                for item in pronounced.diagnostics
            )
            and not pronunciation_validation_diagnostics
        )

        sorted_diagnostics = self._sorted_unique_diagnostics(diagnostics)
        return _PipelineResult(
            normalized_text,
            pronunciation_text,
            segments,
            pronunciation_segments,
            tuple(rewrites),
            tuple(sorted_diagnostics),
            complete,
            pronounced.condition_executions,
        )

    @staticmethod
    def _map_pause_boundaries(
        text: str,
        markers: list[Marker],
        pauses: tuple[int, ...],
    ) -> tuple[int, ...]:
        """NFC 원문 좌표를 후보 치환 뒤의 segment 좌표로 옮긴다."""

        ordered = sorted(markers, key=lambda item: (item.start, item.end))
        output_length = len(text) + sum(
            len(marker.text) - (marker.end - marker.start) for marker in ordered
        )
        mapped: list[int] = []
        for pause in pauses:
            shift = 0
            position: int | None = None
            for marker in ordered:
                source_length = marker.end - marker.start
                replacement_length = len(marker.text)
                if pause < marker.start:
                    break
                if pause == marker.start:
                    position = marker.start + shift
                    break
                if marker.start < pause < marker.end:
                    if source_length != replacement_length:
                        raise InputValidationError(
                            "길이가 바뀌는 영문 치환 내부에는 pause 경계를 놓을 수 없습니다."
                        )
                    position = marker.start + shift + pause - marker.start
                    break
                if pause == marker.end:
                    position = marker.start + shift + replacement_length
                    break
                shift += replacement_length - source_length
            if position is None:
                position = pause + shift
            if not 0 <= position <= output_length:
                raise InternalInvariantError("치환 뒤 pause 좌표가 출력 범위를 벗어났습니다.")
            mapped.append(position)
        return tuple(sorted(set(mapped)))

    @staticmethod
    def _numeric_markers(
        text: str,
        numeric_ranges: tuple[tuple[int, int], ...],
    ) -> list[Marker]:
        markers: list[Marker] = []
        for start, end in numeric_ranges:
            markers.append(
                Marker(
                    start,
                    end,
                    text[start:end],
                    Handler.NUMERIC,
                    "numeric_passthrough",
                    "numeric.passthrough",
                    Boundary.HARD,
                )
            )
        return markers

    @staticmethod
    def _preserved_marker(text: str, candidate: Candidate) -> Marker:
        return Marker(
            candidate.start,
            candidate.end,
            text[candidate.start : candidate.end],
            candidate.handler,
            candidate.reason,
            None,
            Boundary.HARD,
        )

    @staticmethod
    def _resolve_candidate(
        text: str,
        candidate: Candidate,
        protected: tuple[ProtectedRange, ...],
    ) -> _Resolution | None:
        """trace 여부와 무관한 외국어 치환 결과만 계산한다."""

        source = text[candidate.start : candidate.end]
        if candidate.handler is Handler.ENGLISH:
            letters = ascii_letter_form(source)
            conventional = CONVENTIONAL_READINGS.get(letters.upper()) if letters else None
            if conventional is not None and is_standalone_latin_word(
                text, candidate.start, candidate.end, protected=protected,
            ):
                return _Resolution(
                    conventional,
                    "english_conventional",
                    "english.conventional.v1",
                )
            resolved = resolve_english(source)
            if resolved is not None:
                return _Resolution(
                    resolved,
                    "english_letter_names",
                    "english.letter_names.v1",
                )
        return None

    @staticmethod
    def _diagnose_unresolved_candidate(
        diagnostics: list[Diagnostic],
        unresolved: list[SourceSpan],
        normalized: NormalizedText,
        candidate: Candidate,
    ) -> None:
        """상세 경로에서만 보존 후보의 원문 좌표와 진단을 만든다."""

        span = normalized.source_span(candidate.start, candidate.end)
        if candidate.handler is Handler.ENGLISH:
            code = "unconverted_latin"
            message = "정규화되지 않은 Latin span을 원문 그대로 보존했습니다."
            rule_id = "routing.latin"
        elif candidate.reason == "ambiguous_han":
            code = "unconverted_han"
            message = "Han-only span을 보존했습니다."
            rule_id = "routing.ambiguous_han"
        else:
            code = "unsupported_script"
            message = "미지원 문자 체계를 보존했습니다."
            rule_id = "routing.unsupported_script"
        Pipeline._diagnose(diagnostics, code, message, span, rule_id)
        unresolved.append(span)

    @staticmethod
    def _diagnose(
        diagnostics: list[Diagnostic],
        code: str,
        message: str,
        span: SourceSpan,
        rule_id: str,
    ) -> None:
        diagnostics.append(
            Diagnostic(code, message, Severity.WARNING, (span,), rule_id, RewriteStage.LEXICAL)
        )

    @staticmethod
    def _sorted_unique_diagnostics(items: list[Diagnostic]) -> list[Diagnostic]:
        seen: set[tuple[str, int, int, str | None]] = set()
        result: list[Diagnostic] = []
        for item in sorted(
            items,
            key=lambda value: (
                value.source_spans[0].start if value.source_spans else -1,
                value.code,
                value.rule_id or "",
            ),
        ):
            span = item.source_spans[0] if item.source_spans else None
            key = (item.code, span.start if span else -1, span.end if span else -1, item.rule_id)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
