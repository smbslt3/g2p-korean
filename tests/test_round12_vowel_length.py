"""장단음의 조건부 계약·실제 분석·원문 정렬·API 보존을 검증한다."""

import dataclasses
import importlib.metadata
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
import g2p_ko.analyzer as analyzer
from g2p_ko import G2P, InputValidationError
from g2p_ko.alignment import AlignmentPrecision, AlignmentRelation, PronunciationAlignment
from g2p_ko.model import AnalysisToken
from g2p_ko.vowel_length import build_vowel_length

SPEC = json.loads((ROOT / "fixtures/round12_vowel_length.json").read_text(encoding="utf-8"))


def correct_tokens(text):
    """실제 분석과 다른 두 조건부 계약에는 명시적으로 올바른 분석을 제공한다."""
    if text in {"아는", "아니"}:
        tag = "ETM" if text == "아는" else "EC"
        return (AnalysisToken("아", "VV", 0, 1, (("알", "VV"),)),
                AnalysisToken(text[1:], tag, 1, 2, ((text[1:], tag),)))
    return analyzer.KiwiAnalyzer().analyze(text)


class VowelLengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = G2P()

    def test_versions(self):
        self.assertEqual(importlib.metadata.version("kiwipiepy"), "0.24.1")
        self.assertEqual(importlib.metadata.version("kiwipiepy_model"), "0.24.0")

    def test_conditional_positive_26(self):
        for fixture in SPEC["conditional_positive_fixtures"]:
            text = fixture["input"]
            aligned = self.g.convert_with_alignment(text)
            provided = correct_tokens(text)
            with self.subTest(text=text), patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
                provider.return_value.analyze.return_value = provided
                result = build_vowel_length(aligned)
                d, = result.decisions
                self.assertEqual((d.value, d.status), (fixture["expected_value"], "supported"))
                self.assertEqual(d.lemma, fixture["required_lemma"])
                self.assertEqual(d.pos, fixture["required_pos"])
                self.assertEqual([d.owner_source_span.start, d.owner_source_span.end], fixture["owner_source_span"])
                self.assertEqual([d.nucleus_source_span.start, d.nucleus_source_span.end], fixture["nucleus_source_span"])
                self.assertEqual(list(d.output_nucleus_syllable_span), fixture["output_nucleus_syllable_span"])
                provider.return_value.analyze.assert_called_once_with(text)

    def test_generalization(self):
        for fixture in SPEC["additional_predeclared_generalization_probes"]:
            text = fixture["input"]
            with self.subTest(text=text):
                if text == "알다 알아":
                    aligned = self.g.convert_with_alignment(text)
                    provided = (AnalysisToken("알", "VV", 0, 1, (("알", "VV"),)),
                        AnalysisToken("다", "EF", 1, 2, (("다", "EF"),)),
                        AnalysisToken("알", "VV", 3, 4, (("알", "VV"),)),
                        AnalysisToken("아", "EF", 4, 5, (("어", "EF"),)))
                    with patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
                        provider.return_value.analyze.return_value = provided
                        result = build_vowel_length(aligned)
                    self.assertEqual([d.value for d in result.decisions], ["long", "short"])
                    self.assertEqual([d.output_nucleus_syllable_span for d in result.decisions], [(0, 1), (3, 4)])
                else:
                    d, = self.g.convert_with_vowel_length(text).decisions
                    self.assertEqual(d.value, fixture["expected_value"])
                    if "nucleus_source_span" in fixture:
                        self.assertEqual([d.nucleus_source_span.start, d.nucleus_source_span.end], fixture["nucleus_source_span"])
                        self.assertEqual(len(d.nucleus_source_atoms), 3)

    def test_unknown_does_not_become_short(self):
        for text in ["가다", "아니", "알", "맛없다", "알리다", "봐", "아는"]:
            with self.subTest(text=text):
                result = self.g.convert_with_vowel_length(text)
                self.assertTrue(all(d.value == "unknown" and d.status != "supported" for d in result.decisions))

    def test_local_anchor_english_and_liaison(self):
        result = self.g.convert_with_vowel_length("ABC 알아 알아")
        self.assertEqual([d.value for d in result.decisions], ["short", "short"])
        self.assertEqual([d.output_nucleus_syllable_span for d in result.decisions], [(5, 6), (8, 9)])
        self.assertEqual([d.nucleus_source_span.start for d in result.decisions], [4, 7])
        self.assertEqual(result.aligned.alignment.status.value, "coarse")
        result = self.g.convert_with_vowel_length("나는 알아")
        self.assertEqual(result.decisions[-1].value, "short")
        self.assertEqual(result.decisions[-1].output_nucleus_syllable_span, (3, 4))

    def test_coarse_nucleus_is_unknown(self):
        aligned = self.g.convert_with_alignment("알아")
        entries = tuple(dataclasses.replace(e, precision=AlignmentPrecision.OPERATION) for e in aligned.alignment.entries)
        coarse = dataclasses.replace(aligned, alignment=PronunciationAlignment("알아", "아라", entries))
        d, = build_vowel_length(coarse).decisions
        self.assertEqual((d.value, d.reason), ("unknown", "nucleus_output_anchor_unresolved"))

    def test_wrong_owner_and_l_drop(self):
        for text, parts in [("맛없다", (("맛", "NNG"), ("없", "VA"), ("다", "EF"))),
                            ("아고", (("알", "VV"), ("고", "EC"))),
                            ("알리다", (("알", "VV"), ("리", "XSV"), ("다", "EF")))]:
            aligned = self.g.convert_with_alignment(text)
            token = AnalysisToken(text, "+".join(x[1] for x in parts), 0, len(text), parts)
            with patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
                provider.return_value.analyze.return_value = (token,)
                d, = build_vowel_length(aligned).decisions
                self.assertEqual(d.value, "unknown")
                self.assertNotEqual(d.status, "supported")

    def test_failure_empty_and_profile(self):
        with patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
            provider.return_value.analyze.side_effect = ValueError("분석 실패")
            result = self.g.convert_with_vowel_length("알아")
            self.assertEqual(result.decisions[0].value, "unknown")
            self.assertEqual(result.auxiliary_analysis_calls, 1)
        self.assertEqual(self.g.convert_with_vowel_length("").auxiliary_analysis_calls, 0)
        self.assertEqual(self.g.convert_with_vowel_length("ABC").auxiliary_analysis_calls, 0)
        with self.assertRaises(InputValidationError):
            self.g.convert_with_vowel_length("알아", profile="other")

    def test_one_base_call_and_serialization(self):
        with patch.object(self.g, "convert_with_alignment", wraps=self.g.convert_with_alignment) as base:
            result = self.g.convert_with_vowel_length("알더라")
            base.assert_called_once()
        self.assertEqual(result.auxiliary_analysis_calls, 1)
        saved = result.to_dict()
        json.dumps(saved, ensure_ascii=False)
        self.assertEqual(saved["aligned"]["result"], self.g.convert("알더라").to_dict())
        self.assertEqual(saved["analysis_provenance"]["base_pipeline_analyzer_calls_status"], "not_instrumented")
        self.assertNotIn(":", result.aligned.result.surface_pronunciation)

    def test_particle_tail_rejects_wrong_role_order(self):
        cases = [("알만다", (("알", "VV"), ("만", "JX"), ("다", "EF"))),
                 ("알고집", (("알", "VV"), ("고", "EC"), ("집", "NNG"))),
                 ("알고도다", (("알", "VV"), ("고", "EC"), ("도", "JX"), ("다", "EF"))),
                 ("알고도집", (("알", "VV"), ("고", "EC"), ("도", "JX"), ("집", "NNG")))]
        for text, parts in cases:
            aligned = self.g.convert_with_alignment(text)
            token = AnalysisToken(text, "+".join(p[1] for p in parts), 0, len(text), parts)
            with self.subTest(text=text), patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
                provider.return_value.analyze.return_value = (token,)
                d, = build_vowel_length(aligned).decisions
                self.assertEqual(d.value, "unknown")
                self.assertNotEqual(d.status, "supported")

    def test_coda_ending_must_own_first_source_syllable(self):
        aligned = self.g.convert_with_alignment("압니다")
        provided = (AnalysisToken("압", "VV", 0, 1, (("알", "VV"),)),
                    AnalysisToken("니다", "EF", 1, 3, (("ᆸ니다", "EF"),)))
        with patch("g2p_ko.vowel_length.KiwiAnalyzer") as provider:
            provider.return_value.analyze.return_value = provided
            d, = build_vowel_length(aligned).decisions
        self.assertEqual(d.value, "unknown")
        self.assertNotEqual(d.status, "supported")


if __name__ == "__main__":
    unittest.main(verbosity=2)
