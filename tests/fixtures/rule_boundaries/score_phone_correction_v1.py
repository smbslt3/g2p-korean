"""동결된 한 행의 개발 정답 교정을 원시 발음 점수와 별도로 계산한다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


VERSION = "r42-frozen-one-row-phone-score-v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_frozen_policy(policy_path, freeze_path):
    policy_path, freeze_path = Path(policy_path), Path(freeze_path)
    manifest = json.loads(freeze_path.read_text(encoding="utf-8"))
    expected = manifest.get("sha256", {}).get(policy_path.name)
    if not expected or sha(policy_path) != expected:
        raise ValueError("한 행 교정 정책의 기존 동결 해시가 필요하다.")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if (policy.get("classification") != "development_reference_correction"
            or policy.get("original_gold_changed") is not False
            or policy.get("untouched_holdout") is not False
            or policy.get("effective_in_default_runner") is not False):
        raise ValueError("원본과 분리된 기존 개발 교정 정책만 허용한다.")
    if not policy.get("development_corrected_allowed_phones"):
        raise ValueError("기존 동결 정책에 교정 정답이 없다.")
    return policy


def score_result(result, policy):
    """실제 관찰 phone만 교정 정답과 비교하며 나머지 점수는 변경하지 않는다."""
    rows = result.get("rows", [])
    matches = [row for row in rows if row.get("case_id") == policy["case_id"]]
    if len(matches) != 1:
        raise ValueError("교정 대상 행은 정확히 하나여야 한다.")
    target = matches[0]
    if "phone" not in target.get("observation", {}):
        raise ValueError("보존된 실제 phone 관찰이 필요하다.")
    corrected_state = "passed" if target["observation"]["phone"] in policy["development_corrected_allowed_phones"] else "failed"
    raw, corrected = defaultdict(Counter), defaultdict(Counter)
    for row in rows:
        scope = row["evidence_scope"]
        original = row.get("metrics", {}).get("phone", "unbound")
        raw[scope][original] += 1
        corrected[scope][corrected_state if row is target else original] += 1
    return {
        "version": VERSION, "classification": "development_reference_correction",
        "raw_phone_counts_by_scope": {scope: dict(values) for scope, values in raw.items()},
        "development_corrected_phone_counts_by_scope": {scope: dict(values) for scope, values in corrected.items()},
        "one_row": {"case_id": policy["case_id"], "raw_phone_state": target.get("metrics", {}).get("phone", "unbound"),
                    "development_corrected_phone_state": corrected_state, "comparison_scope": policy["comparison_scope"]},
        "original_result_modified": False, "original_gold_modified": False,
        "non_phone_metrics_modified": False, "untouched_holdout_claim": False,
        "full_boundary_proof_claim": False, "new_runtime_executed": False,
    }


def synthetic_preflight(policy):
    case_id = policy["case_id"]
    original = {"rows": [
        {"case_id": case_id, "evidence_scope": "synthetic", "metrics": {"phone": "failed", "other": "failed"},
         "observation": {"phone": policy["development_corrected_allowed_phones"][0]}},
        {"case_id": "OTHER", "evidence_scope": "synthetic", "metrics": {"phone": "failed"}, "observation": {"phone": "모의"}},
    ]}
    before = copy.deepcopy(original)
    scored = score_result(original, policy)
    checks = {
        "원시_실패_두개_보존": scored["raw_phone_counts_by_scope"]["synthetic"] == {"failed": 2},
        "한행만_별도교정": scored["development_corrected_phone_counts_by_scope"]["synthetic"] == {"passed": 1, "failed": 1},
        "원래객체_불변": original == before,
        "전체증명으로_승격하지않음": not scored["full_boundary_proof_claim"],
    }
    return {"synthetic_only": True, "checks": checks, "all_checks_passed": all(checks.values()), "new_runtime_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-freeze", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--preflight-synthetic", action="store_true")
    args = parser.parse_args()
    if args.preflight_synthetic == (args.result is not None):
        parser.error("보존된 결과 또는 모의 점검 하나를 선택한다.")
    if args.report.exists():
        parser.error("기존 결과를 덮어쓸 수 없다.")
    policy = load_frozen_policy(args.policy, args.policy_freeze)
    if args.preflight_synthetic:
        result = synthetic_preflight(policy)
    else:
        before = sha(args.result)
        result = score_result(json.loads(args.result.read_text(encoding="utf-8")), policy)
        if sha(args.result) != before:
            raise ValueError("입력 결과가 읽는 동안 변경되었다.")
        result["saved_result_sha256"] = before
    result.update({"policy_sha256": sha(args.policy), "policy_freeze_sha256": sha(args.policy_freeze)})
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("all_checks_passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
