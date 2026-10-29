"""숫자를 보존하면서 숫자 모델의 영문 문맥을 운영 사전과 같은 읽기로 바꾼다."""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..english.context import is_standalone_latin_word, touches_identifier_structure
from ..scanner import overlaps, scan_protected
from .conventional_english import CONVENTIONAL_READINGS
from .output_policy import render_unknown_latin
from .units import _UNIT_READINGS

CONTEXT_POLICY_VERSION = "latin-context-v2"
_LATIN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_DIGITS = re.compile(r"[0-9]+")
_NUMERIC_LEFT = re.compile(r"(?<![A-Za-z0-9_])[0-9]+(?:[.,][0-9]+)?[ \t]*\Z")
@dataclass(frozen=True, slots=True)
class LatinRewrite:
    """영문만 바뀐 원문·출력 좌표와 선택한 규칙을 기록한다."""

    start: int
    end: int
    output_start: int
    output_end: int
    before: str
    after: str
    rule: str


@dataclass(frozen=True, slots=True)
class NumberModelContext:
    """숫자 판별 지점을 새 문맥으로 투영할 수 있는 전처리 결과다."""

    text: str
    rewrites: tuple[LatinRewrite, ...]

    def project_boundary(self, position: int) -> int:
        """영문 치환 내부의 원문 경계를 거부하고 양쪽 끝 경계만 정확히 투영한다."""

        source_length = len(self.text) - sum(len(c.after) - len(c.before) for c in self.rewrites)
        if not isinstance(position, int) or position < 0 or position > source_length:
            raise ValueError("문맥 경계가 원문 범위를 벗어납니다.")
        if any(c.start < position < c.end for c in self.rewrites):
            raise ValueError("문맥 경계가 영문 치환 내부에 있습니다.")
        return position + sum(len(c.after) - len(c.before) for c in self.rewrites if c.end <= position)

    def project_span(self, start: int, end: int) -> tuple[int, int]:
        """치환 구간과 겹치는 숫자 좌표는 묵인하지 않고 거부한다."""

        if start < 0 or end <= start:
            raise ValueError("숫자 좌표는 비어 있지 않은 범위여야 합니다.")
        if any(change.start < end and start < change.end for change in self.rewrites):
            raise ValueError("숫자 판별 구간이 영문 치환과 겹칩니다.")
        return self.project_boundary(start), self.project_boundary(end)


def prepare_number_model_context(source: str) -> NumberModelContext:
    """정답을 참조하지 않고 영문만 치환하며 숫자·부호·한글 문맥은 보존한다."""

    if not isinstance(source, str):
        raise TypeError("숫자 모델의 문맥은 문자열이어야 합니다.")
    if not _LATIN.search(source):
        return NumberModelContext(source, ())
    protected = scan_protected(source)
    pieces, changes = [], []
    cursor = output_cursor = 0
    for match in _LATIN.finditer(source):
        start, end, word = match.start(), match.end(), match.group()
        prefix = source[cursor:start]
        pieces.append(prefix)
        output_cursor += len(prefix)
        # 독립 숫자에 붙은 단위만 예외로 허용하며 식별자·복합 단위에는 적용하지 않는다.
        numeric = _NUMERIC_LEFT.search(source[:start])
        unit = (
            _UNIT_READINGS.get(word)
            if numeric is not None and not overlaps(protected, numeric.start(), end)
            and not touches_identifier_structure(source, numeric.start(), end)
            else None
        )
        standalone = is_standalone_latin_word(source, start, end, protected=protected)
        structural = not standalone and unit is None
        reading = CONVENTIONAL_READINGS.get(word.upper()) if not structural else None
        if unit is not None:
            after, rule = unit, "unit"
        elif reading is not None:
            after, rule = reading, "conventional"
        else:
            rendered = render_unknown_latin(word)
            if rendered.unresolved:
                raise ValueError("영문 문맥의 읽기를 확정할 수 없습니다.")
            after, rule = rendered.text, "structural_spelling" if structural else "spelling"
        pieces.append(after)
        changes.append(LatinRewrite(start, end, output_cursor, output_cursor + len(after), word, after, rule))
        output_cursor += len(after)
        cursor = end
    pieces.append(source[cursor:])
    result = "".join(pieces)
    if _DIGITS.findall(source) != _DIGITS.findall(result):
        raise ValueError("영문 전처리가 숫자의 값 또는 경계를 변경했습니다.")
    return NumberModelContext(result, tuple(changes))
