"""정상 분석에서 유형 전달·분류·중립 수식과 출현별 경계를 검증한다."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


_DATA = json.loads((Path(__file__).parent / "fixtures" / "korean_semantic_scope.json").read_text(encoding="utf-8"))
_CASES = _DATA["cases"]
_HARD_CASES = [case for case in _CASES if case["id"] in _DATA["relative_hard_cut_case_ids"]]


def _tokens(case):
    return tuple(SemanticToken(**token) for token in case["tokens"])


def _shift_back(choice, offset):
    # 상대 좌표만 이동하며 근거의 종류·개수·자료형은 그대로 비교한다.
    evidence = tuple(replace(item, target_start=item.target_start - offset,
                             target_end=item.target_end - offset, anchor_start=item.anchor_start - offset,
                             anchor_end=item.anchor_end - offset) for item in choice.evidence)
    return replace(choice, start=choice.start - offset, end=choice.end - offset, evidence=evidence)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_category_wrappers_classification_and_modifier_scope(case):
    choices = select_senses(case["text"], _tokens(case), frozenset(case["hard_boundaries"]))
    assert len(choices) == len(case["targets"])
    for target in case["targets"]:
        choice, = [choice for choice in choices if (choice.start, choice.end) == (target["start"], target["end"])]
        assert choice.sense_id in target.get("allowed_sense_ids", [target["sense_id"]])
        for start, end in target.get("forbidden_evidence_anchor_spans", []):
            assert not any(item.anchor_start < end and item.anchor_end > start
                           and item.semantic_class in target.get("forbidden_evidence_semantic_classes", [item.semantic_class])
                           for item in choice.evidence)
        for evidence in choice.evidence:
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_repeated_sentence_preserves_local_choices_and_evidence(case):
    tokens = _tokens(case)
    original = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    offset = len(case["text"]) + 1
    duplicate_tokens = tuple(replace(token, start=token.start + offset, end=token.end + offset) for token in tokens)
    boundaries = frozenset(case["hard_boundaries"] + [value + offset for value in case["hard_boundaries"]])
    result = select_senses(case["text"] + " " + case["text"], tokens + duplicate_tokens, boundaries)
    first = tuple(choice for choice in result if choice.start < offset)
    second = tuple(_shift_back(choice, offset) for choice in result if choice.start >= offset)
    assert original == first == second


@pytest.mark.parametrize("case", _HARD_CASES, ids=lambda case: case["id"])
def test_hard_boundary_blocks_preceding_definition(case):
    target = case["targets"][0]
    choices = select_senses(case["text"], _tokens(case), frozenset({target["start"]}))
    choice, = [choice for choice in choices if (choice.start, choice.end) == (target["start"], target["end"])]
    assert choice.sense_id is None
