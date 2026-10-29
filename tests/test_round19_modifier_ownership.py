"""선행 관형절과 명사 핵어의 소유를 출현ㆍ원문 경계별로 확인한다."""
from dataclasses import replace
import hashlib
import json
import importlib.util as _quote_import
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


# 같은 테스트 폴더의 한정된 보조 코드만 읽는다. output 자료에 의존하지 않는다.
_QUOTE_SPEC = _quote_import.spec_from_file_location("quote_repetition_contract_test_support", Path(__file__).with_name("_quote_repetition_contract.py"))
_QUOTE_CONTRACT = _quote_import.module_from_spec(_QUOTE_SPEC)
_QUOTE_SPEC.loader.exec_module(_QUOTE_CONTRACT)

_FIXTURE_PATH = Path(__file__).parent / "fixtures/round19_modifier_ownership.json"
_FIXTURE_BYTES = _FIXTURE_PATH.read_bytes()
_ADDENDUM = json.loads((Path(__file__).parent / "fixtures/round19_modifier_ownership_contract_addendum.json").read_text(encoding="utf-8"))
assert hashlib.sha256(_FIXTURE_BYTES).hexdigest() == _ADDENDUM["original_fixture_sha256"]


def _r48_expectation_view(case):
    """동결 입력 하나의 기대값만 별도 보정하며 원본 자료는 유지한다."""
    if case["id"] != _ADDENDUM["case_id"]:
        return case
    supplied = {key: case[key] for key in ("text", "tokens", "hard")}
    encoded = json.dumps(supplied, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == _ADDENDUM["original_input_sha256"]
    overlay = _ADDENDUM["semantic_expectation_overlay"]
    targets = [dict(target) for target in case["targets"]]
    matched = [target for target in targets if (target["start"], target["end"]) == (overlay["start"], overlay["end"])]
    assert len(matched) == 1 and matched[0]["sense_id"] == overlay["original_sense_id"]
    matched[0]["sense_id"] = overlay["corrected_sense_id"]
    return dict(case, targets=targets)


_ORIGINAL_CASES = json.loads(_FIXTURE_BYTES)["cases"]
assert sum(case["id"] == _ADDENDUM["case_id"] for case in _ORIGINAL_CASES) == 1
CASES = [_r48_expectation_view(case) for case in _ORIGINAL_CASES]


def _assert_r48_local_nonparticipation(case, selected):
    """특정 국소 소유의 비참여만 확인하며 다른 독립 원천은 제한하지 않는다."""
    if case["id"] != _ADDENDUM["case_id"]:
        return
    guard = _ADDENDUM["scoped_local_owner_nonparticipation"]
    assert not any(
        (item.target_start, item.target_end) == (guard["target_start"], guard["target_end"])
        and item.relation in guard["relations"]
        and item.anchor_start == guard["source_P_start"]
        for choice in selected for item in choice.evidence
    )


def tokens(case):
    return tuple(SemanticToken(**row) for row in case["tokens"])


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_frozen_modifier_contract(case):
    selected = select_senses(case["text"], tokens(case), frozenset(case["hard"]))
    assert [(row.start, row.end, row.sense_id) for row in selected] == [
        (row["start"], row["end"], row["sense_id"]) for row in case["targets"]]
    for choice in selected:
        for evidence in choice.evidence:
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
        if choice.sense_id:
            assert any(row.relation == "quoted_nominal_boundary" for row in choice.evidence)
    _assert_r48_local_nonparticipation(case, selected)


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_repeated_modifier_occurrences_preserve_all_evidence(case, tmp_path):
    provided = tokens(case)
    original = select_senses(case["text"], provided, frozenset(case["hard"]))
    shift = len(case["text"]) + 1
    duplicate = tuple(replace(row, start=row.start + shift, end=row.end + shift) for row in provided)
    cuts = frozenset(case["hard"] + [cut + shift for cut in case["hard"]])
    supplied = provided + duplicate
    selected = select_senses(case["text"] + " " + case["text"], supplied, cuts)
    _QUOTE_CONTRACT.assert_repetition(case, original, selected, supplied, cuts, shift, select_senses, tmp_path)


@pytest.mark.parametrize("case", CASES[:13], ids=lambda row: row["id"])
def test_hard_isolation_prevents_definition_borrowing(case):
    target = case["targets"][-1]
    cuts = frozenset({target["start"], target["end"]})
    selected = select_senses(case["text"], tokens(case), cuts)
    owned, = [row for row in selected if row.start == target["start"]]
    assert owned.sense_id is None


@pytest.mark.parametrize("case", CASES[11:13], ids=lambda row: row["id"])
def test_internal_argument_target_cannot_own_outer_head(case):
    first, second = select_senses(case["text"], tokens(case))
    assert first.sense_id is None and second.sense_id == "sabeop.judicial_function"
    closing = case["text"].index("”")
    assert not any(item.anchor_start > closing for item in first.evidence)
