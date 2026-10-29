# SPDX-License-Identifier: MIT
"""분리된 한자어 기반과 등록 후행 성분의 결합 가능성을 검사한다."""


def licenses_nominal_attachment(
    *,
    base_form: str,
    base_tag: str,
    tail_form: str,
    tail_tag: str,
    verified_base: bool,
    expected_tail_form: str,
    expected_tail_tag: str,
    nasal_liquid: bool,
    whole_hanja_compatible: bool,
) -> bool:
    """호출자가 제공한 분석과 등록 정보가 모든 결합 조건을 만족하는지 반환한다."""
    if not (verified_base and nasal_liquid and whole_hanja_compatible):
        return False

    # 현대 한글 완성형 음절 두 개로 이루어진 기반만 허용한다.
    if len(base_form) != 2 or not all("가" <= char <= "힣" for char in base_form):
        return False

    base_components = base_tag.split("+")
    tail_components = tail_tag.split("+")

    # 조사나 어미가 섞이면 각 독립 품사 구성 요소에서 차단한다.
    if any(
        component.startswith(("J", "E"))
        for component in base_components + tail_components
    ):
        return False

    if not any(component.startswith("NN") for component in base_components):
        return False

    # 등록 품사는 정확한 구성 요소로 대조하며 분석 태그를 바꾸지 않는다.
    if expected_tail_tag not in ("NNG", "XSN"):
        return False
    if tail_form != expected_tail_form:
        return False
    if expected_tail_tag not in tail_components:
        return False

    return True
