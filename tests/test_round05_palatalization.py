from __future__ import annotations

import unittest
from unittest.mock import patch

from g2p_ko.korean.engine import pronounce
from g2p_ko.model import (
    AnalysisToken,
    Boundary,
    Handler,
    OutputSegment,
    RewriteStage,
    SourceSpan,
)


def _token(form: str, tag: str, start: int, morphemes=()) -> AnalysisToken:
    return AnalysisToken(form, tag, start, start + len(form), tuple(morphemes))


def _segment(
    text: str,
    start: int = 0,
    *,
    source_length: int | None = None,
    before=Boundary.WORD,
    after=Boundary.WORD,
) -> OutputSegment:
    length = start + len(text) if source_length is None else source_length
    return OutputSegment(
        text,
        (SourceSpan(start, start + len(text), text, length),),
        Handler.KOREAN,
        "focused-test",
        boundary_before=before,
        boundary_after=after,
    )


class _FixedAnalyzer:
    def __init__(self, by_text):
        self.by_text = by_text
        self.calls: list[str] = []

    def analyze_components(self, text: str):
        self.calls.append(text)
        return tuple(self.by_text[text])

    def analyze(self, text: str):
        return self.analyze_components(text)


class PalatalizationTests(unittest.TestCase):
    def run_pronunciation(self, text: str, tokens, *, pauses=(), segments=None):
        analyzer = _FixedAnalyzer({text: tuple(tokens)})
        if segments is None:
            segments = (_segment(text),)
        with patch("g2p_ko.korean.engine.KiwiAnalyzer", side_effect=lambda: analyzer):
            result = pronounce(segments, pause_boundaries=pauses)
        return result, analyzer

    def assert_palatalized(self, text: str, tokens, expected: str):
        result, _ = self.run_pronunciation(text, tokens)
        self.assertEqual(result.text, expected)
        rewrites = [item for item in result.rewrites if item.rule_id == "ko.palatalization"]
        self.assertTrue(rewrites)
        return rewrites

    def test_exact_nominal_owner_whole_nng_and_nnp(self):
        for tag in ("NNG", "NNP"):
            with self.subTest(tag=tag):
                rewrites = self.assert_palatalized(
                    "붙임머리", (_token("붙임머리", tag, 0),), "부침머리",
                )
                self.assertEqual(rewrites[0].before, "붙임")
                self.assertEqual(rewrites[0].after, "부침")
                self.assertEqual(rewrites[0].stage, RewriteStage.PHONOLOGY)
                self.assertEqual(
                    tuple((span.start, span.end, span.surface) for span in rewrites[0].source_spans),
                    ((0, 1, "붙"), (1, 2, "임")),
                )

    def test_pinned_kiwi_actual_nominal_and_particle_analysis(self):
        import kiwipiepy

        self.assertEqual(kiwipiepy.__version__, "0.24.1")
        for text, expected in (("붙임머리", "부침머리"), ("붙임머리가", "부침머리가")):
            with self.subTest(text=text):
                segment = _segment(text)
                result = pronounce((segment,))
                self.assertEqual(result.text, expected)
                self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_exact_nominal_owner_split_nng_and_attached_particles(self):
        split = (_token("붙임", "NNG", 0), _token("머리", "NNG", 2))
        self.assert_palatalized("붙임머리", split, "부침머리")

        for particle, tag in (("가", "JKS"), ("는", "JX"), ("를", "JKO")):
            with self.subTest(particle=particle):
                text = "붙임머리" + particle
                tokens = (_token("붙임머리", "NNG", 0), _token(particle, tag, 4))
                self.assert_palatalized(text, tokens, "부침머리" + particle)

        text = "붙임머리가"
        combined = _token(
            text,
            "NNG+JKS",
            0,
            (("붙임머리", "NNG"), ("가", "JKS")),
        )
        self.assert_palatalized(text, (combined,), "부침머리가")

    def test_exact_owner_is_matched_at_its_validated_source_range(self):
        text = "말 붙임머리"
        tokens = (_token("말", "NNG", 0), _token("붙임머리", "NNG", 2))
        result, _ = self.run_pronunciation(text, tokens)
        self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))
        rewrite = next(item for item in result.rewrites if item.rule_id == "ko.palatalization")
        self.assertEqual(tuple(span.start for span in rewrite.source_spans), (2, 3))

    def test_registered_prefix_boundaries_and_longer_prefix_owner(self):
        cases = ("미닫이", "여닫이", "땀받이", "벼훑이", "해돋이", "맏이", "같이")
        for word in cases:
            with self.subTest(word=word):
                result, _ = self.run_pronunciation(word, (_token(word, "NNG", 0),))
                self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

        longer = "미닫이문"
        result, _ = self.run_pronunciation(longer, (_token(longer, "NNG", 0),))
        self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_registered_suffix_boundary_is_end_anchored(self):
        for word in ("붙이", "덧붙이"):
            with self.subTest(word=word):
                result, _ = self.run_pronunciation(word, (_token(word, "NNG", 0),))
                self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

        unsupported_tail = "붙이집"
        result, _ = self.run_pronunciation(
            unsupported_tail, (_token(unsupported_tail, "NNG", 0),),
        )
        self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_unlicensed_and_longer_nominal_owners_do_not_gain_property(self):
        cases = (
            ("붙임옷", (_token("붙임옷", "NNG", 0),)),
            ("붙임머리집", (_token("붙임머리집", "NNG", 0),)),
            ("붙임머리집", (_token("붙임머리집", "NNP", 0),)),
            (
                "붙임머리집",
                (_token("붙임머리", "NNG", 0), _token("집", "NNG", 4)),
            ),
            ("가닫이", (_token("가닫이", "NNG", 0),)),
        )
        for text, tokens in cases:
            with self.subTest(text=text):
                result, _ = self.run_pronunciation(text, tokens)
                self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_nominal_owner_rejects_fake_morphemes_and_unsupported_tags(self):
        analyses = (
            (_token("붙임머리", "ETN", 0),),
            (_token("붙임머리", "NNG+JKS", 0),),
            (_token("붙임머리", "NNG", 0, (("붙", "VV"), ("임", "ETN"), ("머리", "NNG"))),),
        )
        for tokens in analyses:
            with self.subTest(tokens=tokens):
                result, _ = self.run_pronunciation("붙임머리", tokens)
                self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_ambiguous_context_and_bat_iran_jc_noun_distinction(self):
        unknown = "곧이어"
        unknown_tokens = (_token("곧", "MAG", 0), _token("이어", "VV+EC", 1))
        result, _ = self.run_pronunciation(unknown, unknown_tokens)
        self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

        noun, _ = self.run_pronunciation("밭이랑", (_token("밭이랑", "NNG", 0),))
        conjunction, _ = self.run_pronunciation(
            "밭이랑", (_token("밭", "NNG", 0), _token("이랑", "JC", 1)),
        )
        self.assertEqual(noun.text, "반니랑")
        self.assertTrue(any(item.rule_id == "ko.palatalization" for item in conjunction.rewrites))
        self.assertNotEqual(noun.text, conjunction.text)

    def test_formal_suffix_and_verb_derived_rules_remain_active(self):
        formal = "굳히다"
        formal_tokens = (
            _token("굳", "VV", 0),
            _token("히", "XSV", 1),
            _token("다", "EF", 2),
        )
        self.assert_palatalized(formal, formal_tokens, "구치다")

    def test_opaque_verb_uses_verified_canonical_lexical_boundary(self):
        # 통짜 동사는 정확한 정준 소유자의 독립 고유 경계 사실로 처리한다.
        # 원래 구개음화 기대를 유지하며 형식 접미사 신원은 만들지 않는다.
        derived = "곧이듣다"
        derived_tokens = (
            _token("곧이듣", "VV", 0),
            _token("다", "EF", 3),
        )
        result, _ = self.run_pronunciation(derived, derived_tokens)
        self.assertTrue(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_pause_blocks_crossing_boundary_and_keeps_other_candidate(self):
        text = "붙임머리 같이"
        tokens = (
            _token("붙임머리", "NNG", 0),
            _token("같이", "NNG", 5),
        )
        result, analyzer = self.run_pronunciation(text, tokens, pauses=(1,))
        self.assertEqual(analyzer.calls, [text])
        rewrites = [item for item in result.rewrites if item.rule_id == "ko.palatalization"]
        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0].before, "같이")
        self.assertEqual(rewrites[0].after, "가치")

    def test_hard_punctuation_and_quote_boundaries_stop_candidate_collection(self):
        for separator in (".", "’"):
            with self.subTest(separator=separator):
                text = "붙" + separator + "임머리"
                segments = (
                    _segment("붙", 0, source_length=len(text), after=Boundary.HARD),
                    OutputSegment(
                        separator,
                        (SourceSpan(1, 2, separator, len(text)),),
                        Handler.PROTECTED,
                        "boundary-test",
                        boundary_before=Boundary.HARD,
                        boundary_after=Boundary.HARD,
                    ),
                    _segment("임머리", 2, source_length=len(text), before=Boundary.HARD),
                )
                analyzer = _FixedAnalyzer({"붙": (), "임머리": ()})
                with patch("g2p_ko.korean.engine.KiwiAnalyzer", side_effect=lambda: analyzer):
                    result = pronounce(segments)
                self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))

    def test_pause_at_exact_boundary_retains_analysis_but_blocks_change(self):
        text = "붙임머리"
        result, analyzer = self.run_pronunciation(
            text, (_token(text, "NNG", 0),), pauses=(1,),
        )
        self.assertEqual(analyzer.calls, [text])
        self.assertFalse(any(item.rule_id == "ko.palatalization" for item in result.rewrites))


if __name__ == "__main__":
    unittest.main()
