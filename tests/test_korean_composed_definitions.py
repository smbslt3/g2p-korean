"""실제 핵어·부분·수량의 합성과 인용 내부 정의의 소유를 검증한다."""
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

_DATA = json.loads((Path(__file__).parent / "fixtures/korean_composed_definitions.json").read_text(encoding="utf-8"))
_CASES = _DATA["cases"]


def _tokens(case):
    return tuple(SemanticToken(**token) for token in case["tokens"])


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_explicit_composed_definition_owns_each_target(case, tmp_path):
    tokens = _tokens(case)
    choices = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    _QUOTE_CONTRACT.assert_standalone(case, choices, select_senses, tokens, tmp_path)


def _shift_back(choice, offset):
    evidence = tuple(replace(item, target_start=item.target_start-offset, target_end=item.target_end-offset,
                             anchor_start=item.anchor_start-offset, anchor_end=item.anchor_end-offset)
                     for item in choice.evidence)
    return replace(choice, start=choice.start-offset, end=choice.end-offset, evidence=evidence)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_repetition_preserves_semantics_and_evidence_coordinates(case, tmp_path):
    tokens = _tokens(case)
    original = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    offset = len(case["text"]) + 1
    second = tuple(replace(token, start=token.start + offset, end=token.end + offset) for token in tokens)
    cuts = frozenset(case["hard_boundaries"] + [cut + offset for cut in case["hard_boundaries"]])
    supplied = tokens + second
    choices = select_senses(case["text"] + " " + case["text"], supplied, cuts)
    _QUOTE_CONTRACT.assert_repetition(case, original, choices, supplied, cuts, offset, select_senses, tmp_path)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_isolated_target_cannot_borrow_external_definition(case):
    target = case["isolation_target"]
    cuts = frozenset(case["hard_boundaries"] + [target["start"], target["end"]])
    choices = select_senses(case["text"], _tokens(case), cuts)
    choice, = [item for item in choices if (item.start, item.end) == (target["start"], target["end"])]
    assert choice.sense_id is None
    assert all(target["start"] <= item.anchor_start <= item.anchor_end <= target["end"] for item in choice.evidence)
