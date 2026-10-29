"""현재 배포용 숫자 전처리의 공개 동작이다."""

from __future__ import annotations

from .errors import InputValidationError


def normalize_numbers(text: str) -> str:
    """숫자를 변환하지 않고 입력을 그대로 돌려준다."""

    if not isinstance(text, str):
        raise InputValidationError("text는 문자열이어야 합니다.")
    return text
