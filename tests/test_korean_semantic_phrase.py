"""명사 핵어의 실제 유형과 중첩 인용의 국소 관계를 검증한다."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken,select_senses

_DATA=json.loads((Path(__file__).parent/'fixtures/korean_semantic_phrase.json').read_text(encoding='utf-8'))
_CASES=_DATA['cases']
_HARD_CASES=[c for c in _CASES if c['id'] in _DATA['hard_cut_case_ids']]


def _tokens(case):
    return tuple(SemanticToken(**t) for t in case['tokens'])


@pytest.mark.parametrize('case',_CASES,ids=lambda c:c['id'])
def test_nominal_head_identity_and_nested_quote_scope(case):
    choices=select_senses(case['text'],_tokens(case),frozenset(case['hard_boundaries']))
    assert len(choices)==len(case['targets'])
    for target in case['targets']:
        choice,=[c for c in choices if (c.start,c.end)==(target['start'],target['end'])]
        assert choice.sense_id in target.get('allowed_sense_ids',[target['sense_id']])
        for start,end in target.get('forbidden_evidence_anchor_spans',[]):
            assert not any(e.anchor_start < end and e.anchor_end > start
                           and e.semantic_class in target['forbidden_evidence_semantic_classes'] for e in choice.evidence)
        for e in choice.evidence:
            assert 0 <= e.anchor_start <= e.anchor_end <= len(case['text'])
            assert (e.target_start,e.target_end)==(choice.start,choice.end)


def _shift_back(choice,offset):
    evidence=tuple(replace(e,target_start=e.target_start-offset,target_end=e.target_end-offset,
                           anchor_start=e.anchor_start-offset,anchor_end=e.anchor_end-offset) for e in choice.evidence)
    return replace(choice,start=choice.start-offset,end=choice.end-offset,evidence=evidence)


@pytest.mark.parametrize('case',_CASES,ids=lambda c:c['id'])
def test_repeated_input_preserves_each_local_scope(case):
    tokens=_tokens(case);original=select_senses(case['text'],tokens,frozenset(case['hard_boundaries']))
    offset=len(case['text'])+1
    second=tuple(replace(t,start=t.start+offset,end=t.end+offset) for t in tokens)
    cuts=frozenset(case['hard_boundaries']+[x+offset for x in case['hard_boundaries']])
    result=select_senses(case['text']+' '+case['text'],tokens+second,cuts)
    assert tuple(c for c in result if c.start < offset)==original
    assert tuple(_shift_back(c,offset) for c in result if c.start >= offset)==original


@pytest.mark.parametrize('case',_HARD_CASES,ids=lambda c:c['id'])
def test_hard_cut_does_not_reconstruct_a_quote_relation(case):
    target=case['targets'][0]
    choices=select_senses(case['text'],_tokens(case),frozenset({target['start']}))
    choice,=[c for c in choices if (c.start,c.end)==(target['start'],target['end'])]
    assert choice.sense_id is None
