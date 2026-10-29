"""ASCII 영어 후보를 글자 이름으로 결정적으로 변환한다."""

from __future__ import annotations

import unicodedata

_LETTER_NAMES = {
    "a": "에이",
    "b": "비",
    "c": "씨",
    "d": "디",
    "e": "이",
    "f": "에프",
    "g": "지",
    "h": "에이치",
    "i": "아이",
    "j": "제이",
    "k": "케이",
    "l": "엘",
    "m": "엠",
    "n": "엔",
    "o": "오",
    "p": "피",
    "q": "큐",
    "r": "알",
    "s": "에스",
    "t": "티",
    "u": "유",
    "v": "브이",
    "w": "더블유",
    "x": "엑스",
    "y": "와이",
    "z": "지",
}
_APOSTROPHES = frozenset({"'", "\u2019"})


def ascii_letter_form(value: str) -> str | None:
    """전각·수학용 영문도 대응되는 알파벳 이름으로 읽는다. 숫자는 변환하지 않는다."""

    letters = unicodedata.normalize("NFKC", value)
    return letters if letters.isascii() and letters.isalpha() else None


def spell_ascii_letters(value: str) -> str:
    """검증된 ASCII 알파벳을 한국어 글자 이름으로 읽는다."""

    return "".join(_LETTER_NAMES[character.lower()] for character in value)


def resolve_english(value: str) -> str | None:
    """ASCII 알파벳과 아포스트로피를 소문자 기준 글자 이름으로 읽는다."""

    lowered = unicodedata.normalize("NFKC", value).lower()
    if not lowered:
        return None
    names: list[str] = []
    for character in lowered:
        if character in _APOSTROPHES:
            continue
        if not character.isascii() or not character.isalpha():
            return None
        names.append(_LETTER_NAMES[character])
    return "".join(names)
