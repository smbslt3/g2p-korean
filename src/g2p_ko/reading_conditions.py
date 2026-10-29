"""원문 좌표의 명시 읽기 조건과 별도 실행 기록을 정의한다."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Literal

from .alignment import G2PAlignedResult
from .errors import InputValidationError
from .unicode import NormalizedText

ReadingRelation = Literal["ordinary_liaison", "one_madi", "pause"]
_RELATIONS = frozenset({"ordinary_liaison", "one_madi", "pause"})


@dataclass(frozen=True, slots=True)
class ReadingBoundary:
    """원문 Python code point 사이의 좌표와 호출자가 선택한 관계다."""

    offset: int
    relation: ReadingRelation

    def __post_init__(self) -> None:
        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise InputValidationError("읽기 조건의 원문 좌표는 정수여야 합니다.")
        if not isinstance(self.relation, str) or self.relation not in _RELATIONS:
            raise InputValidationError("지원하지 않는 읽기 경계 관계입니다.")


@dataclass(frozen=True, slots=True)
class _MappedReadingBoundary:
    """원문과 단계별 좌표를 잃지 않고 전달하는 내부 요청이다."""

    source_offset: int
    nfc_offset: int
    output_offset: int
    relation: ReadingRelation


@dataclass(frozen=True, slots=True)
class ReadingBoundaryExecution:
    """관계 선택, 음운 적용 가능성, 실제 소리 변화를 구분한다."""

    source_offset: int
    nfc_offset: int
    output_offset: int
    relation: ReadingRelation
    output_pair: tuple[int, int] | None
    status: str
    reason: str
    applicability: str
    sound_effect: str
    rule_ids: tuple[str, ...] = ()
    source_prosody_observed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class G2PReadingConditionResult:
    """기존 결과와 정렬에 조건 실행 sidecar를 더한다."""

    aligned: G2PAlignedResult
    boundary_executions: tuple[ReadingBoundaryExecution, ...]

    def to_dict(self) -> dict:
        return {
            "schema": "g2p_reading_conditions.v1",
            "aligned": {
                "result": self.aligned.result.to_dict(),
                "alignment": self.aligned.alignment.to_dict(),
            },
            "boundary_executions": [item.to_dict() for item in self.boundary_executions],
            "source_prosody_observed": False,
        }


def prepare_reading_boundaries(
    normalization: NormalizedText,
    requests: Iterable[ReadingBoundary],
) -> tuple[_MappedReadingBoundary, ...]:
    """NFC 원자 단위의 정확한 가장자리만 원문 좌표에서 옮긴다."""

    if isinstance(requests, (str, bytes)) or not isinstance(requests, Iterable):
        raise InputValidationError("reading_conditions는 ReadingBoundary iterable이어야 합니다.")
    spans = normalization.character_spans
    raw_to_nfc = {0: 0, len(normalization.source): len(normalization.text)}
    for index in range(1, len(spans)):
        if spans[index - 1].end == spans[index].start:
            raw_to_nfc[spans[index].start] = index
    result = []
    for request in requests:
        if not isinstance(request, ReadingBoundary):
            raise InputValidationError("읽기 조건 항목은 ReadingBoundary여야 합니다.")
        if not 0 <= request.offset <= len(normalization.source):
            raise InputValidationError("읽기 조건의 좌표가 원문 범위를 벗어났습니다.")
        if request.offset not in raw_to_nfc:
            raise InputValidationError("NFC 정규화 원자 내부에는 읽기 경계를 놓을 수 없습니다.")
        mapped = raw_to_nfc[request.offset]
        result.append(_MappedReadingBoundary(request.offset, mapped, mapped, request.relation))
    return tuple(result)
