#!/usr/bin/env python3
"""봉인·가족 단위 한국어 G2P challenge의 엔진 출력 점수를 계산합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _json_and_hash(path: Path) -> tuple[dict[str, Any], str]:
    if str(path) == "-":
        raw = sys.stdin.buffer.read()
    else:
        raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _normalize(value: str, policy: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if policy == "nfc_whitespace_collapse":
        return " ".join(value.split())
    if policy == "nfc_whitespace_ignored":
        return "".join(value.split())
    raise ValueError(f"지원하지 않는 정규화 정책: {policy}")


def _matches(output: str | None, accepted: list[str], policy: str) -> bool | None:
    if output is None:
        return None
    candidate = _normalize(output, policy)
    return any(candidate == _normalize(item, policy) for item in accepted)


def _counter_summary(values: list[bool | None]) -> dict[str, int]:
    counts = Counter(values)
    return {
        "total": len(values),
        "matched": counts[True],
        "mismatched": counts[False],
        "missing": counts[None],
    }


def _score(engine_values: list[bool | None], rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    by_category: dict[str, list[bool | None]] = defaultdict(list)
    by_family: dict[str, list[bool | None]] = defaultdict(list)
    by_source_status: dict[str, list[bool | None]] = defaultdict(list)
    for case, row in zip(rows, engine_values):
        by_category[case["category"]].append(row)
        by_family[case["family_id"]].append(row)
        by_source_status[case.get("source_status", "unspecified")].append(row)

    families = {
        family_id: {
            **_counter_summary(values),
            "all_cases_match": bool(values) and all(value is True for value in values),
        }
        for family_id, values in sorted(by_family.items())
    }
    complete_families = sum(item["all_cases_match"] for item in families.values())
    return {
        "overall": _counter_summary(engine_values),
        "categories": {
            name: _counter_summary(values) for name, values in sorted(by_category.items())
        },
        "families": families,
        "family_summary": {
            "total": len(families),
            "all_cases_match": complete_families,
            "at_least_one_mismatch_or_missing": len(families) - complete_families,
        },
        "source_status": {
            name: _counter_summary(values)
            for name, values in sorted(by_source_status.items())
        },
        "scoring_note": (
            f"{key}: 모든 challenge 사례를 분모에 포함하고, 각 사례의 허용 발음 중 하나와 "
            "정규화 후 정확히 일치할 때만 일치로 계산합니다."
        ),
    }


def _attribution(case: dict[str, Any], item: dict[str, Any], accepted: list[str]) -> str:
    policy = case.get("normalization", "nfc_whitespace_collapse")
    prod = item.get("production_integration", {}).get("output")
    prod_match = _matches(prod, accepted, policy)
    controlled = item.get("controlled_correct_analysis", {})
    controlled_output = controlled.get("output")
    controlled_match = _matches(controlled_output, accepted, policy)

    if prod_match is True:
        return "production_matches_reference"
    if prod_match is None:
        return "production_output_missing"
    if (
        case.get("morphology_dependence") == "relevant"
        and controlled.get("analysis_status") == "verified_correct"
        and controlled_match is True
    ):
        return "upstream_kiwi_candidate"
    if case.get("morphology_dependence") == "not_relevant":
        return "rule_engine_candidate"
    if (
        case.get("morphology_dependence") == "relevant"
        and controlled.get("analysis_status") == "verified_correct"
        and controlled_match is False
    ):
        return "rule_engine_candidate_after_controlled_analysis"
    return "ambiguous_attribution"


def _validate_challenge(cases_doc: dict[str, Any]) -> None:
    cases = cases_doc["cases"]
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("모든 사례에는 비어 있지 않은 문자열 id가 필요합니다")
    if len(ids) != len(set(ids)):
        raise ValueError("challenge 사례 id가 중복되었습니다")

    inputs: dict[str, str] = {}
    families: dict[str, dict[str, Any]] = {}
    category_splits: Counter[tuple[str, str]] = Counter()
    for case in cases:
        required = ("input", "split", "category", "family_id", "context_level", "context_type", "accepted_pronunciations", "sources")
        missing = [key for key in required if key not in case]
        if missing:
            raise ValueError(f"{case['id']}: 필수 필드 누락: {missing}")
        if case["split"] not in {"development", "holdout"}:
            raise ValueError(f"{case['id']}: 지원하지 않는 split: {case['split']}")
        if case["context_level"] not in {"word", "context"}:
            raise ValueError(f"{case['id']}: 지원하지 않는 context_level: {case['context_level']}")
        if case["context_type"] not in {"word", "phrase", "sentence"}:
            raise ValueError(f"{case['id']}: 지원하지 않는 context_type: {case['context_type']}")
        if (case["context_level"] == "word") != (case["context_type"] == "word"):
            raise ValueError(f"{case['id']}: context_level/context_type 조합이 맞지 않습니다")
        if not isinstance(case["accepted_pronunciations"], list) or not case["accepted_pronunciations"]:
            raise ValueError(f"{case['id']}: 허용 발음 집합은 비어 있지 않은 목록이어야 합니다")
        if any(not isinstance(item, str) or not item for item in case["accepted_pronunciations"]):
            raise ValueError(f"{case['id']}: 허용 발음은 비어 있지 않은 문자열이어야 합니다")
        if not isinstance(case["sources"], list) or not case["sources"]:
            raise ValueError(f"{case['id']}: 최소 한 개의 출처가 필요합니다")
        key = _normalize(case["input"], "nfc_whitespace_collapse")
        if key in inputs:
            raise ValueError(f"정규화 후 중복 입력: {inputs[key]} / {case['id']}")
        inputs[key] = case["id"]

        family_id = case["family_id"]
        family = families.setdefault(
            family_id,
            {"split": case["split"], "category": case["category"], "context_levels": set(), "count": 0},
        )
        if family["split"] != case["split"]:
            raise ValueError(f"가족 누수: {family_id}가 split을 가로질렀습니다")
        if family["category"] != case["category"]:
            raise ValueError(f"가족 범주 불일치: {family_id}")
        family["count"] += 1
        family["context_levels"].add(case["context_level"])
        category_splits[(case["category"], case["split"])] += 1

    if cases_doc.get("expected_design") == "cycle01_curated48":
        declared_split = cases_doc.get("split")
        expected = {
            None: {"cases": 48, "families": 24, "per_category": 8, "dev_per_category": 2, "holdout_per_category": 6, "dev_families": 6},
            "development": {"cases": 12, "families": 6, "per_category": 2, "dev_per_category": 2, "holdout_per_category": 0, "dev_families": 6},
            "holdout": {"cases": 36, "families": 18, "per_category": 6, "dev_per_category": 0, "holdout_per_category": 6, "dev_families": 0},
        }.get(declared_split)
        if expected is None:
            raise ValueError(f"cycle01 split 선언이 잘못되었습니다: {declared_split}")
        if len(cases) != expected["cases"] or len(families) != expected["families"]:
            raise ValueError("cycle01 split 사례/가족 수가 사전 등록 설계와 다릅니다")
        if any(item["count"] != 2 for item in families.values()):
            raise ValueError("cycle01의 각 가족은 정확히 사례 두 개여야 합니다")
        if any(item["context_levels"] != {"word", "context"} for item in families.values()):
            raise ValueError("cycle01의 각 가족은 단어와 문맥 사례를 하나씩 가져야 합니다")
        categories = {case["category"] for case in cases}
        if len(categories) != 6 or any(sum(c["category"] == name for c in cases) != expected["per_category"] for name in categories):
            raise ValueError("cycle01 split의 각 6개 범주별 사례 수가 사전 등록 설계와 다릅니다")
        if any(category_splits[(name, "development")] != expected["dev_per_category"] for name in categories):
            raise ValueError("cycle01의 각 범주에는 개발 사례 2개가 필요합니다")
        if any(category_splits[(name, "holdout")] != expected["holdout_per_category"] for name in categories):
            raise ValueError("cycle01의 각 범주별 holdout 사례 수가 사전 등록 설계와 다릅니다")
        if sum(f["split"] == "development" for f in families.values()) != expected["dev_families"]:
            raise ValueError("cycle01 개발 가족 수가 사전 등록 설계와 다릅니다")


def evaluate(cases_doc: dict[str, Any], outputs_doc: dict[str, Any]) -> dict[str, Any]:
    _validate_challenge(cases_doc)
    tested_source = outputs_doc.get("tested_source")
    if not isinstance(tested_source, dict) or not tested_source.get("git_head") or not tested_source.get("production_freeze_sha256"):
        raise ValueError("출력 기록에는 git_head와 production_freeze_sha256가 있는 tested_source가 필요합니다")
    cases = cases_doc["cases"]
    items = outputs_doc.get("items", [])
    output_by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        case_id = item["id"]
        if case_id in output_by_id:
            raise ValueError(f"출력 id 중복: {case_id}")
        output_by_id[case_id] = item

    ids = [case["id"] for case in cases]
    unknown = sorted(set(output_by_id) - set(ids))
    if unknown:
        raise ValueError(f"challenge에 없는 출력 id: {unknown}")

    production_values: list[bool | None] = []
    baseline_values: list[bool | None] = []
    controlled_values: list[bool | None] = []
    scored_rows: list[dict[str, Any]] = []
    attribution_counts: Counter[str] = Counter()
    context_type_values: dict[str, list[bool | None]] = defaultdict(list)

    for case in cases:
        item = output_by_id.get(case["id"], {})
        policy = case.get("normalization", "nfc_whitespace_collapse")
        accepted = case["accepted_pronunciations"]
        production = item.get("production_integration", {}).get("output")
        baseline = item.get("baseline", {}).get("output")
        controlled = item.get("controlled_correct_analysis", {}).get("output")
        production_values.append(_matches(production, accepted, policy))
        baseline_values.append(_matches(baseline, accepted, policy))
        controlled_values.append(_matches(controlled, accepted, policy))
        context_type_values[case["context_type"]].append(production_values[-1])
        attribution = _attribution(case, item, accepted)
        attribution_counts[attribution] += 1
        scored_rows.append(
            {
                "id": case["id"],
                "input": case["input"],
                "split": case["split"],
                "category": case["category"],
                "context_level": case["context_level"],
                "context_type": case["context_type"],
                "family_id": case["family_id"],
                "source_status": case.get("source_status", "unspecified"),
                "accepted_pronunciations": accepted,
                "production_integration": item.get("production_integration", {"output": None}),
                "controlled_correct_analysis": item.get(
                    "controlled_correct_analysis", {"status": "not_run", "output": None}
                ),
                "baseline": item.get("baseline", {"output": None}),
                "matches": {
                    "production_integration": production_values[-1],
                    "controlled_correct_analysis": controlled_values[-1],
                    "baseline": baseline_values[-1],
                },
                "attribution_candidate": attribution,
                "sources": case.get("sources", []),
            }
        )

    # 분할별 보고서에도 모든 사례를 보존하며, 전체 통합 점수의 분모에는 항상 모든 사례를 포함합니다.
    split_reports: dict[str, Any] = {}
    for split in sorted({case["split"] for case in cases}):
        indices = [i for i, case in enumerate(cases) if case["split"] == split]
        subset_cases = [cases[i] for i in indices]
        split_reports[split] = {
            "production_integration": _score(
                [production_values[i] for i in indices], subset_cases, "production_integration"
            ),
            "controlled_correct_analysis": _score(
                [controlled_values[i] for i in indices], subset_cases, "controlled_correct_analysis"
            ),
            "baseline": _score([baseline_values[i] for i in indices], subset_cases, "baseline"),
        }

    return {
        "schema_version": 1,
        "created_utc": outputs_doc.get("created_utc"),
        "challenge_id": cases_doc.get("challenge_id"),
        "scope_statement": cases_doc.get(
            "scope_statement",
            "이 선별 challenge는 대표 표본이 아니며 전체 정확도나 전 구현체 중 최고임을 증명하지 않습니다.",
        ),
        "tested_source": outputs_doc.get("tested_source", {}),
        "manifest_sha256": outputs_doc.get("manifest_sha256"),
        "normalization_policy": "NFC + 사례별 공백 정책; 길이 기호/문장 부호는 자동 삭제하지 않음",
        "overall_integration_includes_all_cases": _score(
            production_values, cases, "production_integration"
        ),
        "baseline_includes_all_cases": _score(baseline_values, cases, "baseline"),
        "controlled_correct_analysis_includes_all_cases": _score(
            controlled_values, cases, "controlled_correct_analysis"
        ),
        "attribution_candidate_counts": dict(sorted(attribution_counts.items())),
        "production_integration_by_context_type": {
            name: _counter_summary(values) for name, values in sorted(context_type_values.items())
        },
        "splits": split_reports,
        "rows": scored_rows,
        "family_split_validation_scope": {
            "declared_family_ids_cross_splits": False,
            "lexical_family_novelty_vs_prior_code_tests_or_runtime_lexicon": "not_established",
            "blind_holdout_status": "not_established; public protocol disclosure must be reviewed separately",
        },
        "limits": [
            "사례는 선별한 48개 진단 입력이며 한국어 전체 사용을 대표하지 않습니다.",
            "이 큐레이션 challenge는 대표 표본이 아니며 정확도 추정이나 전 구현체 중 최고임을 증명하지 않습니다.",
            "검증기는 선언된 family_id가 split을 가로지르지 않는지만 확인합니다. 기존 소스 코드·시험·실행 사전과의 어휘 가족 신규성은 증명하지 않습니다.",
            "검증기는 공개 프로토콜의 기대 발음 공개 여부를 판정하지 않습니다. 공개 예시가 있는 자료를 blind holdout으로 부르지 마세요.",
            "결과는 이 challenge에서의 비교이며 전역 최고 또는 완전성의 증거가 아닙니다.",
            "Kiwi 오류 후보는 controlled correct-analysis 차이를 포함한 후속 검토 대상으로만 표시합니다.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, required=True,
        help="사례 JSON 경로 또는 - (표준 입력; holdout 복호화 내용을 디스크에 쓰지 않을 때 사용)",
    )
    parser.add_argument("--outputs", type=Path, required=True, help="엔진별 원시 출력 JSON 경로")
    parser.add_argument("--report", type=Path, required=True, help="결과 보고서 JSON 경로")
    args = parser.parse_args()

    cases_doc, cases_hash = _json_and_hash(args.cases)
    outputs_doc, outputs_hash = _json_and_hash(args.outputs)
    report = evaluate(cases_doc, outputs_doc)
    report["input_hashes"] = {
        "cases_sha256": cases_hash,
        "outputs_sha256": outputs_hash,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "cases": len(cases_doc["cases"]),
                "production": report["overall_integration_includes_all_cases"]["overall"],
                "source": outputs_doc.get("tested_source", {}),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
