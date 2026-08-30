"""고정된 한국어 TTS 파이프라인의 공개 진입점이다."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from functools import partial

from .errors import InputValidationError
from .model import DiagnosticReport, G2PDiagnostics, G2PResult
from .normalizer import KoreanTTSNormalizer, NormalizationResult
from .pipeline import Pipeline
from .unicode import normalize_nfc, normalize_nfc_text


class G2P:
    """원문 또는 정규화된 발화형을 표면 발음으로 변환한다."""

    def __init__(
        self,
        *,
        lexicon: Mapping[str, str] | None = None,
        max_length: int = 10_000,
    ) -> None:
        self._normalizer = KoreanTTSNormalizer(
            lexicon=lexicon,
            max_length=max_length,
        )
        self._pipeline = Pipeline(max_length=max_length * 16)
        self._input_max_length = max_length

    def __call__(self, text: str, *, normalize: bool = True) -> str:
        """선택적으로 정규화한 뒤 표면 발음을 반환한다.

        ``normalize=False``는 이미 정규화된 입력에서 TTS 노멀라이저만 생략한다.
        기본 입력 검증과 NFC 정규화는 두 경로에서 모두 유지한다.
        """

        self._validate_normalize(normalize)
        source = (
            self._normalizer(text)
            if normalize
            else normalize_nfc_text(text, max_length=self._input_max_length)
        )
        return self._pipeline.run_text(source)

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

    def convert(self, text: str, *, normalize: bool = True) -> G2PResult:
        """중간 정규화문, 표면 발음, 단계별 진단과 완료 여부를 반환한다.

        정규화 진단의 span은 원문을, 발음 진단의 span은 해당 진단 보고서의
        ``source``를 기준으로 하는 Python code point 좌표다.
        """

        self._validate_normalize(normalize)
        normalization = (
            self._normalizer.convert(text)
            if normalize
            else self._nfc_result(text)
        )
        pronunciation = self._pipeline.run(normalization.normalized_text)
        return G2PResult(
            source=text,
            normalized_text=pronunciation.normalized_text,
            surface_pronunciation=pronunciation.surface_pronunciation,
            diagnostics=G2PDiagnostics(
                normalization=DiagnosticReport(
                    normalization.source,
                    normalization.diagnostics,
                ),
                pronunciation=DiagnosticReport(
                    normalization.normalized_text,
                    pronunciation.diagnostics,
                ),
            ),
            complete=normalization.complete and pronunciation.complete,
        )

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

    def _nfc_result(self, text: str) -> NormalizationResult:
        """노멀라이저를 생략한 상세 경로의 입력 검증과 NFC 결과를 만든다."""

        normalized = normalize_nfc(text, max_length=self._input_max_length)
        return NormalizationResult(
            source=text,
            normalized_text=normalized.text,
            rewrites=normalized.rewrites,
        )
