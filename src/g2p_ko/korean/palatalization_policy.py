# SPDX-License-Identifier: MIT
"""등록된 음절 경계를 사용해 어휘 구개음화 후보를 판정한다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PalatalizationBoundary:
    """표기와 시작·끝 기준으로 허용한 내부 구개음화 경계를 보관한다."""

    spelling: str
    offset: int
    scope: str
    owner_pos: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.spelling, str) or not self.spelling:
            raise ValueError("구개음화 경계 표기는 비어 있지 않아야 합니다.")
        if type(self.offset) is not int or not 0 < self.offset < len(self.spelling):
            raise ValueError("구개음화 경계 offset은 표기 내부의 양의 정수여야 합니다.")
        if self.scope not in {"exact", "prefix", "suffix"}:
            raise ValueError("구개음화 경계 범위는 exact, prefix, suffix 중 하나여야 합니다.")
        owner_pos = frozenset(self.owner_pos)
        if self.scope == "exact":
            if not owner_pos or not owner_pos <= {"NNG", "NNP"}:
                raise ValueError("exact 구개음화 owner는 NNG 또는 NNP로 선언해야 합니다.")
        elif owner_pos:
            raise ValueError("prefix·suffix 경계에는 exact owner 품사를 선언하지 않습니다.")
        object.__setattr__(self, "owner_pos", owner_pos)

    def matches(self, owner_form: str, boundary_offset: int) -> bool:
        """한 owner의 음절 경계가 선언한 exact·prefix·suffix 위치인지 판정한다."""
        if self.scope == "exact":
            return owner_form == self.spelling and boundary_offset == self.offset
        if self.scope == "prefix":
            return owner_form.startswith(self.spelling) and boundary_offset == self.offset
        suffix_start = len(owner_form) - len(self.spelling)
        return (
            suffix_start >= 0
            and owner_form.endswith(self.spelling)
            and boundary_offset == suffix_start + self.offset
        )


# 파생 명사 안에서 확인한 경계는 어휘 시작을 기준으로 선언한다.
PALATALIZATION_BOUNDARIES = (
    PalatalizationBoundary("미닫이", 2, "prefix"),
    PalatalizationBoundary("여닫이", 2, "prefix"),
    PalatalizationBoundary("땀받이", 2, "prefix"),
    PalatalizationBoundary("벼훑이", 2, "prefix"),
    PalatalizationBoundary("해돋이", 2, "prefix"),
    PalatalizationBoundary("맏이", 1, "prefix"),
    PalatalizationBoundary("같이", 1, "prefix"),
    # ‘붙이’ 접미 경계는 포함 어휘의 끝에 있을 때만 허용한다.
    PalatalizationBoundary("붙이", 1, "suffix"),
    # 전체 명사 owner 또는 NNG 성분열을 확인한 뒤에만 쓰는 정확 속성이다.
    PalatalizationBoundary("붙임머리", 1, "exact", frozenset({"NNG", "NNP"})),
)


def matching_palatalization_boundaries(
    owner_form: str,
    boundary_offset: int,
) -> tuple[PalatalizationBoundary, ...]:
    """문자열 비교 규칙을 공유해 해당 표면 owner의 등록 경계를 반환한다."""
    return tuple(
        feature
        for feature in PALATALIZATION_BOUNDARIES
        if feature.matches(owner_form, boundary_offset)
    )
