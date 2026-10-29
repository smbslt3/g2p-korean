"""독립 합성 의미 관계의 수용 범위와 논항·경계 가드를 검증한다."""
import json
from pathlib import Path
import pytest
from g2p_ko.korean.semantic_policy import SemanticToken, select_senses

CASES = json.loads((Path(__file__).parent / "fixtures/round10_quantity_ability.json").read_text(encoding="utf-8"))["cases"]

@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_source_owned_quantity_and_speech_definition(case):
    tokens = tuple(SemanticToken(**token) for token in case["tokens"])
    selections = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    assert [selection.sense_id for selection in selections] == case["expected"]
    for selection in selections:
        for evidence in selection.evidence:
            assert (evidence.target_start, evidence.target_end) == (selection.start, selection.end)
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
