"""보존된 v6 JSON에 관찰 범위만 덧붙이며 런타임과 골드는 읽지 않는다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
VERSION = "r42-saved-v6-partial-observation-v1"
ORIGIN_FIELDS = {
    "donor_origin": ("left_origin", "left_origin_span", "original_coda"),
    "recipient_origins": ("right_origin", "right_origin_span", "original_receiver"),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_action(record, observation):
    """실제 선택ㆍ소비를 관찰 불가 설명으로 감추지 않는다."""
    raw = record.get("native_evidence", {}).get("boundary_record", {})
    values = record.get("values", {})
    count = values.get("consumption_count")
    if raw.get("applicability") == "eligible" or (type(count) is int and count > 0) or values.get("consumed_articles"):
        return True
    for call in observation.get("native_evidence", {}).get("apply_calls", []):
        for event in call.get("events", []):
            if event.get("boundary", {}).get("pair") == raw.get("pair"):
                if event.get("applicability") == "eligible" or event.get("changed") is True or event.get("rule_ids"):
                    return True
    return False


def unavailable_fields(record, observation):
    raw = record.get("native_evidence", {}).get("boundary_record", {})
    if active_action(record, observation):
        return {}, None
    status, app, reason = (raw.get(k) for k in ("status", "applicability", "reason"))
    missing = {}
    category = None
    if status == "verified" and app == "not_required" and reason == "prior_independent_lexical_recipient":
        category = "delegated_recipient_target_not_computed"
    elif (status == "unresolved" and app == "blocked" and reason == "phonological_barrier"
          and raw.get("role") is None and raw.get("donor_origin") is None and not raw.get("recipient_origins")):
        category = "barrier_before_physical_metadata"
        missing["status"] = "차단된 문법 상태는 대상 물리 역할의 검증 여부를 확정하지 않는다."
    elif status == "unresolved" and app == "unresolved" and reason == "whole_surface_evidence_unavailable":
        category = "whole_surface_proof_unavailable"
        missing["authority"] = "source는 입력 출처이며 전체 표면 증명의 강도가 아니다."
    if category is None:
        return {}, None
    if raw.get("role") is None:
        missing["role"] = "대상 물리 역할을 계산하거나 인증하지 않았다."
    for native, projected in ORIGIN_FIELDS.items():
        if not raw.get(native):
            for field in projected:
                missing[field] = "대상 원형 기원을 계산하거나 인증하지 않았다."
    return missing, category


def project_check(check, record, observation):
    projected = copy.deepcopy(check)
    missing, category = unavailable_fields(record, observation)
    changes = []
    for field, reason in missing.items():
        if field in projected.get("fields", {}):
            before = projected["fields"][field]
            projected["fields"][field] = "unbound"
            changes.append({"field": field, "original_state": before, "observation_state": "unbound", "reason_ko": reason})
    if changes:
        raw = record.get("native_evidence", {}).get("boundary_record", {})
        projected["observation_scope"] = {
            "category": category, "changes": changes,
            "raw_native_fields": {key: copy.deepcopy(raw.get(key)) for key in ("status", "applicability", "reason", "source", "role")},
            "source_axis": "input_origin_only" if category == "whole_surface_proof_unavailable" else "native_source_preserved",
            "physical_authority": "unsupported_surface_proof" if category == "whole_surface_proof_unavailable" else "not_computed",
            "positive_role_or_authority_proof_created": False,
        }
    return projected


def process_row(row):
    observation = row.get("observation", {})
    records = observation.get("boundaries", [])
    projected = []
    changed = []
    for check in row.get("semantic_boundary_checks", []):
        matches = [record for record in records if record.get("source_pair") == check.get("source_pair")]
        # 같은 쌍의 여러 반환값을 임의로 골라 불일치를 감추지 않는다.
        updated = project_check(check, matches[0], observation) if len(matches) == 1 else copy.deepcopy(check)
        projected.append(updated)
        if updated.get("observation_scope"):
            changed.append({"source_pair": check["source_pair"], **updated["observation_scope"]})
    metrics = copy.deepcopy(row.get("metrics", {}))
    original_metric = metrics.get("native_boundary_fields")
    if changed and original_metric in ("failed", "passed", "partial_unbound"):
        states = [state for check in projected for state in check.get("fields", {}).values()]
        metrics["native_boundary_fields"] = "failed" if "failed" in states else "partial_unbound" if "unbound" in states else original_metric
    failures = [metric for metric, state in metrics.items() if state == "failed"]
    return {
        "case_id": row["case_id"], "evidence_scope": row["evidence_scope"],
        "raw_v6_metrics": copy.deepcopy(row.get("metrics", {})),
        "raw_v6_acceptance": row.get("acceptance"),
        "raw_v6_semantic_boundary_checks": copy.deepcopy(row.get("semantic_boundary_checks", [])),
        "raw_v5_comparison": copy.deepcopy(row.get("raw_v5_comparison", {})),
        "observation_scope_changes": changed, "observation_boundary_checks": projected,
        "observation_metrics": metrics, "remaining_failed_metrics": failures,
        "classification": "remaining_available_metrics_failed" if failures else "partial_observation_only",
        "raw_native_failures_preserved_in_input": True, "full_boundary_proof_claim": False,
    }


def process_saved(saved):
    rows = [process_row(row) for row in saved.get("rows", [])]
    counts = defaultdict(Counter)
    changed_fields = Counter()
    for row in rows:
        for metric, state in row["observation_metrics"].items():
            counts[row["evidence_scope"]][metric + ":" + state] += 1
        for change in row["observation_scope_changes"]:
            for field in change["changes"]:
                if field["original_state"] != field["observation_state"]:
                    changed_fields[field["field"]] += 1
    return {
        "rows": rows, "by_scope_observation_only": {scope: dict(values) for scope, values in counts.items()},
        "original_by_scope_v5": copy.deepcopy(saved.get("by_scope_original_v5", {})),
        "original_by_scope_v6": copy.deepcopy(saved.get("by_scope_adjudicated_v6", saved.get("by_scope", {}))),
        "changed_field_counts": dict(changed_fields),
        "classification_counts": dict(Counter(row["classification"] for row in rows)),
        "constructor_rows_unchanged": copy.deepcopy(saved.get("constructor_rows", [])),
        "supplemental_metadata_guard_state_unchanged": saved.get("supplemental_metadata_guard", {}).get("metadata_guard_state"),
        "partial_observation_only": True, "full_78_of_78_proof_claim": False,
        "original_available_metrics_passed": saved.get("available_metrics_passed"),
        "one_row_phone_correction_applied": False, "phone_metrics_unchanged": True,
        "new_runtime_executed": False, "new_baseline_executed": False,
        "gold_read_or_modified": False, "native_records_modified": False,
    }


def synthetic_preflight():
    def fixture(reason, status="unresolved", app="unresolved", role=None):
        raw = {"pair": [0, 1], "reason": reason, "status": status, "applicability": app,
               "role": role, "donor_origin": None, "recipient_origins": [], "grammar": {"synthetic": True}, "source": "analysis"}
        record = {"source_pair": [0, 1], "native_evidence": {"boundary_record": raw},
                  "values": {"consumption_count": 0, "consumed_articles": []}}
        check = {"source_pair": [0, 1], "fields": {key: "failed" for key in (
            "role", "status", "authority", "left_origin", "right_origin", "applicability", "consumption_count", "forbidden_articles", "selected_article")},
                 "native_consistency_violations": ["원래 위반 보존"]}
        return raw, record, check, {"boundaries": [record]}

    checks = {}
    raw, rec, chk, obs = fixture("prior_independent_lexical_recipient", "verified", "not_required")
    before = copy.deepcopy((raw, rec, chk, obs))
    out = project_check(chk, rec, obs)
    checks["위임된_새역할과_기원만_미연결"] = all(out["fields"][k] == "unbound" for k in ("role", "left_origin", "right_origin")) and out["fields"]["status"] == "failed"
    checks["기존_객체_불변"] = (raw, rec, chk, obs) == before
    for reason, expected_unbound in (("phonological_barrier", ("role", "status")), ("whole_surface_evidence_unavailable", ("role", "authority"))):
        raw, rec, chk, obs = fixture(reason, app="blocked" if reason == "phonological_barrier" else "unresolved")
        out = project_check(chk, rec, obs)
        checks[reason + "_지정필드만_미연결"] = all(out["fields"][k] == "unbound" for k in expected_unbound)
        checks[reason + "_동작가드_불변"] = all(out["fields"][k] == "failed" for k in ("applicability", "consumption_count", "forbidden_articles", "selected_article"))
        checks[reason + "_기존위반_보존"] = out["native_consistency_violations"] == chk["native_consistency_violations"]
    checks["입력출처를_직접증명으로_승격하지않음"] = out["observation_scope"]["source_axis"] == "input_origin_only" and out["observation_scope"]["physical_authority"] == "unsupported_surface_proof"
    checks["미해결_긍정전이_요구_실패유지"] = out["fields"]["status"] == "failed"
    for mutation, label in (("eligible", "실제_eligible"), ("count", "실제_소비"), ("articles", "실제_조항"), ("event", "실제_반환사건")):
        raw, rec, chk, obs = fixture("whole_surface_evidence_unavailable")
        if mutation == "eligible":
            raw["applicability"] = "eligible"
        elif mutation == "count":
            rec["values"]["consumption_count"] = 1
        elif mutation == "articles":
            rec["values"]["consumed_articles"] = ["17"]
        else:
            obs["native_evidence"] = {"apply_calls": [{"events": [{"boundary": {"pair": [0, 1]}, "applicability": "eligible"}]}]}
        checks[label + "_관찰설명으로_숨기지않음"] = project_check(chk, rec, obs) == chk
    raw, rec, chk, obs = fixture("source_conflict")
    checks["실제_출처충돌_실패유지"] = project_check(chk, rec, obs) == chk
    raw, rec, chk, obs = fixture("prior_independent_lexical_recipient", "verified", "not_required", "wrong_computed_role")
    checks["계산된_잘못역할_실패유지"] = project_check(chk, rec, obs)["fields"]["role"] == "failed"
    raw, rec, chk, obs = fixture("whole_surface_evidence_unavailable")
    row = {"case_id": "SYNTHETIC", "evidence_scope": "synthetic_only", "metrics": {"native_boundary_fields": "failed", "phone": "failed", "native_event_integrity": "failed"},
           "semantic_boundary_checks": [chk], "observation": obs}
    result = process_saved({"rows": [row], "available_metrics_passed": False})
    checks["발음과_실제사건_실패유지"] = result["rows"][0]["observation_metrics"]["phone"] == "failed" and result["rows"][0]["observation_metrics"]["native_event_integrity"] == "failed"
    checks["전체증명_주장없음"] = result["partial_observation_only"] and not result["full_78_of_78_proof_claim"]
    checks["생산모듈_미수입"] = not any(name == "g2p_ko" or name.startswith("g2p_ko.") for name in sys.modules)
    return {"synthetic_only": True, "checks": checks, "all_checks_passed": all(checks.values()), "project_runtime_imported": not checks["생산모듈_미수입"], "kiwi_executed": False}


def new_target(path):
    target = path.resolve()
    if target.parent != HERE or target.exists():
        raise ValueError("독립 참조 폴더의 존재하지 않는 새 결과 파일만 허용한다.")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--preflight-synthetic", action="store_true")
    args = parser.parse_args()
    if args.preflight_synthetic == (args.input is not None):
        parser.error("모의 점검 또는 보존된 JSON 입력 하나를 선택한다.")
    target = new_target(args.report)
    if args.preflight_synthetic:
        result = synthetic_preflight()
    else:
        source = args.input.resolve()
        if source.parent != HERE or source == target:
            parser.error("보존된 입력은 독립 참조 폴더 안의 별도 JSON이어야 한다.")
        before = sha(source)
        saved = json.loads(source.read_text(encoding="utf-8"))
        if saved.get("runner_version") != "r42-native-source-pinned-v6-cold-semantic-view":
            parser.error("원래 v6 결과만 입력으로 허용한다.")
        result = process_saved(saved)
        if sha(source) != before:
            raise ValueError("후처리 도중 보존된 입력이 변경되었다.")
        result["preserved_input"] = {"path": str(source), "sha256": before, "unchanged_after_read": True}
    result.update({"version": VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(), "postprocessor_sha256": sha(Path(__file__))})
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {key: value for key, value in result.items() if key not in ("rows", "checks", "constructor_rows_unchanged")}
    if args.preflight_synthetic:
        summary["synthetic_check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if result.get("all_checks_passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
