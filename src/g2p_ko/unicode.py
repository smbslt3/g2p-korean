"""NFC 정규화와 정규화 결과에서 원문으로 돌아가는 span 대응을 제공한다."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from .errors import InputValidationError
from .model import Handler, Rewrite, RewriteStage, SourceSpan


def is_numeric_character(character: str) -> bool:
    """모든 Unicode 숫자 문자를 숫자 passthrough 대상으로 판정한다."""

    return character.isnumeric()


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """NFC 문자열의 각 code point가 가리키는 원문 span을 담는다."""

    source: str
    text: str
    character_spans: tuple[SourceSpan, ...]
    rewrites: tuple[Rewrite, ...]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.character_spans):
            raise ValueError("정규화 문자열과 문자 span 수가 다릅니다.")

    def source_span(self, start: int, end: int) -> SourceSpan:
        """정규화 좌표 범위를 가장 작은 연속 원문 span으로 되돌린다."""

        if not (0 <= start < end <= len(self.text)):
            raise ValueError("비어 있거나 범위를 벗어난 정규화 span입니다.")
        # normalize_nfc가 원문 순서로 만든 단조 span이므로 양 끝만 보면 충분하다.
        raw_start = self.character_spans[start].start
        raw_end = self.character_spans[end - 1].end
        return SourceSpan.from_source(self.source, raw_start, raw_end)

    def snap_range(self, start: int, end: int) -> tuple[int, int]:
        """결합 단위의 중간을 자르지 않도록 정규화 범위를 넓힌다."""

        if not (0 <= start <= end <= len(self.text)):
            raise ValueError("범위를 벗어난 정규화 좌표입니다.")
        if start == end:
            return start, end
        first = self.character_spans[start]
        last = self.character_spans[end - 1]
        while start > 0 and self.character_spans[start - 1] == first:
            start -= 1
        while end < len(self.text) and self.character_spans[end] == last:
            end += 1
        return start, end


def _validate_input(source: str, max_length: int) -> bool:
    """입력을 검증하고 원자 단위 처리가 필요한 결합문자 여부를 반환한다."""

    if not isinstance(source, str):
        raise InputValidationError("입력은 문자열이어야 합니다.")
    if len(source) > max_length:
        raise InputValidationError(f"입력이 최대 길이 {max_length}를 초과했습니다.")
    if source.isascii():
        return False
    has_combining = False
    for character in source:
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise InputValidationError("짝이 맞지 않는 surrogate는 입력으로 허용하지 않습니다.")
        has_combining = has_combining or unicodedata.combining(character) != 0
    return has_combining


def normalize_nfc(source: str, *, max_length: int = 10_000) -> NormalizedText:
    """NFC 결과와 모든 결과 문자에 대응하는 원문 span을 만든다.

    일반 결합문자와 정준 조합은 하나의 원자 단위로 정규화한다.
    따라서 NFD 입력이 한 음절로 합쳐져도 원문 code point 위치는 유지된다.
    """

    has_combining = _validate_input(source, max_length)
    if not source:
        return NormalizedText(source, "", (), ())

    # 일반적인 NFC 입력은 문자별 normalize와 임시 cluster 할당을 생략한다.
    # 결합문자가 있으면 정규화 결과가 같아도 기존의 원자 단위 span 묶음을 유지한다.
    if not has_combining and unicodedata.is_normalized("NFC", source):
        source_length = len(source)
        character_spans = tuple(
            SourceSpan(index, index + 1, character, source_length)
            for index, character in enumerate(source)
        )
        return NormalizedText(source, source, character_spans, ())

    chunks: list[str] = []
    spans: list[SourceSpan] = []
    rewrites: list[Rewrite] = []
    cluster: list[str] = []
    cluster_start = 0
    trailing_class = 0
    composed_tail = ""

    def flush(end: int) -> None:
        if not cluster:
            return
        raw = "".join(cluster)
        normalized = unicodedata.normalize("NFC", raw)
        source_span = SourceSpan.from_source(source, cluster_start, end)
        chunks.append(normalized)
        spans.extend([source_span] * len(normalized))
        if raw != normalized:
            rewrites.append(
                Rewrite(
                    (source_span,),
                    raw,
                    normalized,
                    Handler.KOREAN,
                    "unicode.nfc",
                    RewriteStage.UNICODE,
                )
            )

    for index, character in enumerate(source):
        decomposed = unicodedata.normalize("NFD", character)
        leading_class = unicodedata.combining(decomposed[0])
        next_trailing_class = unicodedata.combining(decomposed[-1])
        character_nfc = unicodedata.normalize("NFC", character)

        joins_cluster = bool(leading_class)
        joined_tail = ""
        if cluster and not joins_cluster and not trailing_class:
            # 등급 0 사이에서도 한글 자모와 일부 문자권은 정준 조합한다.
            # 마지막 조합 문자만 확인해 클러스터 전체의 반복 정규화를 피한다.
            joined_tail = unicodedata.normalize("NFC", composed_tail + character_nfc)
            joins_cluster = joined_tail != composed_tail + character_nfc
        if cluster and not joins_cluster:
            flush(index)
            cluster = []
        if not cluster:
            cluster_start = index
        cluster.append(character)
        trailing_class = next_trailing_class
        if not trailing_class:
            composed_tail = joined_tail[-1] if joined_tail and joins_cluster else character_nfc[-1]
        else:
            composed_tail = ""
    flush(len(source))
    return NormalizedText(source, "".join(chunks), tuple(spans), tuple(rewrites))


def normalize_nfc_text(source: str, *, max_length: int = 10_000) -> str:
    """원문 좌표가 필요 없는 문자열 전용 경로에서 NFC 텍스트만 반환한다."""

    _validate_input(source, max_length)
    if source.isascii() or unicodedata.is_normalized("NFC", source):
        return source
    return unicodedata.normalize("NFC", source)
