"""단계 순서·실패 격리·trace 병합을 담당하는 정규화 파이프라인이다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .errors import InternalInvariantError
from .english import resolve_english
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
from .validation import validate_output
from .routing import Candidate, is_unsupported_script_character, route_candidates
from .scanner import ProtectedRange, scan_protected
from .unicode import NormalizedText, normalize_nfc, normalize_nfc_text


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
    rewrites: tuple[Rewrite, ...]
    diagnostics: tuple[Diagnostic, ...]
    complete: bool


class Pipeline:
    """발화형 문자열을 영문 철자화와 표면 발음 결과로 조합한다."""

    def __init__(
        self,
        *,
        max_length: int,
    ) -> None:
        self._max_length = max_length

    def run(
        self,
        source: str,
    ) -> _PipelineResult:
        """영문 철자화와 한국어 표면 발음 단계를 모두 실행한다."""

        return cast(_PipelineResult, self._run(source, trace=True))

    def run_text(self, source: str) -> str:
        """trace와 상세 결과 model 없이 표면 발음 문자열만 반환한다."""

        return cast(str, self._run(source, trace=False))

    def _run(self, source: str, *, trace: bool) -> _PipelineResult | str:
        """라우팅 의미를 공유하고 상세 model 생성만 선택적으로 수행한다."""

        if trace:
            normalized = normalize_nfc(source, max_length=self._max_length)
            text = normalized.text
            protected = self._snap_protected(
                normalized,
                scan_protected(text),
            )
        else:
            normalized = None
            text = normalize_nfc_text(source, max_length=self._max_length)
            protected = scan_protected(text)
        routed = route_candidates(text, protected)

        diagnostics: list[Diagnostic] | None = [] if trace else None
        unresolved: list[SourceSpan] | None = [] if trace else None
        rewrites: list[Rewrite] | None = (
            list(normalized.rewrites) if normalized is not None else None
        )
        markers = self._base_markers(text, protected, routed.numeric_ranges)
        if normalized is not None and diagnostics is not None and unresolved is not None:
            self._apply_protected_script_policy(
                diagnostics,
                unresolved,
                normalized,
                protected,
            )
            for candidate in routed.opaque_candidates:
                self._preserve_opaque_candidate(
                    diagnostics,
                    unresolved,
                    normalized,
                    candidate,
                )

        for candidate in routed.candidates:
            resolution = self._resolve_candidate(text, candidate)
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

        if normalized is None:
            text_segments = merge_text_segments(text, markers)
            pronunciation_text = pronounce_text(text_segments)
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

        pronounced = pronounce(segments)
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
            tuple(rewrites),
            tuple(sorted_diagnostics),
            complete,
        )

    @staticmethod
    def _base_markers(
        text: str,
        protected: tuple[ProtectedRange, ...],
        numeric_ranges: tuple[tuple[int, int], ...],
    ) -> list[Marker]:
        markers: list[Marker] = []
        for item in protected:
            markers.append(
                Marker(
                    item.start,
                    item.end,
                    text[item.start : item.end],
                    Handler.PROTECTED,
                    f"protected_{item.kind}",
                    f"protected.{item.kind}",
                    Boundary.HARD,
                )
            )
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
    ) -> _Resolution | None:
        """trace 여부와 무관한 외국어 치환 결과만 계산한다."""

        source = text[candidate.start : candidate.end]
        if candidate.handler is Handler.ENGLISH:
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
    def _preserve_opaque_candidate(
        diagnostics: list[Diagnostic],
        unresolved: list[SourceSpan],
        normalized: NormalizedText,
        candidate: Candidate,
    ) -> None:
        """숫자 구조 내부 후보는 resolver에 보내지 않고 문자 체계만 보고한다."""

        span = normalized.source_span(candidate.start, candidate.end)
        if candidate.handler is Handler.ENGLISH:
            Pipeline._diagnose(
                diagnostics,
                "unconverted_latin",
                "숫자 포함 Latin 구조는 부분 변환하지 않고 보존했습니다.",
                span,
                "routing.numeric_latin",
            )
        else:
            Pipeline._diagnose(
                diagnostics,
                "unconverted_han",
                "숫자 포함 Han 구조는 부분 변환하지 않고 보존했습니다.",
                span,
                "routing.numeric_han",
            )
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
    def _apply_protected_script_policy(
        diagnostics: list[Diagnostic],
        unresolved: list[SourceSpan],
        normalized: NormalizedText,
        protected: tuple[ProtectedRange, ...],
    ) -> None:
        """보호 구간 내부의 미지원 alpha도 진단하고 보존한다."""

        for item in protected:
            index = item.start
            while index < item.end:
                if not is_unsupported_script_character(normalized.text[index]):
                    index += 1
                    continue
                start = index
                while (
                    index < item.end
                    and is_unsupported_script_character(normalized.text[index])
                ):
                    index += 1
                span = normalized.source_span(start, index)
                Pipeline._diagnose(
                    diagnostics,
                    "unsupported_script",
                    "보호 구간 내 미지원 문자 체계를 보존했습니다.",
                    span,
                    "routing.protected_unsupported_script",
                )
                unresolved.append(span)

    @staticmethod
    def _snap_protected(
        normalized: NormalizedText,
        ranges: tuple[ProtectedRange, ...],
    ) -> tuple[ProtectedRange, ...]:
        result: list[ProtectedRange] = []
        for item in ranges:
            start, end = normalized.snap_range(item.start, item.end)
            if result and start < result[-1].end:
                previous = result[-1]
                result[-1] = ProtectedRange(previous.start, max(previous.end, end), previous.kind)
            else:
                result.append(ProtectedRange(start, end, item.kind))
        return tuple(result)

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
