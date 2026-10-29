"""관용 영문 읽기를 적용할 독립 단어와 구조 토큰의 경계를 구분한다."""

from __future__ import annotations

import re
import unicodedata

from ..scanner import ProtectedRange, overlaps, scan_protected

_LATIN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_JOINERS = frozenset("@.#?=&%$‑‐‒–—-/\\^+:'’·×")
_IDENTIFIER_PREFIXES = frozenset("@#$.")
_UNIT_MODIFIERS = frozenset("µμ°")
_COMPOUND_OPERATORS = frozenset("/\\^·×")


def _is_joiner(value: str) -> bool:
    """두 점 리더·말줄임표처럼 NFKC에서 여러 구분자로 펼쳐지는 표기도 확인한다."""

    return bool(value) and all(character in _JOINERS for character in value)


def _is_identifier_component(character: str) -> bool:
    """영문 식별자와 숫자 식별자를 잇는 문자를 판별한다."""

    character = unicodedata.normalize("NFKC", character)
    return bool(character) and (
        character == "_" or character.isascii() and character.isalnum()
        or character.isnumeric() or any(
            item.isnumeric() or unicodedata.category(item).startswith("M")
            or unicodedata.category(item) == "Cf"
            or item.isalpha() and "HANGUL" not in unicodedata.name(item, "")
            for item in character
        )
    )


def touches_identifier_structure(source: str, start: int, end: int) -> bool:
    """구분자로 연결된 영문·숫자와 아직 지원하지 않는 복합 단위를 보수적으로 찾는다."""

    def character_at(index: int) -> str:
        return unicodedata.normalize("NFKC", source[index]) if 0 <= index < len(source) else ""

    left, right = character_at(start - 1), character_at(end)
    if left in _IDENTIFIER_PREFIXES or right == "@":
        return True
    if any(_is_identifier_component(char) or char in _UNIT_MODIFIERS for char in (left, right)):
        return True
    if _is_joiner(left):
        before = start - 1
        while before >= 0 and _is_joiner(character_at(before)):
            before -= 1
        if before >= 0 and _is_identifier_component(character_at(before)):
            return True
    if _is_joiner(right):
        after = end
        while after < len(source) and _is_joiner(character_at(after)):
            after += 1
        if after < len(source) and _is_identifier_component(character_at(after)):
            return True
    # 복합 단위 기호 양쪽의 공백 때문에 단위 일부만 따로 확정되지 않도록 한다.
    before = start - 1
    while before >= 0 and character_at(before) in " \t":
        before -= 1
    after = end
    while after < len(source) and character_at(after) in " \t":
        after += 1
    def is_compound_operator(index: int) -> bool:
        if not 0 <= index < len(source) or character_at(index) not in _COMPOUND_OPERATORS:
            return False
        if character_at(index) == "\\":
            following = index
            while following < len(source) and character_at(following) == "\\":
                following += 1
            # 코드 구분자를 이스케이프하는 역슬래시는 단어 사이 연산자가 아니다.
            if character_at(following) == "`":
                return False
        return True

    return is_compound_operator(before) or is_compound_operator(after)


def is_standalone_latin_word(
    source: str,
    start: int,
    end: int,
    *,
    protected: tuple[ProtectedRange, ...] | list[ProtectedRange] | None = None,
) -> bool:
    """보호 구조·부분 단어·연결 식별자를 제외한 독립 영문 구간만 허용한다."""

    if start < 0 or end <= start or end > len(source):
        return False
    word = unicodedata.normalize("NFKC", source[start:end])
    if _LATIN.fullmatch(word) is None:
        return False
    ranges = scan_protected(source) if protected is None else protected
    return not overlaps(ranges, start, end) and not touches_identifier_structure(source, start, end)
