from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import kiwipiepy
import kiwipiepy_model

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.engine import pronounce
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


def _pair_segments(left: str, right: str, *, hard: bool = False) -> tuple[OutputSegment, ...]:
    """공백을 보존하는 두 한국어 출력 구간을 만든다."""

    text = f"{left} {right}"
    left_end = len(left)
    right_start = left_end + 1
    return (
        OutputSegment(
            left,
            (SourceSpan.from_source(text, 0, left_end),),
            Handler.KOREAN,
            "합성 시험",
            boundary_after=Boundary.HARD if hard else Boundary.WORD,
        ),
        OutputSegment(
            " ",
            (SourceSpan.from_source(text, left_end, right_start),),
            Handler.KOREAN,
            "합성 공백",
        ),
        OutputSegment(
            right,
            (SourceSpan.from_source(text, right_start, len(text)),),
            Handler.KOREAN,
            "합성 시험",
            boundary_before=Boundary.HARD if hard else Boundary.WORD,
        ),
    )


def _single_segment(text: str) -> tuple[OutputSegment, ...]:
    return (
        OutputSegment(
            text,
            (SourceSpan.from_source(text, 0, len(text)),),
            Handler.KOREAN,
            "합성 시험",
        ),
    )


def _pair_tokens(
    left: str,
    right: str,
    left_tag: str,
    right_tag: str,
) -> tuple[AnalysisToken, ...]:
    text = f"{left} {right}"
    right_start = len(left) + 1
    return (
        AnalysisToken(left, left_tag, 0, len(left)),
        AnalysisToken(right, right_tag, right_start, len(text)),
    )


class SyntheticAnalyzer:
    """정확한 provider 요청과 반환 분석을 기록하는 합성 분석기다."""

    def __init__(self, responses: dict[str, tuple[AnalysisToken, ...]]) -> None:
        self.responses_by_text = responses
        self.requests: list[str] = []
        self.responses: list[tuple[AnalysisToken, ...]] = []

    def analyze_components(self, text: str) -> tuple[AnalysisToken, ...]:
        self.requests.append(text)
        response = self.responses_by_text[text]
        self.responses.append(response)
        return response

    def analyze(self, text: str, **kwargs: object) -> tuple[AnalysisToken, ...]:
        raise AssertionError("analyze_components 요청을 예상했습니다")


class RecordingKiwiAnalyzer:
    """실제 Kiwi 결과의 요청과 소비를 기록한다."""

    def __init__(self) -> None:
        self.delegate = KiwiAnalyzer()
        self.requests: list[str] = []
        self.responses: list[tuple[AnalysisToken, ...]] = []

    def analyze_components(self, text: str) -> tuple[AnalysisToken, ...]:
        self.requests.append(text)
        response = self.delegate.analyze_components(text)
        self.responses.append(response)
        return response

    def analyze(self, text: str, **kwargs: object) -> tuple[AnalysisToken, ...]:
        return self.delegate.analyze(text, **kwargs)


def _pronounce_with_provider(
    provider: object,
    segments: tuple[OutputSegment, ...],
    *,
    pause_boundaries: tuple[int, ...] = (),
):
    with patch("g2p_ko.korean.engine.KiwiAnalyzer", return_value=provider):
        return pronounce(segments, pause_boundaries=pause_boundaries)


class WordBoundaryNInsertionTests(unittest.TestCase):
    def test_synthetic_mag_targets_cover_existing_vowel_set_and_codas(self) -> None:
        cases = (
            ("발", "이제"),
            ("밥", "야금"),
            ("밤", "얘기"),
            ("산", "여기"),
            ("옷", "예컨대"),
            ("책", "요즘"),
            ("물", "유기"),
        )
        for left, right in cases:
            with self.subTest(left=left, right=right):
                text = f"{left} {right}"
                response = _pair_tokens(left, right, "NNG", "MAG")
                provider = SyntheticAnalyzer({text: response})
                result = _pronounce_with_provider(provider, _pair_segments(left, right))

                self.assertEqual(provider.requests, [text])
                self.assertEqual(provider.responses, [response])
                self.assertEqual(len(result.text), len(text))
                self.assertEqual(result.text.count(" "), 1)
                self.assertNotEqual(result.text.split(" ")[1][0], right[0])
                self.assertIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_synthetic_mag_uses_liquid_assimilation_after_n_insertion(self) -> None:
        text = "발 이제"
        response = _pair_tokens("발", "이제", "NNG", "MAG")
        provider = SyntheticAnalyzer({text: response})
        result = _pronounce_with_provider(provider, _pair_segments("발", "이제"))

        self.assertEqual(provider.requests, [text])
        self.assertEqual(result.text, "발 리제")
        self.assertEqual(
            {item.rule_id for item in result.rewrites} & {
                "ko.n_insertion.word",
                "ko.liquid.20",
            },
            {"ko.n_insertion.word", "ko.liquid.20"},
        )

    def test_actual_kiwi_mag_analysis_is_requested_and_consumed(self) -> None:
        self.assertEqual(kiwipiepy.__version__, "0.24.1")
        self.assertEqual(kiwipiepy_model.__version__, "0.24.0")
        provider = RecordingKiwiAnalyzer()
        result = _pronounce_with_provider(provider, _pair_segments("발", "이제"))

        self.assertEqual(provider.requests, ["발 이제"])
        self.assertEqual(
            [(token.form, token.tag) for token in provider.responses[0]],
            [("발", "NNG"), ("이제", "MAG")],
        )
        self.assertEqual(result.text, "발 리제")
        self.assertIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_actual_kiwi_lexical_verb_morphemes_preserve_word_insertion(self) -> None:
        cases = (
            (
                "못", "이뤄요.", "몬 니뤄요.", "이뤄", "VV+EF",
                (("이루", "VV"), ("어", "EF")),
            ),
            (
                "못", "이어줘요.", "몬 니어줘요.", "이어", "VV-I+EC",
                (("잇", "VV-I"), ("어", "EC")),
            ),
            (
                "못", "여쭤요.", "몬 녀쭤요.", "여쭤", "VV+EC",
                (("여쭈", "VV"), ("어", "EC")),
            ),
            (
                "못", "일러요.", "몬 닐러요.", "일", "VV-R",
                (("이르", "VV-R"),),
            ),
            (
                "옷", "입어요.", "온 니버요.", "입", "VV-R",
                (("입", "VV-R"),),
            ),
            (
                "못", "일으켜요.", "몬 니르켜요.", "일으켜", "VV+EC",
                (("일으키", "VV"), ("어", "EC")),
            ),
        )
        for left, right, expected, form, tag, morphemes in cases:
            with self.subTest(text=f"{left} {right}"):
                text = f"{left} {right}"
                provider = RecordingKiwiAnalyzer()
                result = _pronounce_with_provider(provider, _pair_segments(left, right))

                self.assertEqual(provider.requests, [text])
                self.assertEqual(result.text, expected)
                self.assertIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})
                target = next(
                    token for token in provider.responses[0]
                    if token.normalized_start == len(left) + 1
                )
                self.assertEqual((target.form, target.tag, target.morphemes), (form, tag, morphemes))

    def test_actual_kiwi_va_irregular_subtype_and_unknown_suffix_contrast(self) -> None:
        text = "때는 이렇게"
        provider = RecordingKiwiAnalyzer()
        result = _pronounce_with_provider(provider, _pair_segments("때는", "이렇게"))

        self.assertEqual(provider.requests, [text])
        target = next(token for token in provider.responses[0] if token.normalized_start == 3)
        self.assertEqual((target.form, target.tag, target.morphemes), ("이렇", "VA-I", (("이렇", "VA-I"),)))
        self.assertEqual(result.text, "때는 니러케")
        self.assertIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

        unsupported = "발 이제"
        response = (
            AnalysisToken("발", "NNG", 0, 1),
            AnalysisToken("이제", "VA-X", 2, 4, (("이제", "VA-X"),)),
        )
        synthetic = SyntheticAnalyzer({unsupported: response})
        rejected = _pronounce_with_provider(synthetic, _pair_segments("발", "이제"))
        self.assertEqual(rejected.text, unsupported)
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in rejected.rewrites})

    def test_actual_kiwi_copula_and_merged_copula_ending_are_not_lexical_verbs(self) -> None:
        provider = RecordingKiwiAnalyzer()
        actual = _pronounce_with_provider(provider, _pair_segments("모양", "이에요"))

        self.assertEqual(provider.requests, ["모양 이에요"])
        self.assertIn(("이", "VCP"), [(token.form, token.tag) for token in provider.responses[0]])
        self.assertEqual(actual.text, "모양 이에요")
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in actual.rewrites})

        text = "모양 이에요"
        merged = (
            AnalysisToken("모양", "NNG", 0, 2),
            AnalysisToken("이에요", "VCP+EF", 3, 6, (("이", "VCP"), ("에요", "EF"))),
        )
        provider = SyntheticAnalyzer({text: merged})
        result = _pronounce_with_provider(provider, _pair_segments("모양", "이에요"))

        self.assertEqual(provider.requests, [text])
        self.assertEqual(provider.responses, [merged])
        self.assertEqual(result.text, text)
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_existing_noun_pronoun_and_lexical_verb_targets_remain_enabled(self) -> None:
        for right_tag in ("NNG", "NP", "VV", "VA", "VX"):
            with self.subTest(right_tag=right_tag):
                text = "발 이제"
                response = _pair_tokens("발", "이제", "NNG", right_tag)
                provider = SyntheticAnalyzer({text: response})
                result = _pronounce_with_provider(provider, _pair_segments("발", "이제"))

                self.assertEqual(provider.requests, [text])
                self.assertIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_mixed_grammatical_and_unknown_tags_do_not_license_word_boundary(self) -> None:
        for right_tag in (
            "MAG+EF",
            "MAG+JKS",
            "NNG+JKS",
            "NP+JX",
            "VV+EP+EF",
            "VV+EF",
            "VV+ETM",
            "VCP",
            "VCP+EF",
            "VCN+EF",
            "EF+VV",
            "NNUNKNOWN",
            "MAG+",
            "UNKNOWN",
        ):
            with self.subTest(right_tag=right_tag):
                text = "발 이제"
                response = _pair_tokens("발", "이제", "NNG", right_tag)
                provider = SyntheticAnalyzer({text: response})
                result = _pronounce_with_provider(provider, _pair_segments("발", "이제"))

                self.assertEqual(provider.requests, [text])
                self.assertEqual(result.text, text)
                self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_nr_exclusions_are_preserved(self) -> None:
        text = "삼 이제"
        response = _pair_tokens("삼", "이제", "NR", "MAG")
        provider = SyntheticAnalyzer({text: response})
        result = _pronounce_with_provider(provider, _pair_segments("삼", "이제"))

        self.assertEqual(provider.requests, [text])
        self.assertEqual(result.text, text)
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in result.rewrites})

    def test_analysis_failure_and_unknown_tags_leave_input_unmodified(self) -> None:
        text = "발 이제"
        failed_provider = SyntheticAnalyzer({text: ()})
        failed = _pronounce_with_provider(failed_provider, _pair_segments("발", "이제"))

        self.assertEqual(failed_provider.requests, [text])
        self.assertEqual(failed.text, text)
        self.assertIn("analyzer_failed", {item.code for item in failed.diagnostics})
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in failed.rewrites})

    def test_explicit_pause_and_hard_boundary_block_word_n_insertion(self) -> None:
        text = "발 이제"
        response = _pair_tokens("발", "이제", "NNG", "MAG")

        pause_provider = SyntheticAnalyzer({text: response})
        paused = _pronounce_with_provider(
            pause_provider,
            _pair_segments("발", "이제"),
            pause_boundaries=(2,),
        )
        self.assertEqual(pause_provider.requests, [text])
        self.assertEqual(paused.text, text)
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in paused.rewrites})

        hard_provider = SyntheticAnalyzer({"이제": (AnalysisToken("이제", "MAG", 0, 2),)})
        hard = _pronounce_with_provider(
            hard_provider,
            _pair_segments("발", "이제", hard=True),
        )
        self.assertEqual(hard_provider.requests, ["이제"])
        self.assertNotIn(text, hard_provider.requests)
        self.assertEqual(hard.text, text)
        self.assertNotIn("ko.n_insertion.word", {item.rule_id for item in hard.rewrites})

    def test_existing_declared_compound_rule_is_unchanged(self) -> None:
        text = "담요"
        response = (AnalysisToken("담요", "NNG", 0, 2),)
        provider = SyntheticAnalyzer({text: response})
        result = _pronounce_with_provider(provider, _single_segment(text))

        self.assertEqual(provider.requests, [text])
        self.assertEqual(result.text, "담뇨")
        self.assertIn("ko.n_insertion.compound", {item.rule_id for item in result.rewrites})


if __name__ == "__main__":
    unittest.main()
