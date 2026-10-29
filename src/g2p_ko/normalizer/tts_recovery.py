"""미완료 TTS 토큰의 명확한 수량과 닫힌 꼬리만 복원한다."""

from __future__ import annotations

import re

from ..model import Handler
from .grammar import _KOREAN_SUFFIXES
from .numbers import (
    NumberFormatError,
    has_ambiguous_leading_zero,
    parse_number,
    read_native_or_sino,
    read_sino,
)
from .policy import _Rendered
from .renderers import scale_decimal


# 닫힌 서술격·조사 연결만 허용하며 뒤의 임의 낱말까지 잘라 읽지 않는다.
_RECOVERY_TAILS = _KOREAN_SUFFIXES | frozenset({
    "인", "이니", "이니까", "인가", "인가요", "이랍니다", "이라고요",
    "이란", "이고요", "이면요", "이었는데", "이었어요", "이어요",
    "이에요", "예요", "였어요", "이구요", "이죠", "이요", "나", "동안", "째", "쯤에",
    "까지의", "에도", "이서", "이든", "이든지", "이든가",
})
_TAIL_PATTERN = "(?:" + "|".join(re.escape(x) for x in sorted(_RECOVERY_TAILS,key=lambda x:(-len(x),x))) + ")"

# 번호·횟수·시간·연령 등 여러 해석이 겹치는 번/차/분/대/도는 추가하지 않는다.
_NATIVE_UNITS = frozenset({"개", "명", "마리", "사람", "군데", "곳", "줄", "칸", "자리", "잔", "병", "송이", "켤레", "알", "그루", "포기", "시간", "살", "달"})
_SINO_UNITS = frozenset({"원", "달러", "유로", "엔", "파운드", "위안", "년", "개월", "월", "일", "박", "퍼센트", "프로", "위", "분기", "년대", "년생", "월달"})
_CURRENCIES = frozenset({"원", "달러", "유로", "엔", "파운드", "위안"})
_UNIT_PATTERN = "(?:" + "|".join(re.escape(x) for x in sorted(_NATIVE_UNITS|_SINO_UNITS,key=lambda x:(-len(x),x))) + ")"
_NUMBER_PATTERN = r"[+\-−]?[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?"
_QUANTITY_RE = re.compile(
    rf"(?P<number>{_NUMBER_PATTERN})(?P<scale>십|백|천|만|억|조)?[ \t]*"
    rf"(?P<unit>{_UNIT_PATTERN})(?P<tail>{_TAIL_PATTERN})?(?P<punct>[,.!?])?"
)
_APPROXIMATION_RE = re.compile(rf"(?P<number>{_NUMBER_PATTERN})여")
_APPROXIMATION_UNIT_RE = re.compile(rf"[ \t]+(?P<unit>명|마리|개|원|년|개월|일|박)(?:{_TAIL_PATTERN})?(?![A-Za-z0-9가-힣_])")
_SCALE_POWER = {"십":1,"백":2,"천":3,"만":4,"억":8,"조":12}


def recover_tts_quantity(token: str, rendered: _Rendered, *, previous: str = "", following: str = "") -> _Rendered:
    """원문 전체가 안전한 수량일 때만 복원하고 모델이나 원문 범위는 바꾸지 않는다."""

    if not rendered.unresolved or rendered.diagnostic_code != "ambiguous_numeric":
        return rendered
    if previous and (previous.isalnum() or previous in "_."):
        return rendered
    match = _QUANTITY_RE.fullmatch(token)
    approximation = _APPROXIMATION_RE.fullmatch(token) if match is None else None
    if match is None and approximation is None:
        return rendered
    if approximation is not None:
        # 떨어져 쓴 'N여 명'은 토큰을 넓히지 않고 명시적 단위를 읽기 근거로만 쓴다.
        if _APPROXIMATION_UNIT_RE.match(following) is None:
            return rendered
        number = approximation.group("number")
        unit, tail, punct, scale = "", "", "", None
    else:
        assert match is not None
        number = match.group("number")
        unit = match.group("unit")
        tail = match.group("tail") or ""
        punct = match.group("punct") or ""
        scale = match.group("scale")
    try:
        parsed = parse_number(number)
        if has_ambiguous_leading_zero(parsed) or len(parsed.integer) > 10:
            return rendered
        # 세 자리 소수부가 천 단위 구분점일 가능성은 새 경로에서도 보류한다.
        if parsed.fraction is not None and len(parsed.fraction) == 3:
            return rendered
        if approximation is not None and (parsed.sign or parsed.fraction is not None or int(parsed.integer) < 10):
            return rendered
        if unit in {"위", "분기", "년대", "년생", "월", "월달"}:
            if parsed.sign or parsed.fraction is not None or scale is not None:
                return rendered
            magnitude = int(parsed.integer)
            if unit == "위" and magnitude < 1:
                return rendered
            if unit == "분기" and not 1 <= magnitude <= 4:
                return rendered
            if unit in {"월", "월달"} and not 1 <= magnitude <= 12:
                return rendered
        if scale is not None:
            # 범위·계층 사슬은 기존 파서에 맡기고 명시적 단일 금액 배율만 복원한다.
            if unit not in _CURRENCIES:
                return rendered
            number = scale_decimal(number,_SCALE_POWER[scale])
        spoken = read_native_or_sino(number) if unit in _NATIVE_UNITS else read_sino(number)
    except NumberFormatError:
        return rendered
    if approximation is not None:
        text = spoken + "여"
    elif unit in {"월", "월달"} and parsed.integer in {"6", "10"}:
        text = ("유" if parsed.integer == "6" else "시") + unit + tail + punct
    else:
        text = f"{spoken} {unit}{tail}{punct}"
    return _Rendered(text,Handler.NUMERIC,"normalizer.tts.quantity_recovery.v1")
