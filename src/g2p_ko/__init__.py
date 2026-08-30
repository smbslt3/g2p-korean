"""한국어 TTS 입력 정규화의 공개 API다."""

from .engine import G2P
from .errors import (
    BackendUnavailableError,
    ConversionPolicyError,
    G2PError,
    InputValidationError,
)
from .model import (
    Boundary,
    Diagnostic,
    DiagnosticReport,
    G2PDiagnostics,
    G2PResult,
    Handler,
    OutputSegment,
    Rewrite,
    RewriteStage,
    Severity,
    SourceSpan,
)
from .normalizer import KoreanTTSNormalizer, NormalizationResult

__all__ = [
    "BackendUnavailableError",
    "Boundary",
    "ConversionPolicyError",
    "Diagnostic",
    "DiagnosticReport",
    "G2P",
    "G2PDiagnostics",
    "G2PError",
    "G2PResult",
    "Handler",
    "InputValidationError",
    "KoreanTTSNormalizer",
    "NormalizationResult",
    "OutputSegment",
    "Rewrite",
    "RewriteStage",
    "Severity",
    "SourceSpan",
]
