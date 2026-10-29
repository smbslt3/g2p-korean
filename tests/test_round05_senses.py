"""개수ㆍ말발 의미 선택의 범위 있는 검증."""

from pathlib import Path
import sys
import unittest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

import kiwipiepy
from kiwipiepy import Kiwi

from g2p_ko import G2P
from g2p_ko.korean.semantic_policy import (
    SemanticToken,
    SenseEvidence,
    _decide,
    select_senses,
)


class SensePropertyTests(unittest.TestCase):
    """Kiwi 실제 분석과 전달 형태소를 대상으로 새 의미 관계를 확인한다."""

    @classmethod
    def setUpClass(cls):
        cls.kiwi = Kiwi()
        cls.g2p = G2P()

    def tokens(self, text):
        """Kiwi 실제 경계와 품사를 의미 선택기에 전달한다."""
        return tuple(
            SemanticToken(token.form, token.tag, token.start, token.start + token.len)
            for token in self.kiwi.tokenize(text)
        )

    def choices(self, text, hard_boundaries=frozenset()):
        return select_senses(text, self.tokens(text), hard_boundaries)

    def one(self, text, spelling):
        matches = [choice for choice in self.choices(text) if choice.spelling == spelling]
        self.assertEqual(1, len(matches), text)
        return matches[0]

    def assert_selected(self, text, spelling, sense_id):
        choice = self.one(text, spelling)
        self.assertEqual(sense_id, choice.sense_id, text)
        self.assertEqual("selected", choice.reason, text)
        self.assertTrue(choice.evidence, text)
        return choice

    def assert_unresolved(self, text, spelling):
        choice = self.one(text, spelling)
        self.assertIsNone(choice.sense_id, text)
        self.assertIn(choice.reason, {"insufficient_evidence", "unsupported_modifier", "unsupported_relation", "conflicting_evidence"}, text)
        return choice

    def test_actual_kiwi_context_selects_each_supplied_sense(self):
        """실제 Kiwi 0.24.1 분석으로 의미별 선택과 파생형을 확인한다."""
        self.assertEqual("0.24.1", kiwipiepy.__version__)
        self.assert_selected("방은 개수가 얼마나 있나요?", "개수", "gaesu.count_quantity")
        self.assert_selected("부품의 개수를 세었다", "개수", "gaesu.count_quantity")
        self.assert_selected("건물을 개수했다", "개수", "gaesu.renovation")
        self.assert_selected("건물이 개수되었다", "개수", "gaesu.renovation")
        self.assert_selected("그는 재치와 말발도 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("개수는 개숫물이다", "개수", "gaesu.washing_water")
        self.assert_selected("개수는 갑옷의 소매이다", "개수", "gaesu.armour_sleeve")
        self.assert_selected("말발은 언변이다", "말발", "malbal.speech_ability")
        self.assert_selected("말발은 첨족이다", "말발", "malbal.equinus")

    def test_supplied_split_morphology_is_recognized(self):
        """표면 토큰 하나와 분리 전달된 개ㆍ수 형태소가 같은 관계를 만든다."""
        text = "부품의 개수를 세었다"
        tokens = (
            SemanticToken("부품", "NNG", 0, 2),
            SemanticToken("의", "JKG", 2, 3),
            SemanticToken("개", "NNG", 4, 5),
            SemanticToken("수", "NNG", 5, 6),
            SemanticToken("를", "JKO", 6, 7),
            SemanticToken("세", "VV", 8, 9),
            SemanticToken("었", "EP", 9, 10),
            SemanticToken("다", "EF", 10, 11),
        )
        choice = next(item for item in select_senses(text, tokens) if item.spelling == "개수")
        self.assertEqual("gaesu.count_quantity", choice.sense_id)
        self.assertEqual("selected", choice.reason)
        self.assertTrue(any(item.semantic_class == "count_quantity" for item in choice.evidence))

    def test_selected_features_drive_only_their_tensed_senses(self):
        """선택된 경계만 경음화를 내고 명시된 평음 뜻은 보존한다."""
        count = self.g2p.convert("방은 개수가 얼마나 있나요?").surface_pronunciation
        renovation = self.g2p.convert("건물을 개수했다").surface_pronunciation
        washing_water = self.g2p.convert("개수는 개숫물이다").surface_pronunciation
        armour_sleeve = self.g2p.convert("개수는 갑옷의 소매이다").surface_pronunciation
        speech = self.g2p.convert("그는 재치와 말발도 가지고 있다").surface_pronunciation
        equinus = self.g2p.convert("말발은 첨족이다").surface_pronunciation
        self.assertIn("개쑤", count)
        self.assertIn("개수", renovation)
        self.assertNotIn("개쑤", renovation)
        self.assertIn("개수는", washing_water)
        self.assertNotIn("개쑤", washing_water)
        self.assertIn("개수는", armour_sleeve)
        self.assertNotIn("개쑤", armour_sleeve)
        self.assertIn("말빨", speech)
        self.assertNotIn("말빨", equinus)

    def test_quantity_relations_require_their_syntax(self):
        """화제ㆍ속격 소유ㆍ수량 서술만으로 수량 뜻을 연결한다."""
        self.assert_selected("부품의 개수는 얼마나 되나요?", "개수", "gaesu.count_quantity")
        self.assert_selected("부품의 개수가 얼마나 있나요?", "개수", "gaesu.count_quantity")
        self.assert_selected("부품의 개수가 많다", "개수", "gaesu.count_quantity")
        self.assert_selected("부품의 개수를 세지 않았다", "개수", "gaesu.count_quantity")
        self.assert_unresolved("개수", "개수")
        self.assert_unresolved("개수는 얼마나 있나요?", "개수")
        self.assert_unresolved("건물은 개수가 얼마나 필요한가요?", "개수")
        self.assert_unresolved("집의 개수는 얼마나 필요한가요?", "개수")
        self.assert_unresolved("건물 개수 공사를 진행했다", "개수")
        self.assertNotIn("개쑤", self.g2p.convert("개수").surface_pronunciation)

    def test_coordinated_ability_scope_is_local_and_coherent(self):
        """다른 실제 능력과 같은 소유 논항의 병렬만 말발 언변 뜻을 지지한다."""
        self.assert_selected("그는 재치와 말솜씨와 말발도 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("그는 재치와 말발을 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("그는 재치와 말발을 보유하고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("뛰어난 재치와 말발도 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("누구에게도 뒤지지 않는 재치와 말발도 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("동료 정도 되는 재치와 말발도 가지고 있다", "말발", "malbal.speech_ability")
        self.assert_selected("뛰어난 재치와 말발도 가지고 있어야 한다", "말발", "malbal.speech_ability")
        self.assert_unresolved("그는 말발을 가지고 있다", "말발")
        self.assert_unresolved("의사는 말발을 가지고 있다", "말발")
        self.assert_unresolved("가격과 말발도 가지고 있다", "말발")
        self.assert_unresolved("재치가 있다. 그는 말발을 가지고 있다", "말발")
        self.assert_unresolved("그는 재치와 기지와 말발도 가지고 있다", "말발")
        self.assert_unresolved("희귀한 재치와 말발도 가지고 있다", "말발")
        rejected = self.assert_unresolved("그는 재치가 아닌 말발도 가지고 있다", "말발")
        self.assertEqual("unsupported_modifier", rejected.reason)
        self.assert_unresolved("그는 재치와 말발과 망치도 가지고 있다", "말발")
        choices = [item for item in self.choices("그는 재치와 말발도 가지고 있다. 말발은 첨족이다") if item.spelling == "말발"]
        self.assertEqual(["malbal.speech_ability", "malbal.equinus"], [item.sense_id for item in choices])
        self.assert_unresolved("말발은 첨족이 아니다", "말발")
        contradiction = self.assert_unresolved("그는 첨족인 말발과 재치도 가지고 있다", "말발")
        self.assertEqual("conflicting_evidence", contradiction.reason)

    def test_conflicting_explicit_types_defer(self):
        """상충 정의와 대상별 상충 근거는 특정 뜻으로 밀어붙이지 않는다."""
        choice = self.assert_unresolved("개수는 수량이며 개숫물이다", "개수")
        self.assertTrue(any(item.semantic_class == "unresolved_relation" for item in choice.evidence))
        target = SemanticToken("개수", "NNG", 0, 2)
        evidence = (
            SenseEvidence("explicit_definition", 0, 2, 3, 6, "count_quantity"),
            SenseEvidence("explicit_definition", 0, 2, 7, 10, "washing_water"),
        )
        deferred = _decide(target, evidence, False)
        self.assertIsNone(deferred.sense_id)
        self.assertEqual("conflicting_evidence", deferred.reason)

    def test_clause_quote_hard_and_pause_boundaries(self):
        """절ㆍ인용ㆍHARD 경계는 관계를 닫고 pause API는 선택 흐름을 유지한다."""
        text = "방은 개수가 얼마나 있나요?"
        self.assert_selected(text, "개수", "gaesu.count_quantity")
        split = next(item for item in select_senses(text, self.tokens(text), frozenset({2})) if item.spelling == "개수")
        self.assertIsNone(split.sense_id)
        self.assertEqual("insufficient_evidence", split.reason)
        self.assert_unresolved("‘재치’와 말발도 가지고 있다", "말발")
        plain = self.assert_unresolved("재치가 있다. 말발을 가지고 있다", "말발")
        self.assertEqual("insufficient_evidence", plain.reason)

        without_pause = self.g2p.convert(text).surface_pronunciation
        with_pause = self.g2p.convert(text, pause_boundaries=(2,)).surface_pronunciation
        self.assertEqual(without_pause, with_pause)
        self.assertIn("개쑤", with_pause)


if __name__ == "__main__":
    unittest.main()
