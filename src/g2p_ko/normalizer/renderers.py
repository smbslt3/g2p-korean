"""문맥 판별이 필요 없는 숫자·단위·달력 표기를 발화형으로 렌더링한다."""

from __future__ import annotations

from datetime import date
import re

from ..errors import InternalInvariantError
from ..model import Handler
from .grammar import (
    _DATE_RE,
    _EXPONENT_RE,
    _FRACTION_RE,
    _INDEFINITE_UNIT_RE,
    _KOREAN_DATE_RE,
    _MONTH_DAY_RE,
    _MONTH_RE,
    _PERCENT_RE,
    _STANDALONE_UNIT_SYMBOL_RE,
    _UNIT_PER_RE,
    _YEAR_MONTH_RE,
)
from .numbers import (
    NumberFormatError,
    ParsedNumber,
    has_ambiguous_leading_zero,
    parse_number,
    read_sino,
)
from .policy import _Rendered, ambiguous
from .units import (
    _CURRENCY_UNIT_WORDS,
    _SPEED_UNIT_READINGS,
    _UNIT_READINGS,
)


def may_be_thousands_separator(parsed: ParsedNumber) -> bool:
    return parsed.fraction is not None and len(parsed.fraction) == 3


def expected_match(pattern: re.Pattern[str], token: str) -> re.Match[str]:
    """스캐너가 이미 확정한 토큰의 내부 정규식 불일치를 즉시 드러낸다."""

    match = pattern.fullmatch(token)
    if match is None:
        raise InternalInvariantError(f"스캐너와 렌더러의 토큰 규칙이 다릅니다: {token!r}")
    return match


def scale_decimal(surface: str, power: int) -> str:
    """float 없이 10의 거듭제곱을 곱해 축약 금액의 모든 자릿수를 보존한다."""

    parsed = parse_number(surface)
    fraction = parsed.fraction or ""
    digits = parsed.integer + fraction
    remaining_fraction = len(fraction) - power
    if remaining_fraction <= 0:
        integer = digits + "0" * (-remaining_fraction)
        scaled_fraction = ""
    else:
        split_at = len(digits) - remaining_fraction
        integer = digits[:split_at] or "0"
        scaled_fraction = digits[split_at:]
    integer = integer.lstrip("0") or "0"
    result = integer
    if scaled_fraction:
        result += "." + scaled_fraction
    return parsed.sign + result


def format_quantity(
    spoken_number: str,
    unit: str,
    *,
    number_suffix: str = "",
    include_speed_prefix: bool = True,
) -> str:
    """숫자 발화와 단위를 결합하고 이동 속도만 한국어 어순으로 전치한다."""

    speed = _SPEED_UNIT_READINGS.get(unit)
    if speed is not None:
        body = f"{spoken_number}{number_suffix} {speed[1]}"
        return f"{speed[0]} {body}" if include_speed_prefix else body
    return f"{spoken_number}{number_suffix} {_UNIT_READINGS.get(unit, unit)}"


def render_indefinite_unit(token: str) -> _Rendered:
    match = expected_match(_INDEFINITE_UNIT_RE, token)
    return _Rendered(
        format_quantity(match.group("quantifier"), match.group("unit")),
        Handler.NUMERIC,
        "normalizer.indefinite_unit.v1",
    )


def render_unit_per(token: str) -> _Rendered:
    match = expected_match(_UNIT_PER_RE, token)
    return _Rendered(
        _UNIT_READINGS[match.group("unit")] + "당" + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.unit_per.v1",
    )


def render_standalone_unit_symbol(token: str) -> _Rendered:
    match = expected_match(_STANDALONE_UNIT_SYMBOL_RE, token)
    return _Rendered(
        _UNIT_READINGS[match.group("unit")] + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.standalone_unit_symbol.v1",
    )


def render_number(
    number: str,
    *,
    suffix: str = "",
    rule_id: str,
    original: str | None = None,
    allow_long: bool = False,
) -> _Rendered:
    source = original if original is not None else number + suffix
    try:
        parsed = parse_number(number)
        if has_ambiguous_leading_zero(parsed) and parsed.fraction is None:
            return ambiguous(
                source,
                "ambiguous_numeric",
                "선행 0이 있는 숫자의 용도를 확정할 수 없습니다.",
            )
        if suffix in _CURRENCY_UNIT_WORDS and may_be_thousands_separator(parsed):
            return ambiguous(
                source,
                "ambiguous_numeric",
                "점이 천 단위 구분점일 수 있어 원문을 보존합니다.",
            )
        if not allow_long and len(parsed.integer) > 10:
            return ambiguous(
                source,
                "ambiguous_numeric",
                "긴 숫자가 식별번호인지 수량인지 확정할 수 없습니다.",
            )
        spoken = read_sino(number)
    except NumberFormatError:
        return ambiguous(
            source,
            "ambiguous_numeric",
            "숫자 표면형을 손실 없이 읽을 수 없습니다.",
        )
    return _Rendered(spoken + (f" {suffix}" if suffix else ""), Handler.NUMERIC, rule_id)


def render_fraction(token: str) -> _Rendered:
    match = expected_match(_FRACTION_RE, token)
    try:
        numerator_number = parse_number(match.group("numerator"))
        denominator_number = parse_number(match.group("denominator"))
        if numerator_number.fraction is not None or denominator_number.fraction is not None:
            return ambiguous(token, "ambiguous_numeric", "소수의 슬래시 표기를 분수로 단정하지 않습니다.")
        if has_ambiguous_leading_zero(numerator_number) or has_ambiguous_leading_zero(denominator_number):
            return ambiguous(token, "ambiguous_numeric", "선행 0이 있는 분수의 용도를 확정할 수 없습니다.")
        if int(denominator_number.integer) == 0:
            return ambiguous(token, "ambiguous_numeric", "분모가 0인 표기를 분수로 읽지 않습니다.")
        denominator = read_sino(match.group("denominator"))
        numerator = read_sino(match.group("numerator"))
    except NumberFormatError:
        return ambiguous(token, "ambiguous_numeric", "분수를 손실 없이 읽을 수 없습니다.")
    return _Rendered(f"{denominator}분의 {numerator}", Handler.NUMERIC, "normalizer.fraction.v1")


def render_percentage(token: str) -> _Rendered:
    match = expected_match(_PERCENT_RE, token)
    suffix = "퍼센트포인트" if match.group("unit").lower() == "%p" else "퍼센트"
    return render_number(
        match.group("number"),
        suffix=suffix,
        rule_id="normalizer.percentage.v1",
        original=token,
    )


def _spoken_month(month: int) -> str:
    if month == 6:
        return "유월"
    if month == 10:
        return "시월"
    return f"{read_sino(str(month))} 월"


def render_date(token: str, *, korean: bool = False) -> _Rendered:
    match = expected_match(_KOREAN_DATE_RE if korean else _DATE_RE, token)
    year, month, day = (int(match.group(item)) for item in ("year", "month", "day"))
    try:
        date(year, month, day)
    except ValueError:
        return ambiguous(token, "ambiguous_numeric", "유효하지 않은 달력 날짜입니다.")
    month_text = _spoken_month(month)
    return _Rendered(
        f"{read_sino(str(year))} 년 {month_text} {read_sino(str(day))} 일"
        + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.calendar_date.v1",
    )


def render_month_day(token: str) -> _Rendered:
    """연도 없는 한국어 월·일 표기를 윤년 기준으로 검증한다."""

    match = expected_match(_MONTH_DAY_RE, token)
    month, day = (int(match.group(item)) for item in ("month", "day"))
    try:
        date(2000, month, day)
    except ValueError:
        return ambiguous(token, "ambiguous_numeric", "유효하지 않은 월·일 표기입니다.")
    month_text = _spoken_month(month)
    return _Rendered(
        f"{month_text} {read_sino(str(day))} 일" + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.calendar_month_day.v1",
    )


def render_month(token: str) -> _Rendered:
    """독립 월 표기를 1월부터 12월까지만 읽는다."""

    match = expected_match(_MONTH_RE, token)
    month = int(match.group("month"))
    if not 1 <= month <= 12:
        return ambiguous(token, "ambiguous_numeric", "유효하지 않은 월 표기입니다.")
    spoken = _spoken_month(month)
    return _Rendered(
        spoken + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.calendar_month.v1",
    )


def render_year_month(token: str) -> _Rendered:
    """연도와 선택적 월을 한 구조로 검증해 부분 변환을 막는다."""

    match = expected_match(_YEAR_MONTH_RE, token)
    year = read_sino(match.group("year"))
    month_surface = match.group("month")
    if month_surface is None:
        spoken = f"{year} 년"
    else:
        month = int(month_surface)
        if not 1 <= month <= 12:
            return ambiguous(token, "ambiguous_numeric", "유효하지 않은 연월 표기입니다.")
        month_text = _spoken_month(month)
        spoken = f"{year} 년 {month_text}"
    return _Rendered(
        spoken + (match.group("suffix") or ""),
        Handler.NUMERIC,
        "normalizer.calendar_year_month.v1",
    )


def render_exponent(token: str) -> _Rendered:
    match = expected_match(_EXPONENT_RE, token)
    try:
        base = read_sino(match.group("base"))
        exponent = read_sino(match.group("exponent"))
    except NumberFormatError:
        return ambiguous(token, "ambiguous_numeric", "지수 표기를 손실 없이 읽을 수 없습니다.")
    return _Rendered(f"{base}의 {exponent}승", Handler.NUMERIC, "normalizer.math_exponent.v1")

SIMPLE_RENDERERS = {
    "fraction": render_fraction,
    "percentage": render_percentage,
    "month_day": render_month_day,
    "year_month": render_year_month,
    "month": render_month,
    "exponent": render_exponent,
}
