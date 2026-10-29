"""한국어 TTS 입력 정규화의 공개 API다."""

from .engine import G2P
from .alignment import (
    AlignmentEntry,
    AlignmentPrecision,
    AlignmentRelation,
    AlignmentStatus,
    G2PAlignedResult,
    PronunciationAlignment,
    TargetExtraction,
)
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
from .number_reader import HuggingFaceNumberReader
from .number_normalizer import normalize_numbers

__all__ = [
    "BackendUnavailableError",
    "Boundary",
    "AlignmentEntry",
    "AlignmentPrecision",
    "AlignmentRelation",
    "AlignmentStatus",
    "ConversionPolicyError",
    "Diagnostic",
    "DiagnosticReport",
    "G2P",
    "G2PAlignedResult",
    "G2PDiagnostics",
    "G2PError",
    "G2PResult",
    "Handler",
    "HuggingFaceNumberReader",
    "InputValidationError",
    "KoreanTTSNormalizer",
    "NormalizationResult",
    "normalize_numbers",
    "OutputSegment",
    "PronunciationAlignment",
    "Rewrite",
    "RewriteStage",
    "Severity",
    "SourceSpan",
    "TargetExtraction",
]

from .vowel_variants import G2PVowelVariantResult, VowelAlternative, VowelVariantDecision, VowelVariantSlot
__all__ += ["G2PVowelVariantResult", "VowelAlternative", "VowelVariantDecision", "VowelVariantSlot"]

from .vowel_length import G2PVowelLengthResult, VowelLengthDecision
__all__ += ["G2PVowelLengthResult", "VowelLengthDecision"]

from .reading_conditions import G2PReadingConditionResult, ReadingBoundary, ReadingBoundaryExecution
__all__ += ["G2PReadingConditionResult", "ReadingBoundary", "ReadingBoundaryExecution"]
