"""동결된 네 사례의 반복 소유 범위와 원래 일반 근거를 함께 검사한다."""

from dataclasses import fields, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[1]
_ADDENDUM = json.loads((Path(__file__).parent / "fixtures/quote_repetition_contract_addendum.json").read_text(encoding="utf-8"))
for _name, _digest in _ADDENDUM["original_fixture_sha256"].items():
    if hashlib.sha256((_ROOT / _name).read_bytes()).hexdigest() != _digest:
        raise AssertionError("REFERENCE:fixture_hash")


def _jsonable(value):
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _check(condition, case, name, tmp_path, payload):
    if condition:
        return
    # 전체 비교는 비공개 파일에 보존하고 실패에는 ID와 검사명만 남긴다.
    identifier = re.sub(r"[^A-Za-z0-9_.-]", "_", case["id"])
    directory = tmp_path / "quote_contract_failure_private"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{identifier}__{name}.json").write_text(
            json.dumps(_jsonable(dict(case=case, check=name, comparison=payload)), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    except Exception:
        raise AssertionError(f"{identifier}:{name}:private_write_failed") from None
    raise AssertionError(f"{identifier}:{name}")


def _translate(choice, offset):
    evidence = tuple(replace(item, target_start=item.target_start - offset,
                             target_end=item.target_end - offset,
                             anchor_start=item.anchor_start - offset,
                             anchor_end=item.anchor_end - offset) for item in choice.evidence)
    return replace(choice, start=choice.start - offset, end=choice.end - offset, evidence=evidence)


def _ordinary(choice):
    relation = _ADDENDUM["owner_evidence"]["relation"]
    return replace(choice, evidence=tuple(item for item in choice.evidence if item.relation != relation))


def _positions(case, choices, expected, tmp_path, payload, label):
    actual = [(choice.start, choice.end) for choice in choices]
    _check(len(actual) == len(expected) and len(set(actual)) == len(actual) and set(actual) == set(expected),
           case, label, tmp_path, payload)


def _coordinates(case, choice, text, tmp_path, payload):
    for item in choice.evidence:
        values = (item.target_start, item.target_end, item.anchor_start, item.anchor_end)
        _check(all(isinstance(value, int) and not isinstance(value, bool) for value in values)
               and (item.target_start, item.target_end) == (choice.start, choice.end)
               and 0 <= item.anchor_start <= item.anchor_end <= len(text),
               case, "evidence_coordinates", tmp_path, payload)


def _scope(case, text, choice, hard, tmp_path, payload):
    left = max((cut for cut in hard if cut <= choice.start), default=0)
    right = min((cut for cut in hard if cut > choice.start), default=len(text))
    # 네 동결 구조는 실제 닫힘이 없는 뿌리다. 위치는 후보 근거가 아닌 원문에서 얻는다.
    openings = set(_ADDENDUM["opening_glyphs"])
    root = next((index for index in range(left, right) if text[index] in openings), None)
    _check(root is not None and root <= choice.start < choice.end <= right,
           case, "reference_unclosed_scope", tmp_path, payload)
    return root, right


def _owner(case, choice, text, hard, tmp_path, payload):
    declaration = _ADDENDUM["owner_evidence"]
    owners = [item for item in choice.evidence if item.relation == declaration["relation"]]
    _check(choice.sense_id is None and choice.reason in declaration["permitted_reasons"],
           case, "unresolved_abstention_priority", tmp_path, payload)
    _check(len(owners) == 1, case, "owner_count", tmp_path, payload)
    expected = _scope(case, text, choice, hard, tmp_path, payload)
    for item in owners:
        _check(item.semantic_class == declaration["semantic_class"]
               and (item.target_start, item.target_end) == (choice.start, choice.end)
               and (item.anchor_start, item.anchor_end) == expected,
               case, "owner_binding_scope", tmp_path, payload)


def _expected_sense(case, target):
    if case["id"] == _ADDENDUM["standalone_overlay"]["case_id"]:
        ordered = sorted(case["targets"], key=lambda item: (item["start"], item["end"]))
        if target is ordered[-1]:
            return _ADDENDUM["standalone_overlay"]["expected_sense_id"]
    return target["sense_id"]


def assert_standalone(case, choices, select, tokens, tmp_path):
    payload = dict(choices=choices, tokens=tokens)
    expected = [(target["start"], target["end"]) for target in case["targets"]]
    _positions(case, choices, expected, tmp_path, payload, "standalone_occurrences")
    for target in case["targets"]:
        choice = next(item for item in choices if (item.start, item.end) == (target["start"], target["end"]))
        _check(choice.sense_id == _expected_sense(case, target), case, "standalone_sense", tmp_path, payload)
        _coordinates(case, choice, case["text"], tmp_path, payload)
    if case["id"] not in _ADDENDUM["case_contracts"]:
        return
    hard = frozenset(case.get("hard_boundaries", case.get("hard", [])))
    for choice in choices:
        _owner(case, choice, case["text"], hard, tmp_path, payload)
    controls = [item for item in _ADDENDUM["hard_controls"]
                if item["source_case_id"] == case["id"] and item["kind"] == "local_clause"]
    for control in controls:
        local_hard = hard | frozenset(control["new_hard_boundaries"])
        local = select(case["text"], tokens, local_hard)
        comparison = dict(standalone=choices, local=local, local_hard=local_hard)
        _positions(case, local, expected, tmp_path, comparison, "local_HARD_occurrences")
        for reference in control["expected_targets"]:
            target = case["targets"][reference["original_target_index"]]
            choice = next(item for item in local if (item.start, item.end) == (reference["start"], reference["end"]))
            sense = target["sense_id"] if reference["expectation"] == "original_fixture_gold" else None
            _check(choice.sense_id == sense, case, "local_HARD_original_gold", tmp_path, comparison)
            _coordinates(case, choice, case["text"], tmp_path, comparison)
            if sense is None:
                _owner(case, choice, case["text"], local_hard, tmp_path, comparison)
            else:
                left = max((cut for cut in local_hard if cut <= choice.start), default=0)
                _check(choice.reason == "selected" and all(item.anchor_start >= left for item in choice.evidence)
                       and not any(item.relation == _ADDENDUM["owner_evidence"]["relation"] for item in choice.evidence),
                       case, "local_HARD_positive_ownership", tmp_path, comparison)


def assert_repetition(case, original, repeated, tokens, hard, offset, select, tmp_path):
    text = case["text"] + " " + case["text"]
    expected = [(target["start"] + shift, target["end"] + shift)
                for shift in (0, offset) for target in case["targets"]]
    payload = dict(original=original, repeated=repeated, repeated_text=text, tokens=tokens, hard=hard, offset=offset)
    _positions(case, repeated, expected, tmp_path, payload, "raw_occurrences")
    first = tuple(item for item in repeated if item.start < offset)
    second = tuple(item for item in repeated if item.start >= offset)
    scoped = case["id"] in _ADDENDUM["case_contracts"]
    if scoped:
        single_hard = frozenset(case.get("hard_boundaries", case.get("hard", [])))
        for choice in original:
            _coordinates(case, choice, case["text"], tmp_path, payload)
            _owner(case, choice, case["text"], single_hard, tmp_path, payload)
        for choice in repeated:
            _coordinates(case, choice, text, tmp_path, payload)
            _owner(case, choice, text, hard, tmp_path, payload)
        baseline = tuple(_ordinary(item) for item in original)
        _check(tuple(_ordinary(item) for item in first) == baseline,
               case, "ordinary_copy_0", tmp_path, payload)
        _check(tuple(_translate(_ordinary(item), offset) for item in second) == baseline,
               case, "ordinary_copy_1", tmp_path, payload)
    else:
        _check(first == original, case, "exact_copy_0", tmp_path, payload)
        _check(tuple(_translate(item, offset) for item in second) == original,
               case, "exact_copy_1", tmp_path, payload)
        return

    control = next(item for item in _ADDENDUM["hard_controls"]
                   if item["source_case_id"] == case["id"] and item["kind"] == "repeat")
    _check(control["copy_offset"] == offset and control["new_hard_boundaries"] == [len(case["text"])],
           case, "HARD_reference_geometry", tmp_path, payload)
    separated_hard = hard | frozenset(control["new_hard_boundaries"])
    separated = select(text, tokens, separated_hard)
    comparison = dict(original=original, raw=repeated, separated=separated, repeated_text=text,
                      tokens=tokens, separated_hard=separated_hard, offset=offset)
    _positions(case, separated, expected, tmp_path, comparison, "HARD_occurrences")
    for choice in separated:
        _coordinates(case, choice, text, tmp_path, comparison)
        _owner(case, choice, text, separated_hard, tmp_path, comparison)
    _check(tuple(item for item in separated if item.start < offset) == original,
           case, "HARD_exact_copy_0", tmp_path, comparison)
    _check(tuple(_translate(item, offset) for item in separated if item.start >= offset) == original,
           case, "HARD_exact_copy_1", tmp_path, comparison)
