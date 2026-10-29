"""장식의 원문 좌표 투영과 의미 변환 뒤 엄격한 TTS 출력 계약을 제공한다."""

from __future__ import annotations

import re

from ..english.classify import spell_ascii_letters
from ..model import Diagnostic, Handler, Rewrite, RewriteStage, Severity, SourceSpan
from ..scanner import ProtectedRange
from ..unicode import NormalizedText
from .grammar import _KOREAN_SUFFIXES
from .numbers import NumberFormatError, read_digitwise, read_sino
from .policy import _Rendered, ambiguous, is_permitted_whitespace

OUTPUT_POLICIES = frozenset({'preserve', 'tts'})
_PUNCTUATION = {
    '，': ',', '。': '.', '．': '.', '！': '!', '？': '?', '…': '...',
    ':': ',', ';': ',', '：': ',', '；': ',',
    **{character: ' ' for character in '\"\'“”‘’「」『』()[]{}'},
}
_STRUCTURAL_NAMES = {
    '.': '점', ':': '콜론', '/': '슬래시', '\\': '백슬래시', '@': '골뱅이',
    '-': '하이픈', '‑': '하이픈', '_': '밑줄', '+': '플러스', '%': '퍼센트',
    '?': '물음표', '=': '등호', '&': '앰퍼샌드', '#': '해시', '~': '물결표',
    '!': '느낌표', '$': '달러 기호', '*': '별표', ',': '쉼표', ';': '세미콜론',
    '(': '여는 괄호', ')': '닫는 괄호', '[': '여는 대괄호', ']': '닫는 대괄호',
    '{': '여는 중괄호', '}': '닫는 중괄호', '<': '작다 기호', '>': '크다 기호',
    '|': '세로줄', '^': '캐럿', "'": '작은따옴표', '’': '작은따옴표',
    '"': '큰따옴표', '`': '백틱',
}
_EMOJI_BASE = '[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]'
_EMOJI = re.compile(_EMOJI_BASE + '(?:[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF]|\u200D' + _EMOJI_BASE + ')*')
_MARKUP = re.compile(
    r'(?<![\w*])(?P<mark>\*\*|__|~~|\*)(?=\S)'
    r'(?P<body>(?:(?!(?P=mark)).)+?)(?<=\S)(?P=mark)'
    r'(?![A-Za-z0-9_*]|[.,][0-9])'
)
_HTML_TAG = re.compile(r'</?(?:b|i|em|strong|p|br|span|u|s)>', re.IGNORECASE)
_MEANINGFUL_EMOJI_SYMBOLS = frozenset('✖✕➕➖➗')
_LIST_MARKER = re.compile(r'(?m)^[ \t]*[-*+•●][ \t]+(?=[가-힣A-Za-z])')
_HEADING_MARKER = re.compile(r'(?m)^[ \t]*\#{1,6}[ \t]+(?=\S)')
_HANGUL_TAG_MARKER = re.compile(r'(?<![가-힣A-Za-z0-9_#])#(?=[가-힣]+(?:$|[\s,.!?]))')
_NUMERIC_BOUNDARY_SIGNS = frozenset('.,/+-−~～〜')
_SUFFIX = '(?:' + '|'.join(re.escape(s) for s in sorted(_KOREAN_SUFFIXES, key=lambda s: (-len(s), s))) + ')?'
_IDENTIFIER = re.compile(
    r'(?<![A-Za-z0-9가-힣])(?P<label>(?:인증|우편|주문|계좌|비밀|식별|시리얼|제품)[ \t]*번호)'
    r'(?P<label_suffix>는|은|이|가|을|를|에)?(?P<separator>[ \t]*[:：]?[ \t]*)'
    r'(?P<digits>[0-9]+)(?P<suffix>' + _SUFFIX + r')'
    r'(?![A-Za-z0-9가-힣]|[./+~%％\-][0-9])'
)
_ORDINAL = re.compile(
    r'(?<![A-Za-z0-9가-힣])제[ \t]*(?P<number>[0-9]+)[ \t]*'
    r'(?P<unit>조|항|절|장|편|권|과|부|막|호|차|회|기|대)(?P<suffix>' + _SUFFIX + r')'
    r'(?![A-Za-z0-9가-힣]|[./+~%％\-][0-9])'
)


def is_tts_text(text: str) -> bool:
    """성공한 TTS 문자열의 허용 문자는 완성형 한글·공백·네 문장부호다."""

    return all('가' <= character <= '힣' or character in ' ,.!?' for character in text)


def punctuation_output(character: str) -> str | None:
    """의미 기호를 포괄적으로 삭제하지 않고 확정된 문장부호만 바꾼다."""

    return _PUNCTUATION.get(character)


def decoration_ranges(text: str, protected: tuple[ProtectedRange, ...]) -> tuple[ProtectedRange, ...]:
    """의미 토큰을 분절하지 않고 제거할 명시적 장식·마크업 구간을 찾는다."""

    candidates: list[tuple[int, int, str]] = []

    def inline_pair(opening: tuple[int, int], closing: tuple[int, int]) -> None:
        # 보호 구조 안에 어느 한쪽이라도 있으면 마크업 쌍을 따로 지우지 않는다.
        if any(item.start < end and start < item.end
               for start, end in (opening, closing) for item in protected):
            return
        candidates.extend((*part, 'tts_inline_markup') for part in (opening, closing))

    for match in _EMOJI.finditer(text):
        if any(c in _MEANINGFUL_EMOJI_SYMBOLS or c.isnumeric() for c in match.group()):
            continue
        candidates.append((*match.span(), 'tts_decoration'))
    for match in _MARKUP.finditer(text):
        inline_pair(match.span('mark'), (match.end() - len(match['mark']), match.end()))
    html_stack: list[tuple[str, tuple[int, int]]] = []
    for match in _HTML_TAG.finditer(text):
        closing = match.group().startswith('</')
        tag = match.group()[2 if closing else 1:-1].lower()
        if tag in {'p', 'br'}:
            candidates.append((*match.span(), 'tts_decoration'))
        elif not closing:
            html_stack.append((tag, match.span()))
        elif html_stack and html_stack[-1][0] == tag:
            _, opening = html_stack.pop()
            inline_pair(opening, match.span())
    candidates.extend((*match.span(), 'tts_decoration') for match in _LIST_MARKER.finditer(text))
    candidates.extend((*match.span(), 'tts_decoration') for match in _HEADING_MARKER.finditer(text))
    candidates.extend((*match.span(), 'tts_inline_markup') for match in _HANGUL_TAG_MARKER.finditer(text))
    for index, character in enumerate(text):
        if _PUNCTUATION.get(character) != ' ':
            continue
        before, after = text[index - 1:index], text[index + 1:index + 2]
        # 영문 안의 apostrophe는 장식 인용부호가 아니라 구조 읽기에 맡긴다.
        if character in {"'", '’'} and before.isascii() and before.isalpha() and after.isascii() and after.isalpha():
            continue
        candidates.append((index, index + 1, 'tts_decoration'))
    result: list[ProtectedRange] = []
    for start, end, kind in sorted(set(candidates)):
        if any(item.start < end and start < item.end for item in protected):
            continue
        if result and start < result[-1].end:
            continue
        result.append(ProtectedRange(start, end, kind))
    return tuple(result)


def prepare_tts_input(
    normalized: NormalizedText, protected: tuple[ProtectedRange, ...],
) -> tuple[NormalizedText, tuple[Diagnostic, ...]]:
    """숫자·단위를 함께 파싱하도록 장식을 먼저 처리하고 원문 좌표를 투영한다."""

    decorations = decoration_ranges(normalized.text, protected)
    if not decorations:
        return normalized, ()
    # 숫자·부호 사이의 장식은 숫자를 합치거나 나눠 읽을 수 있어 명시적으로 실패시킨다.
    occupied = {index for item in decorations for index in range(item.start, item.end)}
    safe: list[ProtectedRange] = []
    diagnostics: list[Diagnostic] = []
    for item in decorations:
        left, right = item.start - 1, item.end
        while left in occupied:
            left -= 1
        while right in occupied:
            right += 1
        before = normalized.text[left] if left >= 0 else ''
        after = normalized.text[right] if right < len(normalized.text) else ''
        following = normalized.text[right + 1] if right + 1 < len(normalized.text) else ''
        numeric_boundary = (
            before.isascii() and before.isdigit()
            and (after.isascii() and after.isdigit() or after in {'%', '％'}
                 or after in _NUMERIC_BOUNDARY_SIGNS and following.isascii() and following.isdigit())
            or before in _NUMERIC_BOUNDARY_SIGNS and after.isascii() and after.isdigit()
        )
        if numeric_boundary:
            diagnostics.append(Diagnostic('unsafe_numeric_decoration',
                '숫자·부호 사이의 장식을 제거하면 값 또는 읽기 단위가 달라질 수 있습니다.',
                Severity.WARNING, (normalized.source_span(item.start, item.end),),
                'normalizer.tts.numeric_decoration.v1', RewriteStage.LEXICAL))
        else:
            safe.append(item)
    parts: list[str] = []
    spans: list[SourceSpan] = []
    rewrites = list(normalized.rewrites)
    cursor = 0
    for item in safe:
        parts.append(normalized.text[cursor:item.start])
        spans.extend(normalized.character_spans[cursor:item.start])
        before = normalized.text[item.start:item.end]
        # 인라인 마크업은 원래 결합을 유지하고 나머지 장식은 경계를 남긴다.
        after = '' if item.kind == 'tts_inline_markup' else ' '
        source_span = normalized.source_span(item.start, item.end)
        parts.append(after)
        spans.extend([source_span] * len(after))
        rewrites.append(Rewrite((source_span,), before, after, Handler.PROTECTED,
                                'normalizer.tts.decoration.v1', RewriteStage.LEXICAL))
        cursor = item.end
    parts.append(normalized.text[cursor:])
    spans.extend(normalized.character_spans[cursor:])
    return NormalizedText(normalized.source, ''.join(parts), tuple(spans), tuple(rewrites)), tuple(diagnostics)


def tts_semantic_matches(text: str, start: int, end: int) -> list[tuple[int, int, str, str]]:
    """명시적 번호 문맥과 제+숫자+서수 단위만 추가로 인식한다."""

    return [(m.start(), m.end(), kind, m.group())
            for kind, pattern in (('tts_identifier', _IDENTIFIER), ('tts_ordinal', _ORDINAL))
            for m in pattern.finditer(text, start, end)]


def render_tts_semantic(token: str, kind: str) -> _Rendered:
    if kind == 'tts_identifier':
        match = _IDENTIFIER.fullmatch(token)
        assert match is not None
        separator = ', ' if ':' in match['separator'] or '：' in match['separator'] else ' '
        text = (match['label'] + (match['label_suffix'] or '') + separator
                + read_digitwise(match['digits']) + (match['suffix'] or ''))
        return _Rendered(text, Handler.NUMERIC, 'normalizer.tts.explicit_identifier.v1')
    match = _ORDINAL.fullmatch(token)
    assert match is not None
    number = match['number']
    if len(number) > 10 or (len(number) > 1 and number.startswith('0')):
        return ambiguous(token, 'ambiguous_numeric', '선행 0 또는 긴 서수의 용도를 확정할 수 없습니다.')
    try:
        text = '제 ' + read_sino(number) + ' ' + match['unit'] + (match['suffix'] or '')
    except NumberFormatError:
        return ambiguous(token, 'ambiguous_numeric', '서수의 읽기를 확정할 수 없습니다.')
    return _Rendered(text, Handler.NUMERIC, 'normalizer.tts.ordinal.v1')


def render_structure(token: str, kind: str) -> _Rendered:
    """주소·경로·코드를 글자와 숫자 및 구분기호의 한국어 이름으로 읽는다."""

    parts: list[str] = []
    for match in re.finditer(r'[A-Za-z]+|[0-9]+|[가-힣]+|.', token, re.DOTALL):
        value = match.group()
        if value.isascii() and value.isalpha():
            # 주소의 대문자는 경로·식별자에서 의미가 있으므로 표시를 보존한다.
            letters: list[str] = []
            for character in value:
                prefix = '대문자 ' if character.isupper() else ''
                letters.append(prefix + spell_ascii_letters(character))
            parts.append(' '.join(letters))
        elif value.isascii() and value.isdigit():
            parts.append(read_digitwise(value))
        elif all('가' <= c <= '힣' for c in value):
            parts.append(value)
        elif value in _STRUCTURAL_NAMES:
            parts.append(_STRUCTURAL_NAMES[value])
        elif is_permitted_whitespace(value):
            parts.append('공백')
        else:
            return ambiguous(token, 'unsupported_tts_structure', '구조 토큰 안의 문자·기호를 손실 없이 읽을 수 없습니다.')
    return _Rendered(' '.join(parts), Handler.PROTECTED, f'normalizer.tts.{kind}.v1')


def render_unknown_latin(token: str) -> _Rendered:
    """미등록 ASCII 영문은 발음을 추측하지 않고 글자 이름으로 읽는다."""

    parts = []
    for value in re.findall(r'[A-Za-z]+|.', token):
        if value.isascii() and value.isalpha():
            parts.append(spell_ascii_letters(value))
        elif value in _STRUCTURAL_NAMES:
            parts.append(_STRUCTURAL_NAMES[value])
        else:
            return ambiguous(token, 'unconverted_latin', '영문 토큰의 구분기호를 읽을 수 없습니다.')
    return _Rendered(' '.join(parts), Handler.ENGLISH, 'normalizer.tts.english_spelling.v1')


def finish_tts_output(
    source: str,
    text: str,
    spans: list[SourceSpan],
    rewrites: list[Rewrite],
    diagnostics: list[Diagnostic],
) -> tuple[str, bool]:
    """의미 변환 뒤 문장부호·공백을 정리하고 허용 문자를 검증한다."""

    output: list[str] = []
    output_spans: list[SourceSpan] = []

    def span(start: int, end: int) -> SourceSpan:
        return SourceSpan.from_source(source, spans[start].start, spans[end - 1].end)

    def changed(start: int, end: int, after: str, rule: str) -> None:
        before = text[start:end]
        if before != after:
            rewrites.append(Rewrite((span(start, end),), before, after, Handler.PROTECTED,
                                    rule, RewriteStage.VERBALIZATION))

    index = 0
    while index < len(text):
        character = text[index]
        replacement = ' ' if is_permitted_whitespace(character) else punctuation_output(character)
        if replacement is None:
            replacement = character
        changed(index, index + 1, replacement, 'normalizer.tts.punctuation.v1')
        output.extend(replacement)
        output_spans.extend([spans[index]] * len(replacement))
        index += 1
    expanded = ''.join(output)
    compact: list[str] = []
    compact_spans: list[SourceSpan] = []
    index = 0
    while index < len(expanded):
        if expanded[index] != ' ':
            compact.append(expanded[index])
            compact_spans.append(output_spans[index])
            index += 1
            continue
        end = index + 1
        while end < len(expanded) and expanded[end] == ' ':
            end += 1
        after = ' ' if compact and end < len(expanded) and expanded[end] not in ',.!?' else ''
        if expanded[index:end] != after:
            anchor = SourceSpan.from_source(source, output_spans[index].start, output_spans[end - 1].end)
            rewrites.append(Rewrite((anchor,), expanded[index:end], after, Handler.PROTECTED,
                                    'normalizer.tts.whitespace.v1', RewriteStage.VERBALIZATION))
        if after:
            compact.append(after)
            compact_spans.append(output_spans[index])
        index = end
    result = ''.join(compact)
    complete = True
    index = 0
    while index < len(result):
        if is_tts_text(result[index]):
            index += 1
            continue
        end = index + 1
        while end < len(result) and not is_tts_text(result[end]):
            end += 1
        complete = False
        anchor = SourceSpan.from_source(source, compact_spans[index].start, compact_spans[end - 1].end)
        diagnostics.append(Diagnostic('unsupported_tts_output', 'TTS 출력에 허용되지 않는 미해석 문자가 남았습니다.',
                                      Severity.WARNING, (anchor,), 'normalizer.tts.output_contract.v1', RewriteStage.VALIDATION))
        index = end
    return result, complete
