from __future__ import annotations

import sys
import unicodedata

from g2p_ko import (
    Boundary,
    G2PError,
    Handler,
    InputValidationError,
    OutputSegment,
    Rewrite,
    RewriteStage,
    SourceSpan,
)
from g2p_ko.unicode import normalize_nfc


def test_public_errors_share_neutral_base_class() -> None:
    assert issubclass(InputValidationError, G2PError)


def test_nfc_rewrite_keeps_raw_source_span() -> None:
    source = "\u1100\u1161"
    normalized = normalize_nfc(source)

    assert normalized.text == "가"
    assert normalized.source_span(0, 1) == SourceSpan(0, 2, source, 2)
    assert normalized.rewrites[0].stage is RewriteStage.UNICODE
    assert normalized.rewrites[0].before == source


def test_already_nfc_combining_cluster_keeps_atomic_source_span() -> None:
    source = "a\u0338"
    assert unicodedata.is_normalized("NFC", source)

    normalized = normalize_nfc(source)

    cluster = SourceSpan(0, len(source), source, len(source))
    assert normalized.character_spans == (cluster, cluster)


def test_every_canonical_decomposition_and_hangul_matches_builtin_nfc() -> None:
    for code_point in range(sys.maxunicode + 1):
        character = chr(code_point)
        decomposition = unicodedata.decomposition(character)
        has_canonical_decomposition = bool(decomposition) and not decomposition.startswith("<")
        if not has_canonical_decomposition and not 0xAC00 <= code_point <= 0xD7A3:
            continue
        source = unicodedata.normalize("NFD", character)
        normalized = normalize_nfc(source)

        assert normalized.text == unicodedata.normalize("NFC", source), hex(code_point)
        assert len(normalized.text) == len(normalized.character_spans)
        assert all(
            source[span.start : span.end] == span.surface
            for span in normalized.character_spans
        )


def test_reordered_combining_marks_preserve_one_atomic_source_span() -> None:
    source = "xA\u0315\u0300y"
    normalized = normalize_nfc(source)
    cluster_span = SourceSpan(1, 4, source[1:4], len(source))

    assert normalized.text == "xÀ\u0315y"
    assert normalized.character_spans == (
        SourceSpan(0, 1, "x", len(source)),
        cluster_span,
        cluster_span,
        SourceSpan(4, 5, "y", len(source)),
    )
    assert normalized.source_span(2, 3) == cluster_span
    assert normalized.snap_range(2, 3) == (1, 3)


def test_inserted_segment_requires_explicit_anchor_contract() -> None:
    anchor = SourceSpan.from_source("가", 0, 1)
    inserted = OutputSegment(
        "ㅇ",
        (),
        Handler.KOREAN,
        "inserted",
        insertion_rule="test.insert",
        anchor=anchor,
    )

    assert inserted.source_spans == ()
    assert inserted.anchor == anchor
