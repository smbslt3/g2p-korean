# SPDX-License-Identifier: MIT
"""기존 명사 뒤 계사 이형태의 제한된 표면 일치 근거를 공유한다."""

import unicodedata
from .word_grammar import ENDINGS, parse_parts

_POSITIVE_COPULA_ENDING_TAGS = ENDINGS
_COMPATIBILITY_TO_TRAILING_JAMO = {"ㄴ": "ᆫ"}


def _is_particle_only_tag(tag: str) -> bool:
    """결합 태그가 조사 성분만 포함하는지 확인한다."""

    parts = tuple(part.strip() for part in tag.split("+"))
    return bool(parts) and all(part.startswith("J") for part in parts)


def matches_positive_copula_tail(
    source_tail: str, morphemes: tuple[tuple[str, str], ...], *,
    vowel_final_nominal: bool = False,
) -> bool:
    """계사 형태소열이 원문 표면형 또는 허용된 계사 이형태와 맞는지 확인한다."""

    if (
        len(morphemes) < 2
        or morphemes[0] != ("이", "VCP")
    ):
        return False

    ending_parts: list[tuple[str, str]] = []
    particle_parts: list[tuple[str, str]] = []
    saw_particle = False
    for part in morphemes[1:]:
        _, tag = part
        if tag in _POSITIVE_COPULA_ENDING_TAGS and not saw_particle:
            ending_parts.append(part)
        elif _is_particle_only_tag(tag):
            saw_particle = True
            particle_parts.append(part)
        else:
            return False
    if not ending_parts:
        return False

    def surface(parts: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> str:
        return "".join(
            _COMPATIBILITY_TO_TRAILING_JAMO.get(character, character)
            for form, _ in parts
            for character in form
        )

    grammatical_surface = surface(ending_parts)
    particle_surface = surface(particle_parts)
    candidates = {surface((morphemes[0], *ending_parts))}
    if vowel_final_nominal:
        # 모음으로 끝나는 명사 뒤에서는 계사 이가 생략될 수 있다.
        candidates.add(grammatical_surface)
        if ending_parts[0] == ("에요", "EF"):
            candidates.add("예요" + surface(ending_parts[1:]))
        if ending_parts[0] == ("었", "EP"):
            candidates.add("였" + surface(ending_parts[1:]))

    normalized_source = unicodedata.normalize("NFC", source_tail)
    return any(
        normalized_source == unicodedata.normalize("NFC", candidate + particle_surface)
        for candidate in candidates
    )


def is_vowel_final_nominal_source(form: str) -> bool:
    """현재 발음이 아닌 선언된 명사 원형의 마지막 음절에서 받침을 확인한다."""

    normalized = unicodedata.normalize("NFC", form)
    if not normalized:
        return False
    final = ord(normalized[-1])
    return 0xAC00 <= final <= 0xD7A3 and (final - 0xAC00) % 28 == 0


def licensed_positive_copula_tail(source_tail, morphemes, *, vowel_final_nominal=False):
    """계사 표면 일치와 명사 숙주 뒤 유형별 문법 허가를 함께 요구한다."""
    return (parse_parts(morphemes, initial_host="nominal").lexical_status == "eligible"
            and matches_positive_copula_tail(source_tail, morphemes,
                                            vowel_final_nominal=vowel_final_nominal))
