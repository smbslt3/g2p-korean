"""공개 정렬 계약의 합성 및 pipeline trace 테스트."""

from __future__ import annotations

import unittest
import unicodedata

from g2p_ko import (
    AlignmentEntry,
    AlignmentPrecision,
    AlignmentRelation,
    AlignmentStatus,
    G2P,
    PronunciationAlignment,
    RewriteStage,
    SourceSpan,
)


class PronunciationAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.g2p = G2P()

    def test_raw_nfd_hangul_keeps_raw_codepoint_coordinates(self) -> None:
        source = "가"
        aligned = self.g2p.convert_with_alignment(source)

        self.assertEqual(aligned.result.normalized_text, "가")
        self.assertEqual(aligned.result.surface_pronunciation, "가")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.COARSE)
        self.assertEqual(len(aligned.alignment.entries), 1)
        entry = aligned.alignment.entries[0]
        self.assertEqual((entry.output_start, entry.output_end), (0, 1))
        self.assertEqual(entry.source_spans, (SourceSpan.from_source(source, 0, 2),))
        self.assertEqual(entry.relation, AlignmentRelation.CONTRACTION)
        self.assertEqual(entry.stage, RewriteStage.UNICODE)
        self.assertEqual(entry.precision, AlignmentPrecision.OPERATION)
        self.assertEqual(aligned.alignment.extract_target(0, 2).pronunciation, "가")
        self.assertEqual(aligned.alignment.extract_target(0, 1).reason, "partial_operation")

    def test_canonical_combining_sequence_uses_cluster_provenance(self) -> None:
        source = "e\u0301"
        aligned = self.g2p.convert_with_alignment(source)

        self.assertEqual(aligned.result.normalized_text, "é")
        self.assertEqual(aligned.result.surface_pronunciation, "é")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.COARSE)
        entry = aligned.alignment.entries[0]
        self.assertEqual(entry.source_spans, (SourceSpan.from_source(source, 0, 2),))
        self.assertEqual(entry.relation, AlignmentRelation.CONTRACTION)
        self.assertEqual(aligned.alignment.extract_target(0, 2).pronunciation, "é")
        self.assertEqual(aligned.alignment.extract_target(1, 2).reason, "partial_operation")

    def test_canonical_reordering_cluster_is_one_coarse_operation(self) -> None:
        source = "a\u0315\u0300"
        aligned = self.g2p.convert_with_alignment(source)

        self.assertEqual(aligned.result.normalized_text, "à\u0315")
        self.assertEqual(aligned.result.surface_pronunciation, "à\u0315")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.COARSE)
        self.assertEqual(len(aligned.alignment.entries), 1)
        entry = aligned.alignment.entries[0]
        self.assertEqual((entry.output_start, entry.output_end), (0, 2))
        self.assertEqual(entry.source_spans, (SourceSpan.from_source(source, 0, 3),))
        self.assertEqual(entry.relation, AlignmentRelation.CONTRACTION)
        self.assertEqual(entry.stage, RewriteStage.UNICODE)
        self.assertEqual(entry.rule_id, "unicode.nfc")
        self.assertEqual(aligned.alignment.extract_target(0, 3).pronunciation, "à\u0315")
        self.assertEqual(aligned.alignment.extract_target(0, 1).reason, "partial_operation")

    def test_same_length_sound_replacement_uses_phonology_trace(self) -> None:
        aligned = self.g2p.convert_with_alignment("국물")

        self.assertEqual(aligned.result.normalized_text, "국물")
        self.assertEqual(aligned.result.surface_pronunciation, "궁물")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.EXACT)
        first = aligned.alignment.entries[0]
        self.assertEqual(first.source_spans, (SourceSpan.from_source("국물", 0, 1),))
        self.assertEqual(first.relation, AlignmentRelation.SUBSTITUTION)
        self.assertEqual(first.stage, RewriteStage.PHONOLOGY)
        self.assertEqual(first.kind, "phonological_rule")
        self.assertIsNotNone(first.rule_id)
        self.assertEqual(aligned.alignment.extract_target(0, 1).pronunciation, "궁")

    def test_nfd_sound_change_keeps_phonology_attribution_in_coarse_entry(self) -> None:
        source = unicodedata.normalize("NFD", "국물")
        aligned = self.g2p.convert_with_alignment(source)

        self.assertEqual(aligned.result.normalized_text, "국물")
        self.assertEqual(aligned.result.surface_pronunciation, "궁물")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.COARSE)
        first = aligned.alignment.entries[0]
        self.assertEqual(first.source_spans, (SourceSpan.from_source(source, 0, 3),))
        self.assertEqual(first.relation, AlignmentRelation.CONTRACTION)
        self.assertEqual(first.stage, RewriteStage.PHONOLOGY)
        self.assertEqual(first.kind, "phonological_rule")
        self.assertEqual(first.rule_id, "ko.nasalization")
        self.assertEqual(aligned.alignment.extract_target(0, 3).pronunciation, "궁")
        self.assertEqual(aligned.alignment.extract_target(0, 1).reason, "partial_operation")

    def test_actual_english_reading_is_a_coarse_group(self) -> None:
        aligned = self.g2p.convert_with_alignment("AI")

        self.assertEqual(aligned.result.normalized_text, "에이아이")
        self.assertEqual(aligned.result.surface_pronunciation, "에이아이")
        self.assertEqual(aligned.alignment.status, AlignmentStatus.COARSE)
        self.assertEqual(len(aligned.alignment.entries), 1)
        entry = aligned.alignment.entries[0]
        self.assertEqual((entry.output_start, entry.output_end), (0, len("에이아이")))
        self.assertEqual(entry.source_spans, (SourceSpan.from_source("AI", 0, 2),))
        self.assertEqual(entry.relation, AlignmentRelation.GROUPED)
        self.assertEqual(entry.kind, "lexical_reading")
        self.assertEqual(entry.stage, RewriteStage.LEXICAL)
        self.assertEqual(aligned.alignment.extract_target(0, 2).pronunciation, "에이아이")
        self.assertEqual(aligned.alignment.extract_target(0, 1).reason, "partial_operation")

    def test_identity_and_preserved_text_are_exact_even_if_incomplete(self) -> None:
        text = "日本"
        aligned = self.g2p.convert_with_alignment(text)

        self.assertEqual(aligned.result.surface_pronunciation, text)
        self.assertFalse(aligned.result.complete)
        self.assertEqual(aligned.alignment.status, AlignmentStatus.EXACT)
        self.assertTrue(all(entry.relation is AlignmentRelation.IDENTITY for entry in aligned.alignment.entries))
        self.assertEqual(aligned.alignment.extract_target(1, 2).pronunciation, "本")

    def test_alignment_calls_pipeline_once_and_legacy_dict_shape_stays_fixed(self) -> None:
        g2p = G2P()
        original = g2p._pipeline.run_normalized
        calls = 0

        def counted(source: str, *, pause_boundaries=()):
            nonlocal calls
            calls += 1
            return original(source, pause_boundaries=pause_boundaries)

        g2p._pipeline.run_normalized = counted
        aligned = g2p.convert_with_alignment("국물")

        self.assertEqual(calls, 1)
        self.assertEqual(aligned.result.surface_pronunciation, "궁물")
        legacy = G2P().convert("국물").to_dict()
        self.assertEqual(
            set(legacy),
            {"source", "normalized_text", "surface_pronunciation", "diagnostics", "complete"},
        )
        self.assertNotIn("alignment", legacy)

    def test_expansion_contraction_insertion_and_deletion_model_operations(self) -> None:
        source = "ab"
        expansion = PronunciationAlignment(
            "a",
            "xy",
            (
                AlignmentEntry(
                    0,
                    2,
                    (SourceSpan.from_source("a", 0, 1),),
                    AlignmentRelation.EXPANSION,
                    RewriteStage.LEXICAL,
                    "synthetic_expansion",
                    "synthetic.expansion",
                    precision=AlignmentPrecision.OPERATION,
                ),
            ),
        )
        self.assertEqual(expansion.extract_target(0, 1).pronunciation, "xy")

        insertion = PronunciationAlignment(
            source,
            "aXb",
            (
                AlignmentEntry(
                    0, 1, (SourceSpan.from_source(source, 0, 1),), AlignmentRelation.IDENTITY
                ),
                AlignmentEntry(
                    1,
                    2,
                    (),
                    AlignmentRelation.INSERTION,
                    kind="phonological_rule",
                    rule_id="synthetic.insertion",
                    anchor=SourceSpan.from_source(source, 1, 1),
                    insertion_rule="synthetic.insertion",
                    precision=AlignmentPrecision.OPERATION,
                ),
                AlignmentEntry(
                    2, 3, (SourceSpan.from_source(source, 1, 2),), AlignmentRelation.IDENTITY
                ),
            ),
        )
        self.assertEqual(insertion.extract_target(0, 2).pronunciation, "aXb")

        deletion = PronunciationAlignment(
            source,
            "a",
            (
                AlignmentEntry(
                    0, 1, (SourceSpan.from_source(source, 0, 1),), AlignmentRelation.IDENTITY
                ),
                AlignmentEntry(
                    1,
                    1,
                    (SourceSpan.from_source(source, 1, 2),),
                    AlignmentRelation.DELETION,
                    RewriteStage.LEXICAL,
                    "lexical_reading",
                    "synthetic.deletion",
                    precision=AlignmentPrecision.OPERATION,
                ),
            ),
        )
        self.assertEqual(deletion.extract_target(1, 2).pronunciation, "")
        self.assertEqual(deletion.status, AlignmentStatus.COARSE)

        unavailable = PronunciationAlignment(
            "a",
            "?",
            (
                AlignmentEntry(
                    0,
                    1,
                    (SourceSpan.from_source("a", 0, 1),),
                    AlignmentRelation.UNAVAILABLE,
                    kind="unavailable",
                    precision=AlignmentPrecision.UNAVAILABLE,
                ),
            ),
        )
        self.assertEqual(unavailable.status, AlignmentStatus.UNAVAILABLE)
        self.assertEqual(
            unavailable.extract_target(0, 1).reason,
            "unavailable_alignment",
        )

        with self.assertRaises(ValueError):
            PronunciationAlignment("ab", "", ())
        with self.assertRaises(ValueError):
            PronunciationAlignment(
                "ab",
                "a",
                (
                    AlignmentEntry(
                        0,
                        1,
                        (SourceSpan.from_source("ab", 0, 1),),
                        AlignmentRelation.IDENTITY,
                    ),
                ),
            )
        missing_provenance = PronunciationAlignment(
            "ab",
            "",
            (),
            source_coverage_unavailable=True,
        )
        self.assertEqual(missing_provenance.status, AlignmentStatus.UNAVAILABLE)

    def test_target_extraction_uses_raw_anchor_boundaries(self) -> None:
        source = "가x"
        alignment = PronunciationAlignment(
            source,
            "가Xx",
            (
                AlignmentEntry(
                    0,
                    1,
                    (SourceSpan.from_source(source, 0, 2),),
                    AlignmentRelation.CONTRACTION,
                    RewriteStage.UNICODE,
                    "unicode_normalization",
                    "unicode.nfc",
                    precision=AlignmentPrecision.OPERATION,
                ),
                AlignmentEntry(
                    1,
                    2,
                    (),
                    AlignmentRelation.INSERTION,
                    kind="phonological_rule",
                    rule_id="synthetic.insertion",
                    anchor=SourceSpan.from_source(source, 2, 2),
                    insertion_rule="synthetic.insertion",
                    precision=AlignmentPrecision.OPERATION,
                ),
                AlignmentEntry(
                    2,
                    3,
                    (SourceSpan.from_source(source, 2, 3),),
                    AlignmentRelation.IDENTITY,
                ),
            ),
        )
        self.assertEqual(alignment.extract_target(0, 2).pronunciation, "가")
        self.assertEqual(alignment.extract_target(2, 3).pronunciation, "Xx")
        self.assertEqual(alignment.extract_target(0, 3).pronunciation, "가Xx")


if __name__ == "__main__":
    unittest.main()
