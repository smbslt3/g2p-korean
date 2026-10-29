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
from g2p_ko.korean.hangul import JUNGSEONG, compose_syllable, decompose_syllable
from g2p_ko.korean.morphology import _LEXICAL_LIAISON_VOWELS, _N_INSERTION_VOWELS
from g2p_ko.model import Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.pipeline import Pipeline


RULE15_EXAMPLES = (
    ("ㅏ", "아래"),
    ("ㅐ", "애인"),
    ("ㅓ", "얼굴"),
    ("ㅔ", "에어컨"),
    ("ㅗ", "오리"),
    ("ㅘ", "와요"),
    ("ㅙ", "왜곡"),
    ("ㅚ", "외부"),
    ("ㅜ", "우리"),
    ("ㅝ", "원인"),
    ("ㅞ", "웨딩"),
    ("ㅟ", "위쪽"),
    ("ㅡ", "으뜸"),
    ("ㅢ", "의자"),
)

RULE29_EXAMPLES = (
    ("ㅣ", "이론"),
    ("ㅑ", "야외"),
    ("ㅒ", "얘기"),
    ("ㅕ", "여자"),
    ("ㅖ", "예외"),
    ("ㅛ", "요리"),
    ("ㅠ", "유행"),
)


def _first_syllable(value: str):
    span = SourceSpan.from_source(value, 0, 1)
    return decompose_syllable(value[0], (span,))


def _rewrite(result, rule_id: str):
    return [item for item in result.rewrites if item.rule_id == rule_id]


class LexicalVowelGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = Pipeline(max_length=1000)
        self.analyzer = KiwiAnalyzer()

    def test_exact_runtime_and_inventory_partition(self) -> None:
        self.assertEqual(Path(sys.executable).resolve(), Path(r"D:\Projects\g2p_korean\.venv\Scripts\python.exe"))
        self.assertEqual(importlib.metadata.version("kiwipiepy"), "0.24.1")
        self.assertEqual(importlib.metadata.version("kiwipiepy_model"), "0.24.0")
        self.assertEqual(_LEXICAL_LIAISON_VOWELS | _N_INSERTION_VOWELS, frozenset(JUNGSEONG))
        self.assertFalse(_LEXICAL_LIAISON_VOWELS & _N_INSERTION_VOWELS)
        self.assertEqual(len(_LEXICAL_LIAISON_VOWELS), 14)
        self.assertEqual(len(_N_INSERTION_VOWELS), 7)

    def test_real_kiwi_analysis_covers_each_vowel_family(self) -> None:
        Kiwi()
        for vowel, word in RULE15_EXAMPLES:
            with self.subTest(vowel=vowel, word=word):
                self.assertEqual(_first_syllable(word).vowel, vowel)
                text = "옷 " + word
                raw = self.analyzer.analyze(text)
                following = next(item for item in raw if item.normalized_start == 2)
                self.assertTrue(
                    any(part.startswith(("N", "V", "M")) for part in following.tag.split("+")),
                    (text, raw),
                )
                result = self.pipeline.run(text)
                matches = _rewrite(result, "ko.liaison.lexical")
                self.assertEqual(len(matches), 1, (text, result.surface_pronunciation, result.rewrites))
                target = _first_syllable(word)
                expected_after = "오 " + compose_syllable("ㄷ", vowel, target.coda)
                self.assertEqual((matches[0].before, matches[0].after), ("옷 " + word[0], expected_after))
                self.assertEqual(
                    [(span.start, span.end, span.surface) for span in matches[0].source_spans],
                    [(0, 1, "옷"), (1, 2, " "), (2, 3, word[0])],
                )

        for vowel, word in RULE29_EXAMPLES:
            with self.subTest(vowel=vowel, word=word):
                self.assertEqual(_first_syllable(word).vowel, vowel)
                text = "옷 " + word
                raw = self.analyzer.analyze(text)
                following = next(item for item in raw if item.normalized_start == 2)
                self.assertTrue(following.tag.startswith("NN"), (text, raw))
                result = self.pipeline.run(text)
                self.assertFalse(_rewrite(result, "ko.liaison.lexical"), (text, result.rewrites))
                insertions = _rewrite(result, "ko.n_insertion.word")
                self.assertEqual(len(insertions), 1, (text, result.surface_pronunciation, result.rewrites))
                expected_after = "옷 " + compose_syllable("ㄴ", vowel, _first_syllable(word).coda)
                self.assertEqual((insertions[0].before, insertions[0].after), ("옷 " + word[0], expected_after))

    def test_approved_examples_and_real_provider_consumption(self) -> None:
        real_analyzer = korean_engine.KiwiAnalyzer
        calls = []

        class RecordingAnalyzer(real_analyzer):
            def analyze_components(self, text: str):
                tokens = super().analyze_components(text)
                calls.append((text, tokens))
                return tokens

        with patch.object(korean_engine, "KiwiAnalyzer", RecordingAnalyzer):
            result = self.pipeline.run("안 와요")

        self.assertEqual(result.surface_pronunciation, "아 놔요")
        lexical = _rewrite(result, "ko.liaison.lexical")
        self.assertEqual([(item.before, item.after) for item in lexical], [("안 와", "아 놔")])
        self.assertEqual(len(calls), 1)
        request, supplied = calls[0]
        self.assertEqual(request, "안 와요")
        self.assertEqual(
            [(item.form, item.tag) for item in supplied],
            [("안", "MAG"), ("와", "VV+EF"), ("요", "JX")],
        )

        for text, expected in (("옷 와요", "오 돠요"), ("옷 외부", "오 되부")):
            with self.subTest(text=text):
                checked = self.pipeline.run(text)
                self.assertEqual(checked.surface_pronunciation, expected)
                self.assertEqual(len(_rewrite(checked, "ko.liaison.lexical")), 1)

        kiwi = Kiwi()
        self.assertEqual(
            [(item.form, item.tag, item.start, item.len) for item in kiwi.tokenize("옷 외부", split_complex=True, saisiot=True)],
            [("옷", "NNG", 0, 1), ("외부", "NNG", 2, 2)],
        )

    def test_representative_coda_contrasts_and_ng_exception(self) -> None:
        for text, left, onset in (
            ("옷 외부", "옷", "ㄷ"),
            ("밥 외부", "밥", "ㅂ"),
            ("값 외부", "값", "ㅂ"),
            ("닭 외부", "닭", "ㄱ"),
        ):
            with self.subTest(text=text):
                tokens = self.analyzer.analyze(text)
                self.assertEqual([(item.form, item.tag) for item in tokens], [(left, "NNG"), ("외부", "NNG")])
                result = self.pipeline.run(text)
                matches = _rewrite(result, "ko.liaison.lexical")
                self.assertEqual(len(matches), 1, (text, result.rewrites))
                left_token = _first_syllable(left)
                right_token = _first_syllable("외부")
                expected = compose_syllable(left_token.onset, left_token.vowel)
                expected += " " + compose_syllable(onset, right_token.vowel, right_token.coda)
                self.assertEqual(matches[0].after, expected)

        ng_result = self.pipeline.run("강 외부")
        self.assertEqual(ng_result.surface_pronunciation, "강 외부")
        self.assertFalse(_rewrite(ng_result, "ko.liaison.lexical"))

    def test_formal_particles_endings_pause_and_hard_boundary(self) -> None:
        for text in ("옷이", "밭으로", "먹어요"):
            with self.subTest(text=text):
                result = self.pipeline.run(text)
                self.assertFalse(_rewrite(result, "ko.liaison.lexical"), result.rewrites)
                self.assertTrue(_rewrite(result, "ko.liaison.single"), result.rewrites)

        paused = self.pipeline.run("옷 외부", pause_boundaries=(2,))
        self.assertFalse(_rewrite(paused, "ko.liaison.lexical"), paused.rewrites)

        source = "옷 외부"
        segments = (
            OutputSegment(
                "옷 ", (SourceSpan.from_source(source, 0, 2),), Handler.KOREAN,
                "synthetic boundary probe", boundary_after=Boundary.HARD,
            ),
            OutputSegment(
                "외부", (SourceSpan.from_source(source, 2, 4),), Handler.KOREAN,
                "synthetic boundary probe", boundary_before=Boundary.HARD,
            ),
        )
        hard = korean_engine.pronounce(segments)
        self.assertFalse(_rewrite(hard, "ko.liaison.lexical"), hard.rewrites)


if __name__ == "__main__":
    unittest.main(verbosity=2)
