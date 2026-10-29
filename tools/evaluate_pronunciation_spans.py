#!/usr/bin/env python3
"""JSONL 사례의 선언된 발음 구간을 재현 가능하게 채점합니다."""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

JUDGMENTS = {"verified", "pending", "policy_dependent", "data_error", "unalignable"}
SPLITS = {"development", "holdout"}
NORMALIZATIONS = {"nfc_exact", "nfc_whitespace_ignored"}
_HANGUL_SYLLABLE_BASE = 0xAC00
_HANGUL_SYLLABLE_COUNT = 11172
_JAMO_LEAD_BASE = 0x1100
_JAMO_VOWEL_BASE = 0x1161
_JAMO_TRAIL_BASE = 0x11A7
_TRAIL_COUNT = 28
_VOWEL_COUNT = 21
_N_COUNT = _VOWEL_COUNT * _TRAIL_COUNT


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_cases(cases: Any) -> None:
    """사례 필드와 선언된 분할의 누수를 검사합니다."""
    if not isinstance(cases, list):
        raise ValueError("cases는 사례 객체의 목록이어야 합니다")

    seen_ids: set[str] = set()
    family_splits: dict[str, str] = {}
    input_splits: dict[str, str] = {}
    leakage_group_splits: dict[str, str] = {}
    source_group_splits: dict[str, str] = {}
    for index, case in enumerate(cases):
        where = f"cases[{index}]"
        if not isinstance(case, dict):
            raise ValueError(f"{where}: 사례는 객체여야 합니다")

        case_id = case.get("id")
        if not _is_nonempty_string(case_id):
            raise ValueError(f"{where}: id는 비어 있지 않은 문자열이어야 합니다")
        if case_id in seen_ids:
            raise ValueError(f"중복 사례 id: {case_id}")
        seen_ids.add(case_id)

        text = case.get("input")
        if not isinstance(text, str):
            raise ValueError(f"{case_id}: input은 문자열이어야 합니다")
        if unicodedata.normalize("NFC", text) != text:
            raise ValueError(f"{case_id}: input은 NFC 정규형이어야 합니다")

        target = case.get("target")
        if not isinstance(target, dict):
            raise ValueError(f"{case_id}: target은 객체여야 합니다")
        start = target.get("start")
        end = target.get("end")
        surface = target.get("surface")
        if type(start) is not int or type(end) is not int:
            raise ValueError(f"{case_id}: target start/end는 정수여야 합니다")
        if not isinstance(surface, str) or not surface:
            raise ValueError(f"{case_id}: target surface는 비어 있지 않은 문자열이어야 합니다")
        if start < 0 or end <= start or end > len(text):
            raise ValueError(f"{case_id}: target 범위가 input의 코드 포인트 범위를 벗어났습니다")
        if text[start:end] != surface:
            raise ValueError(f"{case_id}: target surface가 선언된 input 구간과 다릅니다")

        judgment = case.get("judgment")
        if not isinstance(judgment, str) or judgment not in JUDGMENTS:
            raise ValueError(f"{case_id}: 지원하지 않는 judgment: {judgment}")
        accepted = case.get("accepted_pronunciations")
        if not isinstance(accepted, list):
            raise ValueError(f"{case_id}: accepted_pronunciations는 목록이어야 합니다")
        if any(not isinstance(item, str) for item in accepted):
            raise ValueError(f"{case_id}: 허용 발음은 문자열이어야 합니다")
        if judgment == "verified" and (
            not accepted or any(not item for item in accepted)
        ):
            raise ValueError(f"{case_id}: verified 사례에는 비어 있지 않은 허용 발음이 필요합니다")

        for field in ("category", "family_id"):
            if not _is_nonempty_string(case.get(field)):
                raise ValueError(f"{case_id}: {field}는 비어 있지 않은 문자열이어야 합니다")
        split = case.get("split")
        if not isinstance(split, str) or split not in SPLITS:
            raise ValueError(f"{case_id}: 지원하지 않는 split: {split}")

        sources = case.get("sources")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(source, dict) for source in sources
        ):
            raise ValueError(f"{case_id}: sources에는 출처 객체가 하나 이상 있어야 합니다")

        leakage_groups = case.get("leakage_group_ids", [])
        if not isinstance(leakage_groups, list) or any(
            not _is_nonempty_string(group_id) for group_id in leakage_groups
        ):
            raise ValueError(f"{case_id}: leakage_group_ids는 비어 있지 않은 문자열 목록이어야 합니다")
        for group_id in leakage_groups:
            previous_group_split = leakage_group_splits.setdefault(group_id, split)
            if previous_group_split != split:
                raise ValueError(f"누수 그룹이 split을 가로질렀습니다: {group_id}")

        for source in sources:
            if "source_group_id" not in source:
                continue
            source_group_id = source["source_group_id"]
            if not _is_nonempty_string(source_group_id):
                raise ValueError(f"{case_id}: source_group_id는 비어 있지 않은 문자열이어야 합니다")
            previous_source_split = source_group_splits.setdefault(source_group_id, split)
            if previous_source_split != split:
                raise ValueError(f"출처 그룹이 split을 가로질렀습니다: {source_group_id}")

        frequency = case.get("frequency", 1)
        if type(frequency) is not int or frequency <= 0:
            raise ValueError(f"{case_id}: frequency는 양의 정수여야 합니다")

        normalization = case.get("normalization", "nfc_exact")
        if not isinstance(normalization, str) or normalization not in NORMALIZATIONS:
            raise ValueError(f"{case_id}: 지원하지 않는 normalization: {normalization}")

        if "accepted_sentence_pronunciations" in case:
            sentence_refs = case["accepted_sentence_pronunciations"]
            if not isinstance(sentence_refs, list) or not sentence_refs or any(
                not isinstance(item, str) or not item for item in sentence_refs
            ):
                raise ValueError(
                    f"{case_id}: accepted_sentence_pronunciations는 비어 있지 않은 문자열 목록이어야 합니다"
                )

        previous_family_split = family_splits.setdefault(case["family_id"], split)
        if previous_family_split != split:
            raise ValueError(f"가족 누수: {case['family_id']}가 split을 가로질렀습니다")
        previous_input_split = input_splits.setdefault(text, split)
        if previous_input_split != split:
            raise ValueError(f"입력 누수: NFC 입력이 split을 가로질렀습니다: {text!r}")


def _normalize(value: str, policy: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if policy == "nfc_exact":
        return normalized
    if policy == "nfc_whitespace_ignored":
        return "".join(character for character in normalized if not character.isspace())
    raise ValueError(f"지원하지 않는 normalization: {policy}")


def _is_whitespace_or_punctuation(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _preserves_boundary_positions(source: str, output: str) -> bool:
    for source_character, output_character in zip(source, output):
        if (
            _is_whitespace_or_punctuation(source_character)
            or _is_whitespace_or_punctuation(output_character)
        ) and source_character != output_character:
            return False
    return True


def _symbol_tokens(value: str) -> list[tuple[str, str]]:
    """한글 음절은 초성·중성·종성 기호로 나누고 공백은 제외합니다."""
    normalized = unicodedata.normalize("NFC", value)
    tokens: list[tuple[str, str]] = []
    for character in normalized:
        if character.isspace():
            continue
        codepoint = ord(character)
        syllable_index = codepoint - _HANGUL_SYLLABLE_BASE
        if 0 <= syllable_index < _HANGUL_SYLLABLE_COUNT:
            lead_index = syllable_index // _N_COUNT
            vowel_index = (syllable_index % _N_COUNT) // _TRAIL_COUNT
            trail_index = syllable_index % _TRAIL_COUNT
            tokens.append(("L", chr(_JAMO_LEAD_BASE + lead_index)))
            tokens.append(("V", chr(_JAMO_VOWEL_BASE + vowel_index)))
            if trail_index:
                tokens.append(("T", chr(_JAMO_TRAIL_BASE + trail_index)))
        else:
            tokens.append(("C", character))
    return tokens


def _edit_distance(left: list[Any], right: list[Any]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_item in enumerate(left, 1):
        current = [left_index]
        for right_index, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _nearest_reference(
    output: str, references: list[str], normalization: str
) -> tuple[int, int, str]:
    output_tokens = _symbol_tokens(output)
    choices: list[tuple[int, str]] = []
    for reference in references:
        normalized = _normalize(reference, normalization)
        distance = _edit_distance(output_tokens, _symbol_tokens(normalized))
        choices.append((distance, normalized))
    distance, chosen = min(choices)
    return distance, len(_symbol_tokens(chosen)), chosen


def _validate_outputs(cases: list[dict[str, Any]], outputs: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(outputs, list):
        raise ValueError("outputs는 출력 객체의 목록이어야 합니다")
    case_ids = {case["id"] for case in cases}
    output_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(outputs):
        if not isinstance(item, dict):
            raise ValueError(f"outputs[{index}]: 출력은 객체여야 합니다")
        output_id = item.get("id")
        if not _is_nonempty_string(output_id):
            raise ValueError(f"outputs[{index}]: id는 비어 있지 않은 문자열이어야 합니다")
        if output_id in output_by_id:
            raise ValueError(f"출력 id 중복: {output_id}")
        if output_id not in case_ids:
            raise ValueError(f"사례에 없는 출력 id: {output_id}")
        if "output" not in item or (item["output"] is not None and not isinstance(item["output"], str)):
            raise ValueError(f"{output_id}: output은 문자열 또는 null이어야 합니다")
        if "error" in item and not isinstance(item["error"], str):
            raise ValueError(f"{output_id}: error는 문자열이어야 합니다")
        if "complete" in item and not isinstance(item["complete"], bool):
            raise ValueError(f"{output_id}: complete는 불리언이어야 합니다")
        if "target_output" in item and not isinstance(item["target_output"], str):
            raise ValueError(f"{output_id}: target_output은 문자열이어야 합니다")
        output_by_id[output_id] = item
    return output_by_id


def _score_one(case: dict[str, Any], item: dict[str, Any] | None) -> dict[str, Any]:
    raw_output = item.get("output") if item is not None else None
    error = item.get("error") if item is not None else None
    complete = item.get("complete") if item is not None else None
    target_output = item.get("target_output") if item is not None else None
    error_present = bool(error)

    row: dict[str, Any] = {
        "id": case["id"],
        "input": case["input"],
        "target": dict(case["target"]),
        "split": case["split"],
        "category": case["category"],
        "family_id": case["family_id"],
        "judgment": case["judgment"],
        "frequency": case.get("frequency", 1),
        "output": raw_output,
        "complete": complete,
        "error": error,
        "target_output": target_output,
        "output_status": "not_scored_excluded",
        "alignment": {"status": "not_scored_excluded", "method": None},
        "localized_output": None,
        "span_match": None,
        "exclusion_reason": None,
        "whole_sentence_match": None,
        "symbol_edit": None,
    }

    if error_present:
        row["output_status"] = "error"
    elif item is None or raw_output is None:
        row["output_status"] = "missing"
    else:
        row["output_status"] = "provided"

    if case["judgment"] != "verified":
        row["exclusion_reason"] = case["judgment"]
        return row

    if error_present:
        row["output_status"] = "error"
        row["alignment"] = {"status": "output_error", "method": None}
        row["span_match"] = False
    elif item is None or raw_output is None:
        row["output_status"] = "missing"
        row["alignment"] = {"status": "missing_output", "method": None}
        row["span_match"] = False
    else:
        alignment_failure: dict[str, Any] | None = None
        if target_output is not None:
            localized = target_output
            method = "explicit_target_output"
        elif len(raw_output) != len(case["input"]):
            localized = None
            method = None
            alignment_failure = {
                "status": "length_mismatch",
                "method": None,
                "expected_codepoints": len(case["input"]),
                "actual_codepoints": len(raw_output),
            }
        elif unicodedata.normalize("NFC", raw_output) != raw_output:
            localized = None
            method = None
            alignment_failure = {
                "status": "non_nfc_output",
                "method": None,
                "expected_codepoints": len(case["input"]),
                "actual_codepoints": len(raw_output),
            }
        elif not _preserves_boundary_positions(case["input"], raw_output):
            localized = None
            method = None
            alignment_failure = {
                "status": "boundary_position_mismatch",
                "method": None,
                "expected_codepoints": len(case["input"]),
                "actual_codepoints": len(raw_output),
            }
        else:
            start, end = case["target"]["start"], case["target"]["end"]
            localized = raw_output[start:end]
            method = "same_length_codepoint_slice"

        if localized is None:
            row["output_status"] = "alignment_failure"
            row["alignment"] = alignment_failure
            row["span_match"] = False
        else:
            row["output_status"] = "provided"
            row["alignment"] = {"status": "aligned", "method": method}
            row["localized_output"] = localized
            policy = case.get("normalization", "nfc_exact")
            actual = _normalize(localized, policy)
            row["span_match"] = any(
                actual == _normalize(reference, policy)
                for reference in case["accepted_pronunciations"]
            )
            edits, reference_count, chosen = _nearest_reference(
                localized, case["accepted_pronunciations"], policy
            )
            output_count = len(_symbol_tokens(localized))
            row["symbol_edit"] = {
                "edits": edits,
                "reference_token_count": reference_count,
                "output_token_count": output_count,
                "rate": edits / reference_count if reference_count else None,
                "chosen_reference": chosen,
            }

    sentence_references = case.get("accepted_sentence_pronunciations")
    if sentence_references is not None:
        if error_present or item is None or raw_output is None:
            row["whole_sentence_match"] = False
        else:
            policy = case.get("normalization", "nfc_exact")
            actual = _normalize(raw_output, policy)
            row["whole_sentence_match"] = any(
                actual == _normalize(reference, policy) for reference in sentence_references
            )
    return row


def _score_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    selected = [row for row in rows if row[field] is not None]
    matched = [row for row in selected if row[field] is True]
    mismatched = [row for row in selected if row[field] is False]

    def counts(source: list[dict[str, Any]]) -> dict[str, int]:
        return {"cases": len(source), "frequency_weight": sum(row["frequency"] for row in source)}

    def rate(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    result: dict[str, Any] = {
        **counts(selected),
        "matched": len(matched),
        "mismatched": len(mismatched),
        "accuracy": rate(len(matched), len(selected)),
        "weighted": {
            **counts(selected),
            "matched": sum(row["frequency"] for row in matched),
            "mismatched": sum(row["frequency"] for row in mismatched),
            "accuracy": rate(
                sum(row["frequency"] for row in matched),
                sum(row["frequency"] for row in selected),
            ),
        },
    }
    if field == "span_match":
        for label, predicate in (
            ("missing_outputs", lambda row: row["output_status"] == "missing"),
            ("error_outputs", lambda row: row["output_status"] == "error"),
            ("alignment_failures", lambda row: row["output_status"] == "alignment_failure"),
        ):
            matching = [row for row in selected if predicate(row)]
            result[label] = len(matching)
            result["weighted"][label] = sum(row["frequency"] for row in matching)
    return result


def _symbol_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["judgment"] == "verified"]
    compared = [row for row in eligible if row["symbol_edit"] is not None]
    edits = sum(row["symbol_edit"]["edits"] for row in compared)
    ref_tokens = sum(row["symbol_edit"]["reference_token_count"] for row in compared)
    weighted_edits = sum(
        row["frequency"] * row["symbol_edit"]["edits"] for row in compared
    )
    weighted_ref_tokens = sum(
        row["frequency"] * row["symbol_edit"]["reference_token_count"] for row in compared
    )
    compared_weight = sum(row["frequency"] for row in compared)
    eligible_weight = sum(row["frequency"] for row in eligible)
    return {
        "compared_cases": len(compared),
        "unavailable_cases": len(eligible) - len(compared),
        "frequency_weight_compared": compared_weight,
        "frequency_weight_unavailable": eligible_weight - compared_weight,
        "edits": edits,
        "reference_tokens": ref_tokens,
        "rate": edits / ref_tokens if ref_tokens else None,
        "weighted": {
            "compared_cases": compared_weight,
            "unavailable_cases": eligible_weight - compared_weight,
            "edits": weighted_edits,
            "reference_tokens": weighted_ref_tokens,
            "rate": weighted_edits / weighted_ref_tokens if weighted_ref_tokens else None,
        },
    }


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    judgment_counts: dict[str, dict[str, int]] = {}
    exclusions: dict[str, dict[str, int]] = {}
    for judgment in sorted(JUDGMENTS):
        matching = [row for row in rows if row["judgment"] == judgment]
        judgment_counts[judgment] = {
            "cases": len(matching),
            "frequency_weight": sum(row["frequency"] for row in matching),
        }
        if judgment != "verified":
            exclusions[judgment] = judgment_counts[judgment]

    output_counts: dict[str, dict[str, int]] = {}
    for status in sorted({row["output_status"] for row in rows}):
        matching = [row for row in rows if row["output_status"] == status]
        output_counts[status] = {
            "cases": len(matching),
            "frequency_weight": sum(row["frequency"] for row in matching),
        }

    return {
        "cases": len(rows),
        "frequency_weight": sum(row["frequency"] for row in rows),
        "judgment_counts": judgment_counts,
        "exclusions": {
            "cases": sum(item["cases"] for item in exclusions.values()),
            "frequency_weight": sum(item["frequency_weight"] for item in exclusions.values()),
            "by_judgment": exclusions,
        },
        "output_status_counts": output_counts,
        "span_exact": _score_summary(rows, "span_match"),
        "whole_sentence_exact": _score_summary(rows, "whole_sentence_match"),
        "symbol_edit": _symbol_summary(rows),
    }


def evaluate(cases: Any, outputs: Any) -> dict[str, Any]:
    """사례와 사전 계산된 출력으로 구간·문장 점수를 계산합니다."""
    validate_cases(cases)
    output_by_id = _validate_outputs(cases, outputs)
    rows = [_score_one(case, output_by_id.get(case["id"])) for case in cases]

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
        by_family[row["family_id"]].append(row)

    return {
        "schema_version": 1,
        "method": "pronunciation_span_exact_and_hangul_symbol_edit",
        "summary": _group_summary(rows),
        "categories": {
            name: _group_summary(group) for name, group in sorted(by_category.items())
        },
        "families": {name: _group_summary(group) for name, group in sorted(by_family.items())},
        "rows": rows,
        "notes": [
            "동일 길이 출력에만 input NFC 코드 포인트 인덱스를 적용합니다. 출력이 NFC가 아니거나 input의 공백·문장 부호 위치를 보존하지 않으면 정렬 실패로 기록합니다.",
            "target_output은 외부 어댑터가 미리 정렬한 구간입니다. 이 값으로 점수화한 행은 alignment.method에 표시합니다.",
            "verified 이외 judgment는 정확도 분모에서 제외하고 상태별 사례 수와 빈도를 계속 보고합니다.",
            "complete 표시는 정확도 판단에 사용하지 않습니다. 출력 오류와 누락은 verified 사례의 실패로 계산합니다.",
            "whole_sentence_exact은 accepted_sentence_pronunciations가 선언된 verified 사례에만 별도로 계산합니다.",
            "symbol_edit는 한글 음절을 초성(L), 중성(V), 종성(T) 기호로 나눈 Levenshtein 편집률입니다. 비한글·비공백 문자는 태그 C 기호로 유지하며, IPA 음소 오류율이 아닙니다.",
            "symbol_edit 대안 동률은 정규화된 허용 발음의 유니코드 사전순으로 선택합니다. 공백은 기호 편집에서 무시합니다.",
            "참조 기호 수가 0이면 편집률은 null로 두어 0 나눗셈을 피합니다.",
            "frequency 가중 점수는 사례 frequency의 합을 가중 분모로 사용하며, 실행 시간이나 처리량을 점수화하지 않습니다.",
        ],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"파일을 읽을 수 없습니다: {path}: {exc}") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(contents.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: JSON 파싱 실패: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: JSONL 행은 객체여야 합니다")
        records.append(value)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="사례 JSONL 경로")
    parser.add_argument("--outputs", type=Path, required=True, help="사전 계산 출력 JSONL 경로")
    parser.add_argument("--report", type=Path, required=True, help="결과 JSON 경로")
    args = parser.parse_args(argv)

    try:
        cases = _read_jsonl(args.cases)
        outputs = _read_jsonl(args.outputs)
        report = evaluate(cases, outputs)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "report": str(args.report),
                "cases": report["summary"]["cases"],
                "weighted_cases": report["summary"]["frequency_weight"],
                "span_exact": report["summary"]["span_exact"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
