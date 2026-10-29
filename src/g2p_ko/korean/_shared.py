"""한국어 음운 규칙과 형태소 판정이 공유하는 내부 단위와 경계 연산이다."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

from ..merge import _TextSegment
from ..model import Boundary, Handler, OutputSegment, Rewrite, RewriteStage, SourceSpan
from .hangul import HangulToken


_Segment = OutputSegment | _TextSegment


class _RewriteLog(list):
    """실제 규칙 호출의 정확한 양끝을 span 추측 없이 함께 보존한다."""
    def __init__(self):
        super().__init__()
        self.pair_rules = {}

    def record_pair(self, left, right, rule_id):
        rules = self.pair_rules.setdefault((left, right), [])
        if rule_id not in rules:
            rules.append(rule_id)


@dataclass(slots=True)
class _Unit:
    """한 출력 문자와 변환 중 바뀔 수 있는 음운 토큰을 함께 보관한다."""

    segment_index: int
    handler: Handler
    source_spans: tuple[SourceSpan, ...]
    raw: str | None = None
    syllable: HangulToken | None = None

    @property
    def text(self) -> str:
        if self.syllable is not None:
            return self.syllable.text
        assert self.raw is not None
        return self.raw


def _next_syllable(
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    index: int,
) -> tuple[int, bool] | None:
    """공백만 건너뛴 다음 한국어 음절과 단어 경계 여부를 찾는다."""

    crossed_space = False
    for candidate in range(index + 1, len(units)):
        unit = units[candidate]
        if unit.syllable is not None:
            if unit.handler is not Handler.KOREAN:
                return None
            if _has_hard_boundary(units[index].segment_index, unit.segment_index, segments):
                return None
            return candidate, crossed_space
        # U+0020만 단어 사이 공백으로 허용한다. 탭·줄바꿈은 구·문장 경계를 넘지 않는다.
        if unit.handler is not Handler.KOREAN or unit.raw != " ":
            return None
        crossed_space = True
    return None


def _has_hard_boundary(
    left_segment: int,
    right_segment: int,
    segments: tuple[_Segment, ...],
) -> bool:
    if left_segment == right_segment:
        return False
    start, end = sorted((left_segment, right_segment))
    for index in range(start, end):
        if (
            segments[index].boundary_after is Boundary.HARD
            or segments[index + 1].boundary_before is Boundary.HARD
        ):
            return True
    return False


def _pair_text(units: list[_Unit], left: int, right: int) -> str:
    return "".join(unit.text for unit in units[left : right + 1])


def _trace_before(
    rewrites: list[Rewrite] | None,
    units: list[_Unit],
    left: int,
    right: int,
) -> str:
    """상세 추적을 사용할 때만 규칙 적용 전 문자열을 복사한다."""

    return _pair_text(units, left, right) if rewrites is not None else ""


def _record(
    rewrites: list[Rewrite] | None,
    units: list[_Unit],
    left: int,
    right: int,
    before: str,
    rule_id: str,
) -> None:
    if rewrites is None:
        return
    after = _pair_text(units, left, right)
    if before == after:
        return
    if isinstance(rewrites, _RewriteLog):
        rewrites.record_pair(left, right, rule_id)
    source_spans = _ordered_unique_spans(
        span for unit in units[left : right + 1] for span in unit.source_spans
    )
    rewrites.append(
        Rewrite(source_spans, before, after, Handler.KOREAN, rule_id, RewriteStage.PHONOLOGY)
    )


def _ordered_unique_spans(spans: Iterable[SourceSpan]) -> tuple[SourceSpan, ...]:
    unique: dict[tuple[int, int, str], SourceSpan] = {}
    for span in spans:
        unique.setdefault((span.start, span.end, span.surface), span)
    return tuple(sorted(unique.values(), key=lambda item: (item.start, item.end, item.surface)))


def _is_blocked_pair(
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    left: int,
    right: int,
) -> bool:
    return left in blocked_units or right in blocked_units or (left, right) in blocked_pairs


def _has_phonological_barrier(
    units: list[_Unit],
    left: int,
    right: int,
    segments: tuple[_Segment, ...],
    pause_boundaries: tuple[int, ...],
) -> bool:
    """두 음운 단위 사이의 HARD 또는 명시적 pause 경계를 찾는다."""

    if left > right:
        left, right = right, left
    if _has_hard_boundary(
        units[left].segment_index,
        units[right].segment_index,
        segments,
    ):
        return True
    index = bisect_right(pause_boundaries, left)
    return index < len(pause_boundaries) and pause_boundaries[index] <= right


def _is_blocked_phonological_pair(
    blocked_pairs: frozenset[tuple[int, int]],
    blocked_units: frozenset[int],
    units: list[_Unit],
    segments: tuple[_Segment, ...],
    left: int,
    right: int,
    pause_boundaries: tuple[int, ...],
) -> bool:
    """분석 불확실성이나 음운 경계에 걸친 pair를 차단한다."""

    return _is_blocked_pair(blocked_pairs, blocked_units, left, right) or (
        _has_phonological_barrier(units, left, right, segments, pause_boundaries)
    )
