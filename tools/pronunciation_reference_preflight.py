#!/usr/bin/env python3
"""엔진 출력 없이 참조 창의 구조와 원문 경계의 검토 필요성을 확인합니다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from tools.evaluate_pronunciation_spans import validate_cases
else:
    from evaluate_pronunciation_spans import validate_cases

PAUSE_ASSUMPTIONS = {"unspecified", "no_pause", "possible_pause", "pause"}
_PLAIN_ONSETS = {0, 3, 7, 9, 12}
_LIMITATIONS_KO = (
    "경고는 원문 철자의 검토 후보이며 오발음 판정이 아니다. 철자만으로 형태소·관형형·"
    "된소리되기·연음·휴지를 결정하지 않는다. 공백과 문장부호도 휴지의 증거로 확정하지 않는다. "
    "발음 정답이나 허용 발음 합집합을 생성하지 않고 기존 참조와 점수를 변경하지 않는다. "
    "경고가 없어도 참조의 정확성이나 경계 검토 완료를 보증하지 않는다."
)


def _syllable(character: str) -> tuple[int, int, int] | None:
    value = ord(character) - 0xAC00
    if 0 <= value < 11172:
        return value // 588, value % 588 // 28, value % 28
    return None


def _separator(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _finding(case_id: str | None, kind: str, *, severity: str = "review", **extra: Any) -> dict[str, Any]:
    return {"id": case_id, "kind": kind, "severity": severity, **extra}


def _normalized(value: str, case: dict[str, Any]) -> str:
    value = unicodedata.normalize("NFC", value)
    if case.get("normalization", "nfc_exact") == "nfc_whitespace_ignored":
        return "".join(character for character in value if not character.isspace())
    return value


def _reference_records(case: dict[str, Any]) -> list[dict[str, Any]]:
    """명시적 조건을 각각 보존하며 조건 사이의 승인 집합을 만들지 않습니다."""
    window = case.get("reference_window") or {}
    conditions = window.get("witness_conditions", [])
    records = []
    for index, pronunciation in enumerate(window.get("accepted_pronunciations", [])):
        matches = [item for item in conditions if item.get("pronunciation") == pronunciation]
        for witness in matches or [None]:
            records.append({
                "pronunciation": pronunciation,
                "reference_index": index,
                "target_references": case["accepted_pronunciations"],
                "witness": copy.deepcopy(witness),
            })
    for index, witness in enumerate(case.get("conditional_projection_witnesses", [])):
        target = witness.get("target_pronunciation")
        records.append({
            "pronunciation": witness.get("reference_window_pronunciation"),
            "conditional_witness_index": index,
            "target_references": [target] if isinstance(target, str) else [],
            "witness": copy.deepcopy(witness),
        })
    return records


def _check_window(case: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """기존 표적 계약에 참조 창의 좌표와 명시적 투영 구조 검사를 더합니다."""
    case_id = case["id"]
    window = case.get("reference_window")
    if window is None:
        kind = "missing_reference_window" if case["judgment"] == "verified" else "review_reference_window_missing"
        severity = "error" if case["judgment"] == "verified" else "review"
        return [_finding(case_id, kind, severity=severity)], True
    target, text = case["target"], case["input"]
    if not isinstance(window, dict):
        return [_finding(case_id, "invalid_reference_window", severity="error")], False
    start, end = window.get("start"), window.get("end")
    if not (type(start) is int and type(end) is int and
            0 <= start <= target["start"] < target["end"] <= end <= len(text)):
        return [_finding(case_id, "invalid_reference_window_coordinates", severity="error")], False
    if "surface" in window and window["surface"] != text[start:end]:
        return [_finding(case_id, "reference_window_surface_mismatch", severity="error")], False
    references = window.get("accepted_pronunciations")
    if not isinstance(references, list) or any(not isinstance(ref, str) or not ref for ref in references):
        return [_finding(case_id, "invalid_window_pronunciations", severity="error")], False
    conditions = window.get("witness_conditions", [])
    witnesses = case.get("conditional_projection_witnesses", [])
    if not isinstance(conditions, list) or any(not isinstance(item, dict) for item in conditions):
        return [_finding(case_id, "invalid_window_witness_conditions", severity="error")], False
    if not isinstance(witnesses, list) or any(not isinstance(item, dict) for item in witnesses):
        return [_finding(case_id, "invalid_conditional_projection_witnesses", severity="error")], False
    findings = []
    if case["judgment"] == "verified" and not references:
        findings.append(_finding(case_id, "missing_window_pronunciations", severity="error"))
    for record in _reference_records(case):
        pronunciation = record["pronunciation"]
        identity = {key: record[key] for key in ("reference_index", "conditional_witness_index") if key in record}
        if record["witness"] is not None:
            identity["witness"] = record["witness"]
        if (not isinstance(pronunciation, str) or not pronunciation or
                unicodedata.normalize("NFC", pronunciation) != pronunciation or len(pronunciation) != end - start):
            findings.append(_finding(case_id, "unaligned_window_pronunciation", severity="error", **identity))
            continue
        if any((_separator(a) or _separator(b)) and a != b for a, b in zip(text[start:end], pronunciation)):
            findings.append(_finding(case_id, "window_boundary_position_mismatch", severity="error", **identity))
            continue
        projected = pronunciation[target["start"] - start:target["end"] - start]
        target_refs = record["target_references"]
        if "conditional_witness_index" in record and (not target_refs or not target_refs[0]):
            findings.append(_finding(case_id, "missing_conditional_target_pronunciation", severity="error", **identity))
        elif target_refs and _normalized(projected, case) not in {_normalized(ref, case) for ref in target_refs}:
            findings.append(_finding(case_id, "window_target_projection_mismatch", severity="error", **identity))
        for offset, (source, reference) in enumerate(zip(text[start:end], pronunciation), start):
            source_parts, reference_parts = _syllable(source), _syllable(reference)
            if source_parts and reference_parts and source_parts[1] != reference_parts[1]:
                findings.append(_finding(case_id, "review_reference_medial_vowel_change", source_offset=offset,
                                         source_character=source, reference_character=reference,
                                         confirmed_error=False, **identity))
    return findings, True


def _assumptions(case: dict[str, Any], reading_profile: str, pause_assumption: str) -> dict[str, Any]:
    explicit = case.get("reference_boundary_assumptions", {})
    return {
        "reading_profile": explicit.get("reading_profile", reading_profile),
        "pause_assumption": explicit.get("pause_assumption", pause_assumption),
        "source": "case_over_cli_defaults" if explicit else "cli_defaults",
        "pause_inferred_from_separator": False,
    }


def _inspect_boundaries(case: dict[str, Any], assumptions: dict[str, Any]) -> list[dict[str, Any]]:
    text, target = case["input"], case["target"]
    ts, te = target["start"], target["end"]
    window = case.get("reference_window")
    ws, we = (window["start"], window["end"]) if window is not None else (ts, te)
    findings = []

    def warning(kind: str, **values: Any) -> dict[str, Any]:
        return _finding(case["id"], kind, confirmed_error=False,
                        coordinate_policy="source_nfc_codepoints_half_open",
                        assumptions=copy.deepcopy(assumptions), **values)

    previous = None
    boundary_count = 0
    for right, character in enumerate(text):
        if _separator(character):
            continue
        left, previous = previous, right
        if left is None:
            continue
        a, b = _syllable(text[left]), _syllable(character)
        if not a or not b or not a[2]:
            continue
        left_owned, right_owned = ts <= left < te, ts <= right < te
        gap = text[left + 1:right]
        crosses_target = left_owned != right_owned
        if not gap and not crosses_target:
            continue
        if not (left_owned or right_owned or (window is not None and ws <= left < right < we)):
            continue
        kinds = []
        if b[0] == 11:
            separator = "punctuation" if any(not char.isspace() for char in gap) else "whitespace" if gap else "adjacent"
            kinds.append(f"review_source_coda_{separator}_vowel_boundary")
        if b[0] in _PLAIN_ONSETS:
            kinds.append("review_potential_consonant_tensing")
        if a[2] == 8 and b[0] != 11 and gap:
            kinds.append("review_potential_adnominal_l_boundary")
        if not kinds:
            continue
        boundary_count += 1
        within = window is not None and ws <= left < right < we
        edge = "internal" if left_owned and right_owned else "right" if left_owned else "left" if right_owned else "none"
        values = {
            "source_offsets": {"coda": left, "onset": right, "separator_start": left + 1, "separator_end": right},
            "source_boundary": text[left:right + 1],
            "source_coda_index": a[2], "source_onset_index": b[0],
            "target_coordinates": {"start": ts, "end": te},
            "window_coordinates": {"start": ws, "end": we} if window is not None else None,
            "within_window": within,
            "ownership": "target_affecting" if left_owned or right_owned else "context_witness_only",
            "affected_target_edge": edge,
        }
        for kind in kinds:
            findings.append(warning(kind, **values, morphology_required="potential" in kind,
                                    candidate_basis="source_spelling_only"))
        if (left_owned or right_owned) and window is not None and not within:
            findings.append(warning("review_window_clips_source_boundary_evidence", **values))

    for side, edge, target_edge, step in (("left", ws, ts, -1), ("right", we, te, 1)):
        between = text[edge:target_edge] if side == "left" else text[target_edge:edge]
        if any(not _separator(char) for char in between):
            continue
        position = edge - 1 if side == "left" else edge
        while 0 <= position < len(text) and _separator(text[position]):
            position += step
        if not 0 <= position < len(text):
            continue
        values = {"source_offset": position, "window_edge_offset": edge,
                  "affected_target_edge": side, "neighbor_source_character": text[position],
                  "window_present": window is not None}
        findings.append(warning("review_window_neighbor_evidence_missing", **values))
        if text[position].isalnum() and _syllable(text[position]) is None:
            findings.append(warning("review_external_normalization_neighbor", **values))
    if boundary_count and (assumptions["reading_profile"] == "unspecified" or assumptions["pause_assumption"] == "unspecified"):
        findings.append(warning("review_boundary_assumptions_unspecified"))
    return findings


def build_report(cases: Any, *, reading_profile: str = "unspecified", pause_assumption: str = "unspecified") -> dict[str, Any]:
    """구조 실패와 검토 경고를 분리한 보고서를 입력 변경 없이 만듭니다."""
    if not isinstance(reading_profile, str) or not reading_profile.strip():
        raise ValueError("reading_profile은 비어 있지 않은 문자열이어야 합니다")
    if not isinstance(pause_assumption, str) or pause_assumption not in PAUSE_ASSUMPTIONS:
        raise ValueError("지원하지 않는 pause_assumption입니다")
    findings = []
    try:
        validate_cases(cases)
    except ValueError as error:
        findings.append(_finding(None, "case_schema_error", severity="error", message_ko=str(error)))
    else:
        for case in cases:
            explicit = case.get("reference_boundary_assumptions", {})
            if (not isinstance(explicit, dict) or
                    not isinstance(explicit.get("reading_profile", reading_profile), str) or
                    not explicit.get("reading_profile", reading_profile).strip() or
                    not isinstance(explicit.get("pause_assumption", pause_assumption), str) or
                    explicit.get("pause_assumption", pause_assumption) not in PAUSE_ASSUMPTIONS):
                findings.append(_finding(case["id"], "invalid_boundary_assumptions", severity="error"))
                continue
            window_findings, safe = _check_window(case)
            findings.extend(window_findings)
            if safe:
                findings.extend(_inspect_boundaries(case, _assumptions(case, reading_profile, pause_assumption)))
    return {
        "schema_version": 1,
        "cases": len(cases) if isinstance(cases, list) else None,
        "validation_scope": "whole_collection_first_schema_failure_then_per_case_window_checks",
        "coordinate_policy": "source_nfc_codepoints_half_open",
        "default_assumptions": {"reading_profile": reading_profile, "pause_assumption": pause_assumption},
        "contract_errors": sum(row["severity"] == "error" for row in findings),
        "review_warnings": sum(row["severity"] == "review" for row in findings),
        "finding_counts": dict(sorted(Counter(row["kind"] for row in findings).items())),
        "engine_used": False, "gold_generated": False, "input_modified": False,
        "historical_scores_modified": False, "whole_window_accuracy_claimed": False,
        "findings": findings, "limitations_ko": _LIMITATIONS_KO,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="기존 사례 스키마의 UTF-8 JSONL")
    parser.add_argument("--report", type=Path, required=True, help="덮어쓰지 않을 신규 JSON 보고서")
    parser.add_argument("--reading-profile", default="unspecified", help="명시적 읽기 조건 이름; 형태 분석에 사용하지 않음")
    parser.add_argument("--pause-assumption", choices=sorted(PAUSE_ASSUMPTIONS), default="unspecified")
    args = parser.parse_args(argv)
    try:
        payload = args.cases.read_bytes()
        cases = []
        input_error = None
        try:
            for line_number, line in enumerate(payload.decode("utf-8-sig").splitlines(), 1):
                if line.strip():
                    try:
                        cases.append(json.loads(line))
                    except json.JSONDecodeError as error:
                        input_error = _finding(None, "input_json_error", severity="error", line=line_number, message_ko=str(error))
                        break
        except UnicodeDecodeError:
            input_error = _finding(None, "input_encoding_error", severity="error", message_ko="입력은 UTF-8이어야 합니다")
        report = build_report([] if input_error else cases, reading_profile=args.reading_profile,
                              pause_assumption=args.pause_assumption)
        if input_error:
            report.update(cases=None, contract_errors=1, review_warnings=0,
                          finding_counts={input_error["kind"]: 1}, findings=[input_error])
        report["cases_sha256"] = hashlib.sha256(payload).hexdigest()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as error:
        print(f"사전 검토 실행 실패: {error}", file=sys.stderr)
        return 2
    print(json.dumps({key: report[key] for key in ("cases", "cases_sha256", "contract_errors", "review_warnings", "finding_counts")}, ensure_ascii=False))
    return 1 if report["contract_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
