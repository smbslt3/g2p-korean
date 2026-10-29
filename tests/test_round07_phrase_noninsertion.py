from __future__ import annotations

import importlib.metadata
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kiwipiepy import Kiwi

from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean import engine as korean_engine
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline


def _rewrite(result, rule_id: str):
    return [item for item in result.rewrites if item.rule_id == rule_id]


def _tokens(text: str, *specs) -> tuple[AnalysisToken, ...]:
    return tuple(AnalysisToken(*spec) for spec in specs)


class _SyntheticAnalyzer:
    """테스트가 지정한 정상 분석 결과를 요청별로 돌려준다."""

    def __init__(self, responses: dict[str, tuple[AnalysisToken, ...]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[AnalysisToken, ...]]] = []

    def analyze_components(self, text: str) -> tuple[AnalysisToken, ...]:
        response = self.responses[text]
        self.calls.append((text, response))
        return response

    def analyze(self, text: str, *, split_complex: bool = False, saisiot: bool = False):
        return self.analyze_components(text)


class PhraseNonInsertionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = Pipeline(max_length=1000)

    def _run_with_response(self, text: str, response: tuple[AnalysisToken, ...]):
        analyzer = _SyntheticAnalyzer({text: response})
        with patch.object(korean_engine, "KiwiAnalyzer", return_value=analyzer):
            result = self.pipeline.run(text)
        self.assertEqual(analyzer.calls, [(text, response)])
        return result

    def test_synthetic_boundary_and_particle_responses_are_consumed(self) -> None:
        cases = (
            (
                "아침 인사",
                _tokens("아침 인사", ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5)),
                "아치 민사", "침 인", "치 민",
            ),
            (
                "작품 이름",
                _tokens("작품 이름", ("작품", "NNG", 0, 2), ("이름", "NNG", 3, 5)),
                "작푸 미름", "품 이", "푸 미",
            ),
            (
                "아침 인사가",
                _tokens(
                    "아침 인사가", ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5),
                    ("가", "JKS", 5, 6),
                ),
                "아치 민사가", "침 인", "치 민",
            ),
            (
                "작품 이름은",
                _tokens(
                    "작품 이름은", ("작품", "NNG", 0, 2), ("이름", "NNG", 3, 5),
                    ("은", "JX", 5, 6),
                ),
                "작푸 미르믄", "품 이", "푸 미",
            ),
        )
        for text, response, expected, before, after in cases:
            with self.subTest(text=text):
                result = self._run_with_response(text, response)
                self.assertEqual(result.surface_pronunciation, expected)
                self.assertEqual(len(text), len(result.surface_pronunciation))
                lexical = _rewrite(result, "ko.liaison.lexical")
                self.assertEqual([(item.before, item.after) for item in lexical], [(before, after)])
                self.assertFalse(_rewrite(result, "ko.n_insertion.word"))

    def test_synthetic_positive_copula_tails_are_consumed_strictly(self) -> None:
        cases = (
            (
                "아침 인사이다.",
                _tokens(
                    "아침 인사이다.", ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5),
                    ("이", "VCP", 5, 6), ("다", "EF", 6, 7),
                ),
                "아치 민사이다.", "침 인", "치 민", False,
            ),
            (
                "작품 이름이면.",
                _tokens(
                    "작품 이름이면.", ("작품", "NNG", 0, 2), ("이름", "NNG", 3, 5),
                    ("이", "VCP", 5, 6), ("면", "EC", 6, 7),
                ),
                "작푸 미르미면.", "품 이", "푸 미", False,
            ),
            (
                "작품 이름이다.",
                _tokens(
                    "작품 이름이다.", ("작품", "NNG", 0, 2),
                    ("이름이다", "NNG+VCP+EF", 3, 7,
                     (("이름", "NNG"), ("이", "VCP"), ("다", "EF"))),
                ),
                "작푸 미르미다.", "품 이", "푸 미", False,
            ),
            (
                "작품 이름인.",
                _tokens(
                    "작품 이름인.", ("작품", "NNG", 0, 2),
                    ("이름인", "NNG+VCP+ETM", 3, 6,
                     (("이름", "NNG"), ("이", "VCP"), ("ㄴ", "ETM"))),
                ),
                "작푸 미르민.", "품 이", "푸 미", False,
            ),
            (
                "아침 인사하는",
                _tokens(
                    "아침 인사하는", ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5),
                    ("하", "VV", 5, 6), ("는", "ETM", 6, 7),
                ),
                "아침 닌사하는", "침 인", "침 닌", True,
            ),
        )
        for text, response, expected, before, after, expect_insertion in cases:
            with self.subTest(text=text):
                result = self._run_with_response(text, response)
                self.assertEqual(result.surface_pronunciation, expected)
                self.assertEqual(len(text), len(result.surface_pronunciation))
                self.assertEqual(
                    [(item.before, item.after) for item in _rewrite(result, "ko.liaison.lexical")],
                    [] if expect_insertion else [(before, after)],
                )
                insertions = _rewrite(result, "ko.n_insertion.word")
                self.assertEqual(bool(insertions), expect_insertion)
                if expect_insertion:
                    self.assertEqual((insertions[0].before, insertions[0].after), (before, after))

    def test_repeated_occurrences_and_spaces_are_preserved(self) -> None:
        cases = (
            (
                "아침  인사",
                _tokens("아침  인사", ("아침", "NNG", 0, 2), ("인사", "NNG", 4, 6)),
                "아치  민사", [("침  인", "치  민")],
                [(1, 2, "침"), (2, 3, " "), (3, 4, " "), (4, 5, "인")],
            ),
            (
                "아침 인사 아침 인사",
                _tokens(
                    "아침 인사 아침 인사", ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5),
                    ("아침", "NNG", 6, 8), ("인사", "NNG", 9, 11),
                ),
                "아치 민사 아치 민사", [("침 인", "치 민"), ("침 인", "치 민")], None,
            ),
        )
        for text, response, expected, rewrite_pairs, expected_spans in cases:
            with self.subTest(text=text):
                result = self._run_with_response(text, response)
                self.assertEqual(result.surface_pronunciation, expected)
                self.assertEqual(len(text), len(result.surface_pronunciation))
                lexical = _rewrite(result, "ko.liaison.lexical")
                self.assertEqual([(item.before, item.after) for item in lexical], rewrite_pairs)
                if expected_spans is not None:
                    self.assertEqual(
                        [(span.start, span.end, span.surface) for span in lexical[0].source_spans],
                        expected_spans,
                    )
                self.assertFalse(_rewrite(result, "ko.n_insertion.word"))

    def test_unknown_whole_token_substrings_do_not_match(self) -> None:
        cases = (
            (
                "새아침 인사",
                _tokens("새아침 인사", ("새아침", "NNG", 0, 3), ("인사", "NNG", 4, 6)),
                "침 인", "침 닌",
            ),
            (
                "아침 인사말",
                _tokens("아침 인사말", ("아침", "NNG", 0, 2), ("인사말", "NNG", 3, 6)),
                "침 인", "침 닌",
            ),
            (
                "작품 이름표",
                _tokens("작품 이름표", ("작품", "NNG", 0, 2), ("이름표", "NNG", 3, 6)),
                "품 이", "품 니",
            ),
        )
        for text, response, before, after in cases:
            with self.subTest(text=text):
                result = self._run_with_response(text, response)
                insertions = _rewrite(result, "ko.n_insertion.word")
                self.assertEqual(len(insertions), 1, result.rewrites)
                self.assertEqual((insertions[0].before, insertions[0].after), (before, after))
                self.assertFalse(_rewrite(result, "ko.liaison.lexical"))

    def test_current_kiwi_analysis_and_positive_controls(self) -> None:
        self.assertEqual(importlib.metadata.version("kiwipiepy"), "0.24.1")
        self.assertEqual(importlib.metadata.version("kiwipiepy_model"), "0.24.0")
        Kiwi()
        analyzer = KiwiAnalyzer()
        expected_tokens = {
            "아침 인사": [("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5)],
            "작품 이름": [("작품", "NNG", 0, 2), ("이름", "NNG", 3, 5)],
            "아침 인사가": [
                ("아침", "NNG", 0, 2), ("인사", "NNG", 3, 5), ("가", "JKS", 5, 6),
            ],
            "작품 이름은": [
                ("작품", "NNG", 0, 2), ("이름", "NNG", 3, 5), ("은", "JX", 5, 6),
            ],
        }
        for text, expected in expected_tokens.items():
            with self.subTest(text=text):
                self.assertEqual(
                    [(item.form, item.tag, item.normalized_start, item.normalized_end)
                     for item in analyzer.analyze_components(text)],
                    expected,
                )

        for text, expected in (
            ("아침 인사", "아치 민사"),
            ("작품 이름", "작푸 미름"),
            ("아침 인사가", "아치 민사가"),
            ("작품 이름은", "작푸 미르믄"),
            ("옷 입다", "온 닙따"),
            ("한 일", "한 닐"),
        ):
            with self.subTest(text=text):
                result = self.pipeline.run(text)
                self.assertEqual(result.surface_pronunciation, expected)
                if text in {"옷 입다", "한 일"}:
                    self.assertEqual(len(_rewrite(result, "ko.n_insertion.word")), 1)
                else:
                    self.assertFalse(_rewrite(result, "ko.n_insertion.word"))

    def test_current_kiwi_contracted_copula_analysis_is_consumed(self) -> None:
        real_analyzer = korean_engine.KiwiAnalyzer
        calls = []

        class RecordingAnalyzer(real_analyzer):
            def analyze_components(self, text: str):
                tokens = super().analyze_components(text)
                calls.append((text, tokens))
                return tokens

        cases = (
            (
                "작품 이름인", "작푸 미르민", "품 이", "푸 미",
                [
                    ("작품", "NNG", 0, 2, (("작품", "NNG"),)),
                    ("이름", "NNG", 3, 5, (("이름", "NNG"),)),
                    ("인", "VCP+ETM", 5, 6, (("이", "VCP"), ("ᆫ", "ETM"))),
                ],
            ),
            (
                "아침 인사인", "아치 민사인", "침 인", "치 민",
                [
                    ("아침", "NNG", 0, 2, (("아침", "NNG"),)),
                    ("인사", "NNG", 3, 5, (("인사", "NNG"),)),
                    ("인", "VCP+ETM", 5, 6, (("이", "VCP"), ("ᆫ", "ETM"))),
                ],
            ),
        )
        for text, expected_surface, before, after, expected_tokens in cases:
            with self.subTest(text=text):
                calls.clear()
                with patch.object(korean_engine, "KiwiAnalyzer", RecordingAnalyzer):
                    result = self.pipeline.run(text)
                self.assertEqual(len(calls), 1)
                request, supplied = calls[0]
                self.assertEqual(request, text)
                self.assertEqual(
                    [(item.form, item.tag, item.normalized_start, item.normalized_end, item.morphemes)
                     for item in supplied],
                    expected_tokens,
                )
                self.assertEqual(ord(supplied[-1].morphemes[1][0]), 0x11AB)
                self.assertEqual(result.surface_pronunciation, expected_surface)
                lexical = _rewrite(result, "ko.liaison.lexical")
                self.assertEqual([(item.before, item.after) for item in lexical], [(before, after)])
                self.assertFalse(_rewrite(result, "ko.n_insertion.word"))

    def test_attached_particle_punctuation_pause_and_hard_guards(self) -> None:
        attached = self.pipeline.run("작품의 이름")
        self.assertEqual(
            [(item.form, item.tag) for item in KiwiAnalyzer().analyze_components("작품의 이름")],
            [("작품", "NNG"), ("의", "JKG"), ("이름", "NNG")],
        )
        self.assertEqual(attached.surface_pronunciation, "작푸메 이름")
        self.assertFalse(_rewrite(attached, "ko.n_insertion.word"))
        self.assertFalse(_rewrite(attached, "ko.liaison.lexical"))

        punctuated = self.pipeline.run("아침, 인사")
        self.assertEqual(punctuated.surface_pronunciation, "아침, 인사")
        self.assertFalse(_rewrite(punctuated, "ko.n_insertion.word"))
        self.assertFalse(_rewrite(punctuated, "ko.liaison.lexical"))

        paused = self.pipeline.run("아침 인사", pause_boundaries=(3,))
        self.assertEqual(paused.surface_pronunciation, "아침 인사")
        self.assertFalse(_rewrite(paused, "ko.n_insertion.word"))
        self.assertFalse(_rewrite(paused, "ko.liaison.lexical"))

        source = "아침 인사"
        segments = (
            OutputSegment(
                "아침 ", (SourceSpan.from_source(source, 0, 3),), Handler.KOREAN,
                "합성 HARD 경계 검사", boundary_after=Boundary.HARD,
            ),
            OutputSegment(
                "인사", (SourceSpan.from_source(source, 3, 5),), Handler.KOREAN,
                "합성 HARD 경계 검사", boundary_before=Boundary.HARD,
            ),
        )
        hard = korean_engine.pronounce(segments)
        self.assertEqual(hard.text, source)
        self.assertFalse(_rewrite(hard, "ko.n_insertion.word"))
        self.assertFalse(_rewrite(hard, "ko.liaison.lexical"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
