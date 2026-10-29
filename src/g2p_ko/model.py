"""공개 결과와 단계 사이 계약에 쓰는 불변 모델을 정의한다."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from .analysis_features import freeze_morphemes


class RewriteStage(str, Enum):
    """문자열 변화나 진단이 발생한 파이프라인 단계를 나타낸다."""

    UNICODE = "unicode"
    LEXICAL = "lexical"
    VERBALIZATION = "verbalization"
    PHONOLOGY = "phonology"
    VALIDATION = "validation"


class Boundary(str, Enum):
    """인접 조각 사이에서 후속 음운 규칙이 넘을 수 있는 경계다."""

    MORPHEME = "morpheme"
    WORD = "word"
    HARD = "hard"


class Handler(str, Enum):
    """한 조각을 소유한 처리기의 안정적인 이름이다."""

    KOREAN = "korean"
    PROTECTED = "protected"
    NUMERIC = "numeric"
    ENGLISH = "english"


class Severity(str, Enum):
    """진단의 사용자 영향 수준이다."""

    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """원문 code point 좌표와 정규화 전 표면형을 함께 보존한다."""

    start: int
    end: int
    surface: str
    source_length: int

    def __post_init__(self) -> None:
        if not (0 <= self.start <= self.end <= self.source_length):
            raise ValueError("SourceSpan 좌표가 원문 범위를 벗어났습니다.")
        if len(self.surface) != self.end - self.start:
            raise ValueError("SourceSpan 표면형 길이가 좌표 길이와 다릅니다.")

    @classmethod
    def from_source(cls, source: str, start: int, end: int) -> SourceSpan:
        """원문 문자열에서 검증된 span을 만든다."""

        return cls(start, end, source[start:end], len(source))

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 값을 반환한다."""

        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class AnalysisToken:
    """분석기가 반환하는 형태소 경계 annotation의 최소 표현이다."""

    form: str
    tag: str
    normalized_start: int
    normalized_end: int
    morphemes: tuple[tuple[str, str], ...] = ()
    morpheme_spans: tuple[tuple[int, int], ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.normalized_start < 0 or self.normalized_end <= self.normalized_start:
            raise ValueError("AnalysisToken 정규화 좌표가 올바르지 않습니다.")
        object.__setattr__(self, "morphemes", freeze_morphemes(self.morphemes))
        spans = tuple(tuple(span) for span in self.morpheme_spans)
        if spans and (len(spans) != len(self.morphemes) or any(
            len(span) != 2 or any(isinstance(value, bool) or not isinstance(value, int) for value in span)
            or not self.normalized_start <= span[0] <= span[1] <= self.normalized_end
            for span in spans
        )):
            raise ValueError("형태소 원시 범위가 표면 token과 일치하지 않습니다.")
        object.__setattr__(self, "morpheme_spans", spans)

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class OutputSegment:
    """하나의 출력 조각과 그 원문 근거·경계를 기록한다."""

    text: str
    source_spans: tuple[SourceSpan, ...]
    handler: Handler
    reason: str
    rule_id: str | None = None
    boundary_before: Boundary = Boundary.WORD
    boundary_after: Boundary = Boundary.WORD
    insertion_rule: str | None = None
    anchor: SourceSpan | None = None

    def __post_init__(self) -> None:
        if not self.source_spans and (not self.insertion_rule or self.anchor is None):
            raise ValueError("삽입 OutputSegment에는 insertion_rule과 anchor가 필요합니다.")
        if tuple(sorted(self.source_spans, key=lambda item: (item.start, item.end))) != self.source_spans:
            raise ValueError("OutputSegment의 원문 span은 원문 순서여야 합니다.")

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class Rewrite:
    """단계별 문자열 변화와 규칙 provenance를 남긴다."""

    source_spans: tuple[SourceSpan, ...]
    before: str
    after: str
    handler: Handler
    rule_id: str
    stage: RewriteStage

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("Rewrite에는 규칙 ID가 필요합니다.")
        if not self.source_spans:
            raise ValueError("Rewrite에는 적어도 하나의 원문 span이 필요합니다.")

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """원문 보존 또는 구성 실패의 구조화된 설명이다."""

    code: str
    message: str
    severity: Severity
    source_spans: tuple[SourceSpan, ...] = ()
    rule_id: str | None = None
    stage: RewriteStage | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Diagnostic에는 코드가 필요합니다.")

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """진단 span이 가리키는 단계 입력과 진단 목록을 함께 묶는다."""

    source: str
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        for diagnostic in self.diagnostics:
            for span in diagnostic.source_spans:
                if (
                    span.source_length != len(self.source)
                    or self.source[span.start : span.end] != span.surface
                ):
                    raise ValueError(
                        "DiagnosticReport의 진단 span이 source와 일치하지 않습니다."
                    )

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 값을 반환한다."""

        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class G2PDiagnostics:
    """좌표계가 다른 정규화·발음 단계 진단을 분리해 보존한다."""

    normalization: DiagnosticReport
    pronunciation: DiagnosticReport

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 값을 반환한다."""

        return _to_json_value(self)


@dataclass(frozen=True, slots=True)
class G2PResult:
    """원문부터 표면 발음까지의 공개 상세 변환 결과다."""

    source: str
    normalized_text: str
    surface_pronunciation: str
    diagnostics: G2PDiagnostics
    complete: bool

    def __post_init__(self) -> None:
        if self.diagnostics.normalization.source != self.source:
            raise ValueError("정규화 진단의 source가 G2P 원문과 다릅니다.")
        if self.complete and len(self.normalized_text) != len(self.surface_pronunciation):
            raise ValueError("완료된 G2P 결과의 code point 길이가 다릅니다.")

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화 가능한 값을 반환한다."""

        return _to_json_value(self)


def _to_json_value(value: Any) -> Any:
    """공개 모델만 허용하는 JSON 호환 재귀 변환기다."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _to_json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple | list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    return value
