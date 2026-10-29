# SPDX-License-Identifier: MIT
"""정확한 어휘 소유 범위 안의 한자어 성분만 선언한다."""

from dataclasses import dataclass

from .lexicon import SINO_ORIGINS, SinoAttachment


@dataclass(frozen=True)
class OwnedSinoStructure:
    """전체 품사, 분리 성분의 품사 및 한자 어원을 보존한다."""

    owner_pos: frozenset[str]
    parts: tuple[tuple[str, frozenset[str], str | None], ...]

    @property
    def spelling(self) -> str:
        return "".join(form for form, _, _ in self.parts)


# 원자 사실의 實地+고유어 로를 옮긴다. 완성 발음은 저장하지 않는다.
OWNED_SINO_STRUCTURES = (
    OwnedSinoStructure(
        frozenset({"MAG"}),
        (("실지", frozenset({"NNG"}), "實地"),
         ("로", frozenset({"JKB", "MAG"}), None)),
    ),
)


# 的의 품사·어원만 선언하며 완성형 발음이나 활용형 목록은 두지 않는다.
SINO_DERIVATIONAL_COMPONENTS = (SinoAttachment("적", "XSN", "的"),)


def _derivational_structures():
    """확인한 보통명사 기반과 명시한 한자 파생 성분을 합성한다."""
    bases = {
        form: next(iter(sorted(feature.hanja_variants)))
        for form, feature in SINO_ORIGINS.items() if "NNG" in feature.pos
    }
    # 物質은 물질적의 어원으로만 확인했다. 중의적인 단독 물질에는 전파하지 않는다.
    bases["물질"] = "物質"
    for form, origin in bases.items():
        for component in SINO_DERIVATIONAL_COMPONENTS:
            yield OwnedSinoStructure(
                frozenset({"NNG"}),
                ((form, frozenset({"NNG"}), origin),
                 (component.form, frozenset({component.tag}), component.hanja)),
            )


def owned_sino_spans(text, annotation, *, nominal_tail_validator=None):
    """진실한 전체·분리 분석과 검증한 조사 꼬리에서만 어근 좌표를 낸다."""
    for structure in (*OWNED_SINO_STRUCTURES, *_derivational_structures()):
        spelling = structure.spelling
        start = text.find(spelling)
        while start >= 0:
            end = start + len(spelling)
            if _owns(text, annotation, start, end, structure, nominal_tail_validator):
                cursor = start
                sino_start = None
                for form, _, origin in structure.parts:
                    if origin is not None and sino_start is None:
                        sino_start = cursor
                    if origin is None and sino_start is not None:
                        yield sino_start, cursor, start, end
                        sino_start = None
                    cursor += len(form)
                if sino_start is not None:
                    yield sino_start, cursor, start, end
            start = text.find(spelling, start + 1)


def _truthful(token, text):
    """표면형·좌표·형태소열이 모두 맞는 단일 태그 token만 받는다."""
    return (
        token is not None
        and text[token.normalized_start:token.normalized_end] == token.form
        and (not token.morphemes or token.morphemes == ((token.form, token.tag),))
    )


def _owns(text, annotation, start, end, structure, nominal_tail_validator=None):
    """다른 단어의 부분 문자열이나 지원하지 않는 분석을 거부한다."""
    if start and text[start - 1].isalnum():
        return False
    first = annotation.starting_at(start)
    if first is None:
        return False
    if first.normalized_end == end and first.tag in structure.owner_pos:
        if not _truthful(first, text):
            return False
    else:
        cursor = start
        for form, tags, _ in structure.parts:
            token = annotation.starting_at(cursor)
            if (
                not _truthful(token, text) or token.tag not in tags
                or token.form != form or token.normalized_end != cursor + len(form)
            ):
                return False
            cursor = token.normalized_end
        if cursor != end:
            return False
    cursor = end
    following = annotation.starting_at(cursor)
    if (
        "NNG" in structure.owner_pos and nominal_tail_validator is not None
        and following is not None and following.tag.split("+")[0] == "VCP"
    ):
        # 기존 일반 명사 계사 검증기가 형태소 이+어미와 실제 표면형을 대조한다.
        return nominal_tail_validator(annotation, end, annotation.ending_at(end), structure.spelling)
    while cursor < len(text) and text[cursor].isalnum():
        token = annotation.starting_at(cursor)
        if token is None or token.normalized_end <= cursor:
            return False
        tags = tuple(token.tag.split("+"))
        parts = token.morphemes or ((token.form, token.tag),)
        if (
            not tags or any(not tag.startswith("J") for tag in tags)
            or tuple(tag for _, tag in parts) != tags
            or "".join(form for form, _ in parts) != token.form
            or text[cursor:token.normalized_end] != token.form
        ):
            return False
        cursor = token.normalized_end
    return True
