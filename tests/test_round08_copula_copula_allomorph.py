from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g2p_ko.korean import engine as korean_engine
from g2p_ko.model import AnalysisToken
from g2p_ko.pipeline import Pipeline


def _rewrite(result, rule_id: str):
    return [item for item in result.rewrites if item.rule_id == rule_id]


class _SyntheticAnalyzer:
    def __init__(self, response: tuple[AnalysisToken, ...]) -> None:
        self.response = response
        self.calls: list[str] = []

    def analyze_components(self, text: str) -> tuple[AnalysisToken, ...]:
        self.calls.append(text)
        return self.response

    def analyze(self, text: str, *, split_complex: bool = False, saisiot: bool = False):
        return self.analyze_components(text)


class CopulaAllomorphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = Pipeline(max_length=1000)

    def test_real_provider_consumes_all_positive_copula_allomorphs(self) -> None:
        real_analyzer = korean_engine.KiwiAnalyzer
        calls = []

        class RecordingAnalyzer(real_analyzer):
            def analyze_components(self, text: str):
                tokens = super().analyze_components(text)
                calls.append((text, tokens))
                return tokens

        cases = (
            ("아침 인사예요.", "아치 민사예요.", ("예요", "VCP+EF", (("이", "VCP"), ("예요", "EF")))),
            ("아침 인사다.", "아치 민사다.", ("다", "VCP+EF", (("이", "VCP"), ("다", "EF")))),
            ("아침 인사면.", "아치 민사면.", ("면", "VCP+EC", (("이", "VCP"), ("면", "EC")))),
            ("아침 인사야.", "아치 민사야.", ("야", "VCP+EF", (("이", "VCP"), ("야", "EF")))),
            ("아침 인사였어요.", "아치 민사여써요.", ("였", "VCP+EP", (("이", "VCP"), ("었", "EP")))),
            ("작품 이름이에요.", "작푸 미르미에요.", ("이", "VCP", (("이", "VCP"),))),
        )
        with patch.object(korean_engine, "KiwiAnalyzer", RecordingAnalyzer):
            for text, expected, expected_copula in cases:
                with self.subTest(text=text):
                    calls.clear()
                    result = self.pipeline.run(text)
                    self.assertEqual(len(calls), 1)
                    request, supplied = calls[0]
                    self.assertEqual(request, text)
                    self.assertEqual(result.surface_pronunciation, expected)
                    self.assertEqual(len(text), len(result.surface_pronunciation))
                    self.assertEqual(
                        [
                            (token.form, token.tag, token.morphemes)
                            for token in supplied
                            if token.normalized_start >= 5
                        ][:1],
                        [expected_copula],
                    )
                    self.assertFalse(_rewrite(result, "ko.n_insertion.word"))
                    self.assertEqual(len(_rewrite(result, "ko.liaison.lexical")), 1)

    def test_supplied_normal_copula_alignment_and_merged_ownership(self) -> None:
        cases = (
            (
                "아침 인사예요.",
                (
                    AnalysisToken("아침", "NNG", 0, 2),
                    AnalysisToken("인사", "NNG", 3, 5),
                    AnalysisToken("예요", "VCP+EF", 5, 7, (("이", "VCP"), ("에요", "EF"))),
                    AnalysisToken(".", "SF", 7, 8),
                ),
            ),
            (
                "아침 인사예요.",
                (
                    AnalysisToken("아침", "NNG", 0, 2),
                    AnalysisToken(
                        "인사예요", "NNG+VCP+EF", 3, 7,
                        (("인사", "NNG"), ("이", "VCP"), ("에요", "EF")),
                    ),
                    AnalysisToken(".", "SF", 7, 8),
                ),
            ),
        )
        for text, response in cases:
            with self.subTest(response=response):
                analyzer = _SyntheticAnalyzer(response)
                with patch.object(korean_engine, "KiwiAnalyzer", return_value=analyzer):
                    result = self.pipeline.run(text)
                self.assertEqual(analyzer.calls, [text])
                self.assertEqual(result.surface_pronunciation, "아치 민사예요.")
                self.assertEqual(len(_rewrite(result, "ko.liaison.lexical")), 1)
                self.assertFalse(_rewrite(result, "ko.n_insertion.word"))

    def test_mismatched_merged_morphemes_and_coda_final_contraction_are_refused(self) -> None:
        text = "아침 인사예요."
        false_owner = (
            AnalysisToken("아침", "NNG", 0, 2),
            AnalysisToken(
                "인사예요", "NNG+VCP+EF", 3, 7,
                (("인사", "NNG"), ("이", "VCP"), ("다", "EF")),
            ),
            AnalysisToken(".", "SF", 7, 8),
        )
        analyzer = _SyntheticAnalyzer(false_owner)
        with patch.object(korean_engine, "KiwiAnalyzer", return_value=analyzer):
            rejected = self.pipeline.run(text)
        self.assertEqual(rejected.surface_pronunciation, text)
        self.assertFalse(_rewrite(rejected, "ko.liaison.lexical"))
        self.assertFalse(_rewrite(rejected, "ko.n_insertion.word"))

        coda_text = "작품 이름예요."
        coda_response = (
            AnalysisToken("작품", "NNG", 0, 2),
            AnalysisToken("이름", "NNG", 3, 5),
            AnalysisToken("예요", "VCP+EF", 5, 7, (("이", "VCP"), ("에요", "EF"))),
            AnalysisToken(".", "SF", 7, 8),
        )
        analyzer = _SyntheticAnalyzer(coda_response)
        with patch.object(korean_engine, "KiwiAnalyzer", return_value=analyzer):
            rejected = self.pipeline.run(coda_text)
        self.assertFalse(_rewrite(rejected, "ko.liaison.lexical"))
        # 잘못된 계사 표면은 꼬리 예외와 필수 ㄴ 첨가 양쪽의 근거가 되지 않는다.
        self.assertFalse(_rewrite(rejected, "ko.n_insertion.word"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
