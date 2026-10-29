# SPDX-License-Identifier: MIT
"""명세에 따라 형태소 메타데이터를 고정하고 표면 토큰에 배정한다."""

from bisect import bisect_right


def _fields(value, size, label):
    """문자열을 제외한 반복 가능한 레코드의 필드 수를 확인한다."""
    if isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label}: 잘못된 레코드 형식")
    try:
        fields = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{label}: 반복 가능한 레코드가 필요함") from exc
    if len(fields) != size:
        raise ValueError(f"{label}: 필드 수가 올바르지 않음")
    return fields


def _items(value, label):
    """최상위 입력이 문자열이 아닌 반복 가능한 값인지 확인한다."""
    if isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label}: 문자열은 허용되지 않음")
    try:
        return iter(value)
    except TypeError as exc:
        raise ValueError(f"{label}: 반복 가능한 값이 필요함") from exc


def _text(value, label):
    """값을 변환하지 않고 비어 있지 않은 문자열인지 확인한다."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: 비어 있지 않은 문자열이 필요함")
    return value


def _offset(value, label):
    """불리언을 제외한 음이 아닌 정수 좌표인지 확인한다."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label}: 음이 아닌 정수가 필요함")
    return value


def freeze_morphemes(value) -> tuple[tuple[str, str], ...]:
    """원래 순서와 중복을 유지하며 형태소 쌍을 불변 튜플로 만든다."""
    result = []
    for item in _items(value, "형태소"):
        form, tag = _fields(item, 2, "형태소")
        result.append((_text(form, "형태"), _text(tag, "품사")))
    return tuple(result)


def align_morphemes(raw_parts, token_spans) -> tuple[tuple[tuple[str, str], ...], ...]:
    """이미 정렬된 표면 구간에 정규 형태소를 배정하고 방출 순서를 보존한다."""
    spans = []
    starts = []
    previous_end = 0
    for item in _items(token_spans, "토큰 구간"):
        start, end = _fields(item, 2, "토큰 구간")
        _offset(start, "토큰 시작")
        _offset(end, "토큰 끝")
        if end <= start or (spans and start < previous_end):
            raise ValueError("토큰 구간은 양의 길이이며 순서대로 겹치지 않아야 함")
        spans.append((start, end))
        starts.append(start)
        previous_end = end

    buckets = [[] for _ in spans]
    for item in _items(raw_parts, "원시 형태소"):
        form, tag, start, length = _fields(item, 4, "원시 형태소")
        if form is not None:
            _text(form, "형태")
        _text(tag, "품사")
        _offset(start, "형태소 시작")
        _offset(length, "형태소 길이")

        # 이진 탐색으로 시작 좌표를 포함할 수 있는 마지막 구간을 찾는다.
        index = bisect_right(starts, start) - 1
        assigned = index >= 0 and start < spans[index][1]
        if length:
            end = start + length
            if assigned:
                if end > spans[index][1]:
                    raise ValueError("형태소가 토큰 구간 밖으로 걸쳐 있음")
            elif index + 1 < len(spans) and end > spans[index + 1][0]:
                raise ValueError("형태소가 토큰 구간의 일부에만 겹침")

        if assigned and form is not None:
            buckets[index].append((form, tag))

    return tuple(tuple(bucket) for bucket in buckets)
