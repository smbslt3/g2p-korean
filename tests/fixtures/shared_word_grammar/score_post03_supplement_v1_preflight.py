"""합성 JSON DTO만 사용하여 정책 보완 평가기를 사전 검증한다."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def main():
    path = HERE / "score_post03_supplement_v1.py"
    spec = importlib.util.spec_from_file_location("synthetic_post03_scorer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    supplement = json.loads('''{
      "schema": "r41_independent_policy_supplement.v1",
      "development_stage": "post03_policy_refinement_before_candidate04",
      "untouched_holdout": false,
      "amendments": [{"case_id": "synthetic", "variants": ["fused"],
        "expected_before": {"lexical_status": "unresolved", "final_category": null,
          "assert_category": false, "host": null, "tail": null,
          "surface_status": "unavailable", "n_target": false},
        "expected_after": {"lexical_status": "eligible", "final_category": "verb",
          "assert_category": true, "host": "nominalized", "tail": "nominalized",
          "surface_status": "unavailable", "n_target": true}}]
    }''')
    result = json.loads('''{
      "total": 2, "passed": 1, "failed": 1,
      "by_kind": {"certificate": {"passed": 0, "failed": 1}, "public_gap": {"passed": 1, "failed": 0}},
      "records": [
        {"kind": "certificate", "id": "synthetic:fused", "pass": false,
         "errors": ["lexical_status 불일치", "연음 소비자와 공유 어휘 적격성 불일치", "단어 ㄴ 첨가 소비자와 공유 어휘 적격성 불일치"],
         "observed": {"certificate": {"start": 0, "end": 1, "parts": [["가", "VV"], ["ㅁ", "ETN"]],
           "lexical_status": "eligible", "final_category": "verb", "host_state": "nominalized",
           "tail_state": "nominalized", "surface_status": "unavailable", "reason": "합성 정책 관찰"},
           "liaison_target": true, "n_target": true}},
        {"kind": "public_gap", "id": "synthetic_gap", "pass": true, "errors": [], "observed": {}}
      ]
    }''')
    checks = []

    def check(name, candidate, wanted):
        candidate = json.loads(json.dumps(candidate, ensure_ascii=False))
        before = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        policy_before = json.dumps(supplement, ensure_ascii=False, sort_keys=True)
        scored = module.score_result(candidate, supplement)
        assert scored["ok"] is wanted, name
        assert json.dumps(candidate, ensure_ascii=False, sort_keys=True) == before
        assert json.dumps(supplement, ensure_ascii=False, sort_keys=True) == policy_before
        assert scored["original_raw_counts"] == {key: candidate[key] for key in ("total", "passed", "failed", "by_kind")}
        checks.append({"name": name, "passed": True})
        return scored

    scored = check("보완 대상만 재판정하고 원점수 보존", result, True)
    assert scored["original_raw_counts"]["failed"] == 1
    assert scored["adjudicated_counts"]["failed"] == 0
    other = deepcopy(result)
    other["records"][1].update({"pass": False, "errors": ["합성 다른 행 실패"]})
    other.update(passed=0, failed=2)
    other["by_kind"]["public_gap"] = {"passed": 0, "failed": 1}
    check("다른 행 실패는 그대로 실패", other, False)
    for field in ("start", "end", "parts", "lexical_status", "final_category", "host_state", "tail_state", "surface_status", "reason"):
        missing = deepcopy(result)
        del missing["records"][0]["observed"]["certificate"][field]
        check("증명 필수 필드 누락 " + field, missing, False)
    for field, wrong in (("lexical_status", "unresolved"), ("final_category", "noun"),
                         ("host_state", "predicate"), ("tail_state", "prefinal"),
                         ("surface_status", "verified")):
        mismatch = deepcopy(result)
        mismatch["records"][0]["observed"]["certificate"][field] = wrong
        check("보완 증명 상태 불일치 " + field, mismatch, False)
    for field in ("liaison_target", "n_target"):
        missing = deepcopy(result)
        del missing["records"][0]["observed"][field]
        check("소비자 투영 누락 " + field, missing, False)
        wrong = deepcopy(result)
        wrong["records"][0]["observed"][field] = 1
        check("소비자 투영 정수 우회 금지 " + field, wrong, False)
    invariant = deepcopy(result)
    invariant["records"][0]["errors"].append("원형 출현열 신원 불일치")
    check("보완 행의 다른 불변 조건 실패 보존", invariant, False)
    totals = deepcopy(result)
    totals["failed"] = 0
    check("원본 집계 불일치 거부", totals, False)
    duplicate = deepcopy(result)
    duplicate["records"].append(deepcopy(duplicate["records"][1]))
    duplicate.update(total=3, passed=2)
    duplicate["by_kind"]["public_gap"]["passed"] = 2
    check("중복 원본 행 거부", duplicate, False)
    report = {
        "schema": "r41_post03_score_adapter_preflight.v1", "passed": True,
        "synthetic_dto_json_only": True, "project_runtime_or_g2p_kiwi_executed": False,
        "actual_result_or_candidate_source_read": False,
        "adapter_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "checks": checks,
    }
    output = HERE / "score_post03_supplement_v1_preflight.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": True, "synthetic_checks": len(checks), "adapter_sha256": report["adapter_sha256"]}))


if __name__ == "__main__":
    main()
