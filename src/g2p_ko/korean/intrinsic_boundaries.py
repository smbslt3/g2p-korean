# SPDX-License-Identifier: MIT
"""정확한 원형 소유의 최소 내재 경계 속성을 파생 구조 사실과 분리한다."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntrinsicBoundaryFact:
    """완성 발음이나 숨은 형태소 없이 다섯 필드의 국소 속성만 보존한다."""

    canonical_owner: str
    owner_pos: frozenset[str]
    boundary_offset: int
    property: str
    source_ids: tuple[str, ...]


# 허가된 한 건의 국립국어원 사실만 보존한다. 파생·합성·제29항 권한은 아니다.
INTRINSIC_BOUNDARY_FACTS = (
    IntrinsicBoundaryFact("곧이듣", frozenset({"VV"}), 1, "intrinsic_palatalization", ("nikl_krdict_27702",)),
)
