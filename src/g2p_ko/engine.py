"""고정된 한국어 TTS 파이프라인의 공개 진입점이다."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import partial

from .alignment import G2PAlignedResult, build_pronunciation_alignment
from .errors import InputValidationError
from .model import DiagnosticReport, G2PDiagnostics, G2PResult
from .pipeline import Pipeline
from .unicode import normalize_nfc
from .vowel_variants import G2PVowelVariantResult
from .vowel_length import G2PVowelLengthResult
from .reading_conditions import (
    G2PReadingConditionResult,
    ReadingBoundary,
    prepare_reading_boundaries,
)


class G2P:
    """숫자가 이미 한글로 변환된 입력의 영문 읽기와 한국어 발음을 처리한다."""

    def __init__(
        self,
        *,
        max_length: int = 10_000,
    ) -> None:
        if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length <= 0:
            raise InputValidationError("max_length는 양의 정수여야 합니다.")
        self._pipeline = Pipeline(max_length=max_length)
        self._input_max_length = max_length

    def __call__(
        self,
        text: str,
        *,
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
    ) -> str:
        """발음 문자열을 반환한다.

        ``pause_boundaries``는 NFC로 정규화한 입력에서, 영문 후보를 치환하기 전의
        Python code point 경계 좌표 iterable이다. ``normalize``는 이전 호출 호환용이다.
        """

        self._validate_normalize(normalize)
        return self._pipeline.run_text(text, pause_boundaries=pause_boundaries)

    def pronounce_many(
        self,
        texts: Iterable[str],
        *,
        normalize: bool = True,
    ) -> Iterator[str]:
        """입력을 미리 모으지 않고 표면 발음을 순서대로 반환한다.

        iterable 자체와 ``normalize``는 호출 시 검증한다. 각 항목의 입력 검증과
        원본 iterator의 예외는 해당 항목을 꺼내는 시점에 발생한다.
        """

        self._validate_normalize(normalize)
        self._validate_texts(texts)
        return map(partial(self, normalize=normalize), texts)

    def convert(
        self,
        text: str,
        *,
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
    ) -> G2PResult:
        """중간 정규화문, 표면 발음, 단계별 진단과 완료 여부를 반환한다.

        정규화 진단의 span은 원문을, 발음 진단의 span은 해당 진단 보고서의
        ``source``를 기준으로 하는 Python code point 좌표다.
        ``pause_boundaries`` 좌표는 NFC 입력에서 영문 후보 치환 전을 기준으로 한다.
        """

        self._validate_normalize(normalize)
        normalization = normalize_nfc(text, max_length=self._input_max_length)
        pronunciation = self._pipeline.run_normalized(
            normalization.text,
            pause_boundaries=pause_boundaries,
        )
        return G2PResult(
            source=text,
            normalized_text=pronunciation.normalized_text,
            surface_pronunciation=pronunciation.surface_pronunciation,
            diagnostics=G2PDiagnostics(
                normalization=DiagnosticReport(
                    text,
                    (),
                ),
                pronunciation=DiagnosticReport(
                    normalization.text,
                    pronunciation.diagnostics,
                ),
            ),
            complete=pronunciation.complete,
        )

    def convert_with_alignment(
        self,
        text: str,
        *,
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
    ) -> G2PAlignedResult:
        """기존 상세 결과와 원문 code point 정렬 sidecar를 한 번의 실행으로 반환한다.

        정렬 source 좌표는 호출자가 전달한 원문 Python code point다. 내부 NFC와
        영문 읽기 trace를 실제 segment provenance로 합성하며, trace가 작업 단위뿐이면
        coarse로 표시한다.
        """

        self._validate_normalize(normalize)
        normalization = normalize_nfc(text, max_length=self._input_max_length)
        pronunciation = self._pipeline.run_normalized(
            normalization.text,
            pause_boundaries=pause_boundaries,
        )
        result = G2PResult(
            source=text,
            normalized_text=pronunciation.normalized_text,
            surface_pronunciation=pronunciation.surface_pronunciation,
            diagnostics=G2PDiagnostics(
                normalization=DiagnosticReport(text, ()),
                pronunciation=DiagnosticReport(
                    normalization.text,
                    pronunciation.diagnostics,
                ),
            ),
            complete=pronunciation.complete,
        )
        alignment = build_pronunciation_alignment(text, normalization, pronunciation)
        return G2PAlignedResult(result, alignment)

    def convert_with_reading_conditions(
        self,
        text: str,
        *,
        reading_conditions: Iterable[ReadingBoundary] = (),
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
    ) -> G2PReadingConditionResult:
        """원문 좌표의 명시 읽기 조리법을 같은 변환·정렬에서 실행한다."""

        self._validate_normalize(normalize)
        normalization = normalize_nfc(text, max_length=self._input_max_length)
        requests = prepare_reading_boundaries(normalization, reading_conditions)
        pronunciation = self._pipeline.run_normalized(
            normalization.text,
            pause_boundaries=pause_boundaries,
            reading_conditions=requests,
        )
        result = G2PResult(
            source=text,
            normalized_text=pronunciation.normalized_text,
            surface_pronunciation=pronunciation.surface_pronunciation,
            diagnostics=G2PDiagnostics(
                normalization=DiagnosticReport(text, ()),
                pronunciation=DiagnosticReport(normalization.text, pronunciation.diagnostics),
            ),
            complete=pronunciation.complete,
        )
        alignment = build_pronunciation_alignment(text, normalization, pronunciation)
        return G2PReadingConditionResult(
            G2PAlignedResult(result, alignment), pronunciation.condition_executions,
        )

    def convert_with_variants(
        self,
        text: str,
        *,
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
        profile: str = "standard_vowels_v1",
    ) -> G2PVowelVariantResult:
        """기존 변환 한 번과 별도 보조 분석으로 지역 모음 대안을 반환한다."""

        from .vowel_variants import PROFILE_ID, build_vowel_variants

        if profile != PROFILE_ID:
            raise InputValidationError("지원하지 않는 지역 모음 변이 profile입니다.")
        return build_vowel_variants(self.convert_with_alignment(
            text, normalize=normalize, pause_boundaries=pause_boundaries,
        ))
    def convert_with_vowel_length(
        self,
        text: str,
        *,
        normalize: bool = True,
        pause_boundaries: Iterable[int] = (),
        profile: str = "standard_vowel_length_v1",
    ) -> G2PVowelLengthResult:
        """기존 정렬 한 번에 어근·어미 분석으로 판정한 장단음 정보를 더한다."""

        from .vowel_length import PROFILE_ID, build_vowel_length

        if profile != PROFILE_ID:
            raise InputValidationError("지원하지 않는 장단음 profile입니다.")
        return build_vowel_length(self.convert_with_alignment(
            text, normalize=normalize, pause_boundaries=pause_boundaries,
        ))

    def convert_many(
        self,
        texts: Iterable[str],
        *,
        normalize: bool = True,
    ) -> Iterator[G2PResult]:
        """상세 결과를 입력 순서대로 계산하는 지연 iterator를 반환한다."""

        self._validate_normalize(normalize)
        self._validate_texts(texts)
        return map(partial(self.convert, normalize=normalize), texts)

    @staticmethod
    def _validate_normalize(normalize: bool) -> None:
        if not isinstance(normalize, bool):
            raise InputValidationError("normalize는 불리언이어야 합니다.")

    @staticmethod
    def _validate_texts(texts: Iterable[str]) -> None:
        if isinstance(texts, (str, bytes)) or not isinstance(texts, Iterable):
            raise InputValidationError(
                "texts는 문자열이 아닌 문자열 iterable이어야 합니다."
            )
