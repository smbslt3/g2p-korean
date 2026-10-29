"""영문 관용 읽기에서 제외할 주소와 코드의 원문 범위를 찾는다."""

from __future__ import annotations

import re
import unicodedata

from ..scanner import ProtectedRange, scan_protected

_SCHEME_URL = re.compile(r'''(?<![\w.+-])[A-Za-z][A-Za-z0-9+.-]*://(?=[^\s<>"{}])''')
_LABEL = r"[^\W_](?:(?:[^\W_]|-){0,61}[^\W_])?"
_TLD = r"(?:xn--[A-Za-z0-9-]+|[^\W\d_]{2,63})"
_BARE_URL = re.compile(
    rf"(?<![\w.@-])(?:{_LABEL}\.)+{_TLD}"
    r"(?![\w-])(?::[0-9]+)?[/?#]?",
    re.IGNORECASE,
)
_EMAIL_ATOM = r"[\w.!#$%&'*+/=?^`{|}~-]"
_EMAIL_QUOTED = r'''"(?:[^"\\\r\n]|\\[^\r\n])*"'''
_EMAIL_DOMAIN = rf"(?:(?:{_LABEL}[.。])+{_TLD}|\[[^\]\s<>]+\])"
# 로컬 부분 한가운데서 같은 긴 후보를 반복 탐색하지 않는다.
_EMAIL = re.compile(rf"(?:(?<!{_EMAIL_ATOM}){_EMAIL_ATOM}+|(?<![\w\\]){_EMAIL_QUOTED})@{_EMAIL_DOMAIN}(?![\w-])")
_IDNA_URL = re.compile(
    rf"(?<![\w.@-])(?:{_LABEL}[.。])+{_TLD}(?![\w-])"
    r"(?::[0-9]+)?[/?#]", re.IGNORECASE,
)
_QUOTED_PATH = re.compile(
    r'''(?P<quote>["'])(?:[A-Za-z]:[\\/]|\\\\|\.{1,2}[\\/]|~/|/)[^\r\n]*?(?P=quote)'''
)
_ENVIRONMENT_VARIABLE = re.compile(r"%[\w()]+%|\$\{[^{}\r\n]+\}")
_LOCAL_URL = re.compile(
    r"(?<![\w.@-])(?:localhost|(?:[0-9]{1,3}\.){3}[0-9]{1,3}|\[[0-9A-Fa-f:.]+(?:%[\w.~-]+)?\])"
    r"(?::[0-9]+)?[/?#]",
    re.IGNORECASE,
)
_URL_TAIL = re.compile(r'''[^\s<>"{}]*''')
_BARE_URL_TAIL = re.compile(r'''[^\s<>"\[\]{}]*''')
_QUOTE_PREFIX = re.compile(r" {0,3}>[ \t]?")
_LIST_BEFORE_QUOTE = re.compile(r"[ \t]*(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)+(?=>)")
_FENCE = re.compile(r"([ \t]*)(?:(?:[-+*]|[0-9]{1,9}[.)])[ \t]+)*(`{3,}|~{3,})([^\r\n]*)")


def _container_body(line: str) -> tuple[str, int]:
    """목록 안 인용과 인용 안 목록이 교차하는 접두부를 벗긴다."""
    depth = 0
    while True:
        if (quote := _QUOTE_PREFIX.match(line)) is not None:
            line = line[quote.end():]
            depth += 1
        elif (listing := _LIST_BEFORE_QUOTE.match(line)) is not None:
            line = line[listing.end():]
        else:
            return line, depth


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    """닫히지 않은 코드 울타리도 입력 끝까지 보호한다."""

    ranges: list[tuple[int, int]] = []
    opening: tuple[int, str, int, int] | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        body, quote_depth = _container_body(line)
        indentation = len(body.expandtabs(4)) - len(body.lstrip(" \t").expandtabs(4))
        # 인용·목록 블록이 끝나면 닫는 울타리가 없어도 뒤의 일반 문장을 해제한다.
        if opening is not None and (
            quote_depth < opening[2] or body.strip() and indentation < opening[3]
        ):
            ranges.append((opening[0], offset))
            opening = None
        match = _FENCE.match(body)
        if match is not None:
            leading_space, fence, suffix = match.groups()
            if opening is None:
                # 역따옴표 울타리의 정보 문자열에는 역따옴표를 허용하지 않는다.
                if fence[0] != "`" or "`" not in suffix:
                    has_list_marker = match.start(2) > len(leading_space)
                    container_indent = (
                        len(body[:match.start(2)].expandtabs(4)) if has_list_marker
                        else indentation if indentation >= 4 else 0
                    )
                    opening = (offset, fence, quote_depth, container_indent)
            elif (
                quote_depth == opening[2] and fence[0] == opening[1][0]
                and len(fence) >= len(opening[1]) and not suffix.strip()
                and match.start(2) == len(leading_space)
                and indentation <= opening[3] + 3
            ):
                ranges.append((opening[0], offset + len(line)))
                opening = None
        offset += len(line)
    if opening is not None:
        ranges.append((opening[0], len(text)))
    return ranges


def _inline_ranges(text: str, fences: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """같은 길이의 역따옴표를 짝지으며 코드 내부의 역슬래시는 문자로 취급한다."""
    barriers = list(fences)
    offset = 0
    for line in text.splitlines(keepends=True):
        body, _ = _container_body(line)
        if not body.strip():
            barriers.append((offset, offset + len(line)))
        offset += len(line)
    barriers.sort()
    ranges: list[tuple[int, int]] = []
    start = 0
    for barrier_start, barrier_end in [*barriers, (len(text), len(text))]:
        if barrier_start > start:
            runs = list(re.finditer(r"`+", text[start:barrier_start]))
            following: dict[int, int] = {}
            next_run: dict[int, int] = {}
            next_escaped: dict[int, int] = {}
            for index in range(len(runs) - 1, -1, -1):
                length = len(runs[index].group())
                if length in following:
                    next_run[index] = following[length]
                if length > 1 and length - 1 in following:
                    next_escaped[index] = following[length - 1]
                following[length] = index
            index = 0
            while index < len(runs):
                position = start + runs[index].start()
                previous = position - 1
                while previous >= start and text[previous] == "\\":
                    previous -= 1
                escaped = (position - previous - 1) % 2 == 1
                closing = (next_escaped if escaped else next_run).get(index)
                if closing is not None:
                    # 역슬래시는 첫 역따옴표 하나만 이스케이프한다.
                    position += int(escaped)
                    ranges.append((position, start + runs[closing].end()))
                    index = closing + 1
                else:
                    index += 1
        start = max(start, barrier_end)
    return ranges


def _enclosing_ends(text: str, literals: list[tuple[int, int]]) -> list[int]:
    """구조를 감싼 괄호의 끝을 선형으로 색인해 뒤의 산문을 보호 범위에서 뺀다."""
    opening: list[tuple[str, int]] = []
    pairs: dict[int, int] = {}
    expected = {")": "(", "]": "[", "}": "{"}
    ignored = bytearray(len(text))
    for start, end in literals:
        ignored[start:end] = b"\1" * (end - start)
    for index, char in enumerate(text):
        if ignored[index]:
            continue
        if char in "([{":
            opening.append((char, index))
        elif char in expected and opening and opening[-1][0] == expected[char]:
            _, start = opening.pop()
            pairs[start] = index
    limits: list[int] = []
    ends: list[int] = []
    for index in range(len(text)):
        limits.append(ends[-1] if ends else len(text))
        if ends and ends[-1] == index:
            ends.pop()
        if index in pairs:
            ends.append(pairs[index])
    return limits


def _url_ranges(text: str, limits: list[int]) -> list[tuple[int, int]]:
    """주소 시작은 계속 탐색하고, 꼬리는 해당 괄호·코드 경계 안에서만 펼친다."""
    ranges: list[tuple[int, int]] = []
    for pattern, tail in (
        (_SCHEME_URL, _URL_TAIL), (_BARE_URL, _BARE_URL_TAIL),
        (_IDNA_URL, _BARE_URL_TAIL), (_LOCAL_URL, _URL_TAIL),
    ):
        covered_until = 0
        for match in pattern.finditer(text):
            start, end = match.span()
            if start < covered_until or end > limits[start]:
                continue
            if text[end - 1] in "/?#":
                remainder = tail.match(text, end, limits[start])
                assert remainder is not None
                end = remainder.end()
            ranges.append((start, end))
            # 이미 보호한 주소 안의 접두부마다 긴 꼬리를 다시 훑지 않는다.
            covered_until = end
    return ranges


def scan_english_structures(text: str) -> tuple[ProtectedRange, ...]:
    """호환 표기를 탐지용으로만 펼치고 원래 좌표로 주소·코드 범위를 반환한다.

    이 범위는 관용 사전 적용만 제한한다. 내부 영문 철자화와 숫자·미지원 문자
    진단은 그대로 수행하므로 기존 노멀라이저의 원문 보존 정책과 구별한다.
    """

    pieces: list[str] = []
    origins: list[int] = []
    for index, character in enumerate(text):
        piece = unicodedata.normalize("NFKC", character)
        pieces.append(piece)
        origins.extend([index] * len(piece))
    shadow = "".join(pieces)
    ranges: list[tuple[int, int]] = []
    for item in scan_protected(shadow):
        if item.kind in {"inline_code", "url"}:
            continue
        # 기존 경로 스캐너가 닫는 따옴표 뒤 산문까지 삼키지 않도록 제한한다.
        quote = shadow.find('"', item.start, item.end)
        end = quote if quote >= 0 else item.end
        if end > item.start:
            ranges.append((item.start, end))
    ranges.extend(match.span() for match in _EMAIL.finditer(shadow))
    quoted_paths = [match.span() for match in _QUOTED_PATH.finditer(shadow)]
    ranges.extend(quoted_paths)
    ranges.extend(match.span() for match in _ENVIRONMENT_VARIABLE.finditer(shadow))
    quoted_locals = [match.span() for match in re.finditer(r"(?<!\\)" + _EMAIL_QUOTED, shadow)]
    fences = _fenced_ranges(shadow)
    inline = _inline_ranges(shadow, fences)
    enclosing_ends = _enclosing_ends(shadow, quoted_paths + quoted_locals + fences + inline)
    # 코드 안에서 시작한 주소가 닫는 구분자 뒤의 일반 산문을 삼키지 않게 한다.
    for start, end in [*fences, *inline]:
        for index in range(start, end):
            enclosing_ends[index] = min(enclosing_ends[index], end)
    ranges.extend(_url_ranges(shadow, enclosing_ends))
    clipped: list[tuple[int, int]] = []
    for start, end in ranges:
        end = min(end, enclosing_ends[start])
        # 닫는 괄호 자체에서 시작한 이메일 후보는 빈 범위가 될 수 있다.
        if end > start:
            clipped.append((start, end))
    ranges = clipped
    ranges.extend(fences)
    ranges.extend(inline)
    merged: list[ProtectedRange] = []
    for start, end in sorted(ranges):
        source_start, source_end = origins[start], origins[end - 1] + 1
        if merged and source_start <= merged[-1].end:
            previous = merged.pop()
            source_start = previous.start
            source_end = max(previous.end, source_end)
        merged.append(ProtectedRange(source_start, source_end, "english_structure"))
    return tuple(merged)
