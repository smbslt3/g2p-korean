"""평가의 의미 선택을 위한 자체 작성 합성 검사다."""

import importlib.metadata
import unittest

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.semantic_policy import (
    SemanticToken,
    SenseEvidence,
    SenseSelection,
    _decide,
    select_senses,
)


def _token(form, tag, start, end, morphemes=None):
    return SemanticToken(
        form,
        tag,
        start,
        end,
        tuple(morphemes or ((form, tag),)),
    )


class PyeonggaSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = KiwiAnalyzer()
        cls.g2p = G2P()

    def _provider(self, text):
        analysis = self.analyzer.analyze(text, split_complex=True)
        tokens = tuple(
            SemanticToken(
                token.form,
                token.tag,
                token.normalized_start,
                token.normalized_end,
                token.morphemes,
            )
            for token in analysis
        )
        return analysis, select_senses(text, tokens)

    def test_runtime_versions_are_current_approved_pair(self):
        self.assertEqual(importlib.metadata.version("kiwipiepy"), "0.24.1")
        self.assertEqual(importlib.metadata.version("kiwipiepy-model"), "0.24.0")

    def test_provider_analysis_and_g2p_output(self):
        cases = (
            ("평가는 평집이다.", "pyeongga.house", "평가는 평지비다."),
            ("평가는 보통의 값이다.", "pyeongga.parity", "평까는 보통에 갑씨다."),
            ("평가는 가치 판단이다.", "pyeongga.appraisal", "평까는 가치 판다니다."),
        )
        for text, expected_sense, expected_output in cases:
            with self.subTest(text=text):
                analysis, choices = self._provider(text)
                self.assertEqual(choices[0].sense_id, expected_sense)
                self.assertTrue(any(token.form == "평집" and token.tag == "NNP" for token in analysis) or text != "평가는 평집이다.")
                self.assertEqual(self.g2p.convert(text).surface_pronunciation, expected_output)

    def test_registered_proper_noun_alias_has_its_declared_owner_pos(self):
        text = "평가는 평집이다."
        analysis = self.analyzer.analyze(text)
        self.assertTrue(any(token.form == "평집" and token.tag == "NNP" for token in analysis))
        tokens = tuple(
            SemanticToken(token.form, token.tag, token.normalized_start, token.normalized_end, token.morphemes)
            for token in analysis
        )
        self.assertEqual(select_senses(text, tokens)[0].sense_id, "pyeongga.house")

    def test_supplied_normal_analysis_selects_three_declared_types(self):
        cases = (
            (
                "평가는 평집이다.",
                (
                    _token("평가", "NNG", 0, 2), _token("는", "JX", 2, 3),
                    _token("평집", "NNP", 4, 6), _token("이", "VCP", 6, 7),
                    _token("다", "EF", 7, 8), _token(".", "SF", 8, 9),
                ),
                "pyeongga.house",
            ),
            (
                "평가는 보통의 값이다.",
                (
                    _token("평가", "NNG", 0, 2), _token("는", "JX", 2, 3),
                    _token("보통", "NNG", 4, 6), _token("의", "JKG", 6, 7),
                    _token("값", "NNG", 8, 9), _token("이", "VCP", 9, 10),
                    _token("다", "EF", 10, 11), _token(".", "SF", 11, 12),
                ),
                "pyeongga.parity",
            ),
            (
                "평가는 가치 판단이다.",
                (
                    _token("평가", "NNG", 0, 2), _token("는", "JX", 2, 3),
                    _token("가치", "NNG", 4, 6), _token("판단", "NNG", 7, 9),
                    _token("이", "VCP", 9, 10), _token("다", "EF", 10, 11),
                    _token(".", "SF", 11, 12),
                ),
                "pyeongga.appraisal",
            ),
        )
        for text, tokens, expected_sense in cases:
            with self.subTest(text=text):
                self.assertEqual(select_senses(text, tokens)[0].sense_id, expected_sense)

    def test_bare_owner_title_negation_and_unrelated_mentions_abstain(self):
        cases = (
            "평가",
            "평가의 평집",
            "『평가』",
            "평가는 값이다.",
            "평가는 평집이 아니다.",
            "평가는 옆에 평집이 있다.",
        )
        for text in cases:
            with self.subTest(text=text):
                _, choices = self._provider(text)
                self.assertTrue(choices)
                self.assertTrue(all(choice.sense_id is None for choice in choices))

    def test_repeated_occurrences_and_hard_boundary_stay_local(self):
        text = "평가는 평집이다. 평가는 값이다."
        _, choices = self._provider(text)
        self.assertEqual([choice.sense_id for choice in choices], ["pyeongga.house", None])

        isolated = "평가는 평집이다."
        analysis = self.analyzer.analyze(isolated, split_complex=True)
        tokens = tuple(
            SemanticToken(token.form, token.tag, token.normalized_start, token.normalized_end, token.morphemes)
            for token in analysis
        )
        choices = select_senses(isolated, tokens, hard_boundaries={4})
        self.assertEqual(choices[0].sense_id, None)

    def test_coordinated_copular_types_conflict_in_either_order(self):
        for text in (
            "평가는 평집이면서 가치 판단이다.",
            "평가는 가치 판단이면서 평집이다.",
            "평가는 평집이고 가치 판단이다.",
            "평가는 가치 판단이고 평집이다.",
        ):
            with self.subTest(text=text):
                _, choices = self._provider(text)
                self.assertEqual(len(choices), 1)
                self.assertIsNone(choices[0].sense_id)
                self.assertEqual(choices[0].reason, "conflicting_evidence")

    def test_explicit_new_topic_replaces_carried_copular_topic(self):
        text = "평가는 평집이면서 평가는 가치 판단이다."
        _, choices = self._provider(text)
        self.assertEqual([choice.sense_id for choice in choices], ["pyeongga.house", "pyeongga.appraisal"])

    def test_source_owned_derivation_requires_adjacent_root_and_xsv_provenance(self):
        text = "평가했"
        tokens = (
            _token("평가", "NNG", 0, 2),
            _token("했", "XSV+EP", 2, 3, (("하", "XSV"), ("었", "EP"))),
        )
        choice = select_senses(text, tokens)[0]
        self.assertEqual(choice.sense_id, "pyeongga.appraisal")
        self.assertTrue(any(item.relation == "source_owned_nominal_derivation" for item in choice.evidence))
        self.assertEqual(self.g2p.convert("평가하다.").surface_pronunciation, "평까하다.")

        separated = "평가 했"
        tokens = (
            _token("평가", "NNG", 0, 2),
            _token("했", "XSV+EP", 3, 4, (("하", "XSV"), ("었", "EP"))),
        )
        self.assertIsNone(select_senses(separated, tokens)[0].sense_id)

        wrong_tag = "평가했"
        tokens = (
            _token("평가", "NNG", 0, 2),
            _token("했", "VV+EP", 2, 3, (("하", "VV"), ("었", "EP"))),
        )
        self.assertIsNone(select_senses(wrong_tag, tokens)[0].sense_id)

    def test_conflicting_same_occurrence_types_abstain_independent_of_order(self):
        target = SemanticToken("평가", "NNG", 0, 2)
        evidence = (
            SenseEvidence("copular_category", 0, 2, 4, 6, "dwelling_house"),
            SenseEvidence("copular_category", 0, 2, 7, 9, "ordinary_price"),
        )
        forward = _decide(target, evidence, False)
        reverse = _decide(target, tuple(reversed(evidence)), False)
        self.assertIsInstance(forward, SenseSelection)
        self.assertIsNone(forward.sense_id)
        self.assertEqual(forward.reason, "conflicting_evidence")
        self.assertEqual((reverse.sense_id, reverse.reason), (forward.sense_id, forward.reason))


if __name__ == "__main__":
    unittest.main()
