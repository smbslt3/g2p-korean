"""독립 제공 분석에서 명사구와 관형절의 실제 소유 관계를 확인한다."""
import json
from pathlib import Path
import pytest
from g2p_ko.korean.semantic_policy import SemanticToken, select_senses

CASES = json.loads((Path(__file__).parent / "fixtures/round12_clause_ownership.json").read_text(encoding="utf-8"))["cases"]

@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_clause_and_nominal_ownership(case):
    selected = select_senses(case["text"], tuple(SemanticToken(**token) for token in case["tokens"]), frozenset(case["hard"]))
    assert [choice.sense_id for choice in selected] == case["expected"]
    for choice in selected:
        for evidence in choice.evidence:
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
