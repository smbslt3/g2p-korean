"""관형절 구성 관계의 역할·반복 좌표·HARD 경계 격리를 검증한다."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses

_DATA = json.loads((Path(__file__).parent / "fixtures/korean_membership_roles.json").read_text(encoding="utf-8"))
_CASES = _DATA["cases"]


def _tokens(case):
    return tuple(SemanticToken(**token) for token in case["tokens"])


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_membership_relative_preserves_target_ownership(case):
    choices = select_senses(case["text"], _tokens(case), frozenset(case["hard_boundaries"]))
    assert len(choices) == len(case["targets"])
    for target in case["targets"]:
        choice, = [item for item in choices if (item.start, item.end) == (target["start"], target["end"])]
        assert choice.sense_id == target["sense_id"]
        for evidence in choice.evidence:
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)


def _shift_back(choice, offset):
    evidence = tuple(replace(item, target_start=item.target_start-offset, target_end=item.target_end-offset,
                             anchor_start=item.anchor_start-offset, anchor_end=item.anchor_end-offset)
                     for item in choice.evidence)
    return replace(choice, start=choice.start-offset, end=choice.end-offset, evidence=evidence)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_repetition_preserves_semantics_and_evidence_coordinates(case):
    tokens = _tokens(case)
    original = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    offset = len(case["text"]) + 1
    second = tuple(replace(token, start=token.start+offset, end=token.end+offset) for token in tokens)
    cuts = frozenset(case["hard_boundaries"] + [cut+offset for cut in case["hard_boundaries"]])
    choices = select_senses(case["text"] + " " + case["text"], tokens+second, cuts)
    assert tuple(item for item in choices if item.start < offset) == original
    assert tuple(_shift_back(item, offset) for item in choices if item.start >= offset) == original


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_isolated_target_cannot_borrow_external_definition(case):
    target = case["isolation_target"]
    cuts = frozenset(case["hard_boundaries"] + [target["start"], target["end"]])
    choices = select_senses(case["text"], _tokens(case), cuts)
    choice, = [item for item in choices if (item.start, item.end) == (target["start"], target["end"])]
    assert choice.sense_id is None
    assert all(target["start"] <= item.anchor_start <= item.anchor_end <= target["end"] for item in choice.evidence)
