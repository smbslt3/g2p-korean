"""초기 동형어의 직접 유형 정의와 제목·혼합 유형의 보수적 대조를 검증한다."""
import json
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


_CASES = json.loads((Path(__file__).parent / 'fixtures' / 'korean_original_family_categories.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', _CASES, ids=lambda case: case['id'])
def test_original_family_category_transfer(case):
    tokens = tuple(SemanticToken(**token) for token in case['tokens'])
    choices = select_senses(case['text'], tokens, frozenset(case['hard_boundaries']))
    assert len(choices) == len(case['targets'])
    for target in case['targets']:
        choice, = [item for item in choices if (item.start, item.end) == (target['start'], target['end'])]
        assert choice.sense_id == target['sense_id']
        for evidence in choice.evidence:
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case['text'])
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)
