# SPDX-License-Identifier: MIT
"""독립 명세에 따른 ㄴ 첨가 경계와 후행 ㄹ 성분 분석 후보 판정."""

from __future__ import annotations


def _parts(tag: str) -> tuple[str, ...]:
    """복합 태그를 비어 있지 않은 독립 구성 요소로 나눈다."""
    return tuple(part.strip() for part in tag.split("+") if part.strip())


def _has(parts: tuple[str, ...], prefix: str) -> bool:
    """독립 태그 구성 요소가 지정된 유형으로 시작하는지 검사한다."""
    return any(part.startswith(prefix) for part in parts)


def licenses_n_insertion(
    *,
    left_form: str,
    left_tag: str,
    right_form: str,
    right_tag: str,
    declared_boundary: bool,
    saisiot: bool,
) -> bool:
    """음운 조건을 이미 통과한 두 성분의 문법적 경계만 판정한다."""
    left_parts = _parts(left_tag)
    right_parts = _parts(right_tag)

    # 조사를 포함한 오른쪽 범위는 경계 허용 근거로 삼지 않는다.
    if _has(right_parts, "J"):
        return False

    # 왼쪽의 관형형 어미는 명시적으로 허용하되 다른 문법 범위는 섞지 않는다.
    if _has(left_parts, "J") or any(
        part.startswith("E") and not part.startswith("ETM")
        for part in left_parts
    ):
        return False

    left_prefix = _has(left_parts, "XPN")
    right_verb = _has(right_parts, "V")

    # 접두사 뒤의 실제 용언은 어미와 표면 범위를 공유해도 경계를 보존한다.
    if _has(right_parts, "E"):
        return left_prefix and right_verb

    right_noun = _has(right_parts, "NNG")
    right_noun_suffix = _has(right_parts, "XSN")

    if declared_boundary and (right_noun or right_noun_suffix):
        return True
    if saisiot and right_noun:
        return True
    if left_prefix and (right_noun or right_verb):
        return True
    if _has(left_parts, "ETM") and right_noun:
        return True
    if _has(left_parts, "NN") and right_form == "용" and right_noun_suffix:
        return True
    return False


def needs_suffix_liquid_analysis(
    *,
    left_coda: str | None,
    right_onset: str,
    has_two_syllable_base_candidate: bool,
    crossed_space: bool,
) -> bool:
    """단어 안의 ㄴ·ㄹ 경계가 후행 성분 분석 후보인지 판정한다.

    참인 결과는 형태소 분석을 요청할 근거이며 발음 결정을 뜻하지 않는다.
    """
    return (
        left_coda == "ㄴ"
        and right_onset == "ㄹ"
        and has_two_syllable_base_candidate
        and not crossed_space
    )
