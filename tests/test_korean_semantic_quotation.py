"""정상 분석의 인용 정의와 정확한 약수 개수 및 출현 경계를 검증한다."""
from dataclasses import replace
import json
import importlib.util as _quote_import
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


# 같은 테스트 폴더의 한정된 보조 코드만 읽는다. output 자료에 의존하지 않는다.
_QUOTE_SPEC = _quote_import.spec_from_file_location("quote_repetition_contract_test_support", Path(__file__).with_name("_quote_repetition_contract.py"))
_QUOTE_CONTRACT = _quote_import.module_from_spec(_QUOTE_SPEC)
_QUOTE_SPEC.loader.exec_module(_QUOTE_CONTRACT)


_DATA=json.loads((Path(__file__).parent / "fixtures/korean_semantic_quotation.json").read_text(encoding="utf-8"))
_CASES=_DATA["cases"]
_LABEL_CASES=json.loads((Path(__file__).parent / "fixtures/korean_semantic_label_recording.json").read_text(encoding="utf-8"))["cases"]


def _tokens(case):
    return tuple(SemanticToken(**token) for token in case["tokens"])


@pytest.mark.parametrize("case",_CASES+_LABEL_CASES,ids=lambda case:case["id"])
def test_quote_definition_exact_count_and_protective_controls(case):
    choices=select_senses(case["text"],_tokens(case),frozenset(case["hard_boundaries"]))
    assert len(choices)==len(case["targets"])
    for target in case["targets"]:
        choice,=[c for c in choices if (c.start,c.end)==(target["start"],target["end"])]
        assert choice.sense_id in target.get("allowed_sense_ids",[target["sense_id"]])
        for start,end in target.get("forbidden_evidence_anchor_spans",[]):
            assert not any(e.anchor_start < end and e.anchor_end > start
                           and e.semantic_class in target["forbidden_evidence_semantic_classes"]
                           for e in choice.evidence)
        for e in choice.evidence:
            assert 0 <= e.anchor_start <= e.anchor_end <= len(case["text"])
            assert (e.target_start,e.target_end)==(choice.start,choice.end)


def _shift_back(choice,offset):
    evidence=tuple(replace(e,target_start=e.target_start-offset,target_end=e.target_end-offset,
                           anchor_start=e.anchor_start-offset,anchor_end=e.anchor_end-offset) for e in choice.evidence)
    return replace(choice,start=choice.start-offset,end=choice.end-offset,evidence=evidence)


@pytest.mark.parametrize("case",_CASES,ids=lambda case:case["id"])
def test_quoted_sentence_duplicate_preserves_local_evidence(case, tmp_path):
    tokens = _tokens(case)
    original = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    offset = len(case["text"]) + 1
    second = tuple(replace(t, start=t.start + offset, end=t.end + offset) for t in tokens)
    hard = frozenset(case["hard_boundaries"] + [x + offset for x in case["hard_boundaries"]])
    supplied = tokens + second
    result = select_senses(case["text"] + " " + case["text"], supplied, hard)
    _QUOTE_CONTRACT.assert_repetition(case, original, result, supplied, hard, offset, select_senses, tmp_path)


@pytest.mark.parametrize("boundary",_DATA["quote_hard_cut_offsets"])
def test_explicit_hard_cut_blocks_quote_naming_relation(boundary):
    case=next(c for c in _CASES if c["id"]=="Q01")
    choice,=select_senses(case["text"],_tokens(case),frozenset({boundary}))
    assert choice.sense_id is None
