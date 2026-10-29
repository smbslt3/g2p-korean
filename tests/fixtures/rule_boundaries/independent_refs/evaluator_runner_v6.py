"""원시 v5 비교를 보존한 채 cold 의미 투영과 한 메타데이터 가드를 적용한다."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaluator_runner_v5 as previous
import evaluator_binding_v3 as binding
import evaluator_runner_v2 as isolation
import evaluator_runner_v1 as utilities
import semantic_projection_v1 as semantic
import run_refs as frozen


RUNNER_VERSION = "r42-native-source-pinned-v6-cold-semantic-view"
FACTS_PATH = HERE.parent / "contract/Opaque_Canonical_Lexical_Structure_Facts.json"
API_PATH = HERE.parent / "cleanroom/boundary_rules/candidate06/Boundary_API_KO.json"
GUARD_PATH = HERE / "Supplemental_Unknown_Owner_Metadata_Guard_v1.json"
ORIGINAL_SCORE = previous.score


def facts():
    return json.loads(FACTS_PATH.read_text(encoding="utf-8"))["facts"]


def score(case, observation):
    result = ORIGINAL_SCORE(case, observation)
    result["raw_v5_comparison"] = {k: copy.deepcopy(result[k]) for k in ("metrics", "boundary_checks", "acceptance") if k in result}
    projected = []
    records = observation.get("boundaries", [])
    for expected in case["expected"]["boundaries"]:
        matching = [r for r in records if r["source_pair"] == expected["source_pair"]]
        if matching:
            projected.extend(semantic.compare(expected, r) for r in matching)
        else:
            projected.append({"source_pair": expected["source_pair"], "fields": {k: "unbound" for k in expected}, "native_consistency_violations": []})
    result["semantic_boundary_checks"] = projected
    all_states = [state for row in projected for state in row["fields"].values()]
    result["metrics"]["native_boundary_fields"] = ("not_required" if not projected else "failed" if "failed" in all_states else "partial_unbound" if "unbound" in all_states else "passed")
    violations = [v for row in projected for v in row["native_consistency_violations"]]
    result["metrics"]["native_event_integrity"] = "failed" if violations else "passed"
    result["native_consistency_violations"] = violations
    if result.get("conditional_guard", {}).get("state") == "unbound_input":
        result["metrics"]["native_boundary_fields"] = "unbound_input"
    authorities = {b.get("authority") for b in case["expected"]["boundaries"]}
    if "missing_internal_structure" in authorities:
        coverage = [semantic.exact_fact_coverage(case["input"], semantic.raw_boundary(r), facts()) for r in records]
        coverage = [c for c in coverage if c is not None]
        if coverage:
            result["absence_premise_disposition"] = coverage
            result["metrics"]["native_boundary_fields"] = "premise_not_met"
            # 정확 이/히 구조가 실제 적용된 경우 다른 규칙 가족으로 바꾸지 않는다.
            wrong = [a for r in records for a in r.get("values", {}).get("consumed_articles", []) if a != "17"]
            if wrong:
                result["metrics"]["native_event_integrity"] = "failed"
                result["native_consistency_violations"].append("정확 형식 이/히 사실에서 다른 조항을 실제 소비했다.")
    if "contract_scope_deferred_vcp" in authorities and semantic.typed_copula(case["input"]):
        scope = semantic.copular_scope(case["input"], records, observation.get("native_api_available", {}).get("certify", False))
        result["copular_scope_disposition"] = scope
        result["metrics"]["native_boundary_fields"] = "scope_precondition_changed"
        result["metrics"]["development_copular_scope_authority"] = (
            "passed" if scope["scope_authority"] == "verified_scope_authority" else "unbound" if scope["scope_authority"] == "unbound_native_api" else "failed")
        if scope["wrong_applied_article_pairs"]:
            result["metrics"]["native_event_integrity"] = "failed"
    result["available_metrics_passed"] = not any(v == "failed" for v in result["metrics"].values())
    incomplete = any(v in ("unbound", "unbound_input", "partial_unbound", "premise_not_met", "scope_precondition_changed") for v in result["metrics"].values())
    result["acceptance"] = "available_metrics_failed" if not result["available_metrics_passed"] else "consult_cold_scope_and_unbound_dispositions" if incomplete else "passed_bound_requirements"
    result["note_ko"] = "원시 v5 비교와 의미 투영을 함께 보존한다. 선행 조건 미충족을 옛 가드 통과로 세지 않는다."
    return result


def synthetic_preflight():
    prior = previous.synthetic_preflight()
    checks = {"이전_입력수리_검증_보존": prior["all_checks_passed"]}

    def record(status="verified", app="not_required", article="17", count=0, role="formal_particle"):
        raw = {"pair": [0, 1], "status": status, "applicability": app, "article": article, "role": role,
               "donor_origin": None, "recipient_origins": [], "grammar": None}
        return {"source_pair": [0, 1], "values": {"consumption_count": count, "consumed_articles": [article] * count, "role": role},
                "native_evidence": {"boundary_record": raw}}

    negative = {"source_pair": [0, 1], "status": "excluded", "selected_article": None, "consumption_count": 0}
    excluded = semantic.compare(negative, record())
    checks["문법검증과_음운제외_축분리"] = excluded["fields"]["status"] == "passed" and excluded["native_axes"]["grammatical_evidence_status"] == "verified"
    checks["not_required_선택없음"] = excluded["fields"]["selected_article"] == "passed"
    wrong = semantic.compare(negative, record(app="eligible", count=1))
    checks["실제_eligible을_제외로_숨기지않음"] = wrong["fields"]["status"] == "failed" and wrong["fields"]["consumption_count"] == "failed"
    contradiction = semantic.compare(negative, record(count=1))
    checks["not_required_실제소비_모순검출"] = bool(contradiction["native_consistency_violations"])
    blocked = semantic.compare({"source_pair": [0, 1], "status": "verified", "role": "lexical_component", "applicability": "blocked", "consumption_count": 0}, record(status="unresolved", app="blocked", role=None))
    checks["차단전_미계산_역할_미연결"] = blocked["fields"]["role"] == "unbound" and blocked["fields"]["status"] == "unbound"
    checks["차단과_0소비_계속확인"] = blocked["fields"]["applicability"] == "unbound" and blocked["fields"]["consumption_count"] == "passed"
    # 실제 관찰에서는 applicability가 values에도 있으며 그 값은 변경하지 않는다.
    blocked_record = record(status="unresolved", app="blocked", role=None)
    blocked_record["values"]["applicability"] = "blocked"
    checks["관찰된_차단_적용성_비교"] = semantic.compare({"source_pair": [0, 1], "applicability": "blocked", "consumption_count": 0}, blocked_record)["fields"]["applicability"] == "passed"
    conflict = semantic.compare({"source_pair": [0, 1], "status": "unresolved"}, record(status="verified", app="eligible", count=1))
    checks["출처충돌_미해결요구_보존"] = conflict["fields"]["status"] == "failed"
    proof_failure = semantic.compare({"source_pair": [0, 1], "status": "unresolved"}, record(status="unresolved", app="unresolved"))
    checks["미지원_증명_미해결_보존"] = proof_failure["fields"]["status"] == "passed"
    guard = json.loads(GUARD_PATH.read_text(encoding="utf-8"))
    owners = {f["canonical_owner_form"] for f in facts()}
    checks["보충원형_다섯허가소유자_밖"] = guard["input"]["source"] not in owners and len(owners) == 5
    checks["보충가드_발음정답_없음"] = guard["phone_gold"] is None and guard["pronunciation_accuracy_credit"] is False
    empty = {"boundaries": [], "native_api_available": {"certify": True, "apply": True}, "native_evidence": {"certify_calls": [[]], "apply_calls": [{"events": []}]}}
    checks["전체단어_문법실패_요구하지않음"] = semantic.supplemental_guard(guard, empty)["metadata_guard_state"] == "passed"
    bad_identity = record(app="eligible", count=0, role="formal_suffix_i")
    bad_identity["source_pair"] = guard["metadata_assertions"]["pair"]
    checks["철자만의_접미사신원_검출"] = semantic.supplemental_guard(guard, {**empty, "boundaries": [bad_identity]})["metadata_guard_state"] == "failed"
    bad_event = {"boundary": {"pair": guard["metadata_assertions"]["pair"], "article": "17"}, "applicability": "eligible"}
    checks["보충가드_실제잘못소비_검출"] = semantic.supplemental_guard(guard, {**empty, "native_evidence": {"certify_calls": [[]], "apply_calls": [{"events": [bad_event]}]}})["metadata_guard_state"] == "failed"
    checked = next(f for f in facts() if f["id"] == "gudi_adverbial_i")
    native_fact = {"id": checked["id"], "owner_form": checked["canonical_owner_form"], "owner_pos": checked["owner_pos"],
                   "base_span": checked["base"]["span"], "affix_span": checked["affix"]["span"], "role": checked["affix"]["role"], "source_ids": checked["source_ids"]}
    owner_payload = {"canonical_parts": [{"form": checked["canonical_owner_form"], "tag": "MAG"}]}
    raw = {"status": "verified", "surface_proofs": [{"synthetic": True}], "source": "canonical_lexical_structure:" + checked["id"], "lexical_fact": native_fact, "role": checked["affix"]["role"]}
    checks["실제_정확fact_부재전제_분리"] = semantic.exact_fact_coverage(owner_payload, raw, facts())["state"] == "premise_not_met"
    checks["단순_MAG나_다른소유_불충분"] = semantic.exact_fact_coverage({"canonical_parts": [{"form": guard["input"]["source"], "tag": "MAG"}]}, raw, facts()) is None
    checks["실제fact없는_권한_미조작"] = semantic.exact_fact_coverage(owner_payload, {**raw, "lexical_fact": None}, facts()) is None
    checks["위임된_정확fact_원래증거_보존"] = semantic.exact_fact_coverage(owner_payload, {**raw, "source": "legacy_structure_delegation", "applicability": "not_required"}, facts())["state"] == "premise_not_met"
    checks["잘못된_실제역할_감추지않음"] = semantic.exact_fact_coverage(owner_payload, {**raw, "role": "formal_ending_i"}, facts()) is None
    checks["원시_객체_불변"] = raw["status"] == "verified" and raw["lexical_fact"] is native_fact
    checks["생산_모듈_미수입"] = not any(isolation.project_name(name) for name in sys.modules)
    return {"synthetic_only": True, "all_checks_passed": all(checks.values()), "checks": checks,
            "prior_repair_checks": len(prior["checks"]), "prior_native_input_checks": prior["prior_native_input_checks"],
            "source_isolation_checks": prior["source_isolation_checks"], "project_runtime_imported": not checks["생산_모듈_미수입"], "kiwi_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--run-runtime", action="store_true")
    parser.add_argument("--preflight-synthetic", action="store_true")
    parser.add_argument("--input-mode", choices=("tokens_only", "controlled_structure_supplied"), default="tokens_only")
    parser.add_argument("--include-supplemental-guard", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        isolation.require_source_option(args.run_runtime, args.src)
    except ValueError as error:
        parser.error(str(error))
    if args.run_runtime and args.preflight_synthetic:
        parser.error("실제 실행과 모의 점검은 분리합니다.")
    _, cases, invalid = utilities._manifest()
    target = utilities._new_report_path(args.report) if args.report is not None else None
    if args.run_runtime:
        if target is None:
            parser.error("실제 실행에는 새 결과 경로가 필요합니다.")
        session = isolation.SourceSession(args.src)
        try:
            with session:
                binding.prepare_native_imports()
                session.audit()
                with patch.object(previous, "score", score):
                    result = previous.run_records(cases, invalid, session, args.input_mode)
                original_counts = defaultdict(Counter)
                for row in result["rows"]:
                    for metric, state in row.get("raw_v5_comparison", {}).get("metrics", row["metrics"]).items():
                        original_counts[row["evidence_scope"]][metric + ":" + state] += 1
                result["by_scope_original_v5"] = {scope: dict(counts) for scope, counts in original_counts.items()}
                result["by_scope_adjudicated_v6"] = copy.deepcopy(result["by_scope"])
                if args.include_supplemental_guard:
                    guard = json.loads(GUARD_PATH.read_text(encoding="utf-8"))
                    observation = binding.evaluate(copy.deepcopy(guard["input"]), input_mode=args.input_mode)
                    adjudicated = semantic.supplemental_guard(guard, observation)
                    result["supplemental_metadata_guard"] = {**adjudicated, "observation": observation}
                    if adjudicated["metadata_guard_state"] == "failed":
                        result["available_metrics_passed"] = False
        except Exception as error:
            result = {"available_metrics_passed": False, "acceptance": "source_isolation_or_runtime_abort", "exception": type(error).__name__, "message": str(error)}
        result["source_origin"] = session.receipt()
        result["audit_cadence"] = {"verified_at_import": True, "initial_after_import": True, "per_record_filesystem_audit": False, "final": True}
    elif args.preflight_synthetic:
        result = synthetic_preflight()
    else:
        print(json.dumps({"freeze_valid": True, "main_cases": len(cases), "constructor_invalid": len(invalid), "supplemental_metadata_guards": 1, "runtime_imported": False}, ensure_ascii=False))
        return 0
    frozen.check_freeze()
    result.update({"created_at_utc": datetime.now(timezone.utc).isoformat(), "runner_version": RUNNER_VERSION,
                   "binding_version": binding.BINDING_VERSION, "input_mode": args.input_mode,
                   "reference_version": "original_raw_plus_cold_semantic_adjudication_v1", "phone_reference": "original_frozen_gold_unchanged",
                   "one_row_A17_14_development_correction_auto_applied": False, "supplemental_guard_requested": args.include_supplemental_guard,
                   "python_executable": sys.executable, "python_version": sys.version,
                   "freeze_sha256": utilities._sha(HERE / "FREEZE.json"), "runner_v6_sha256": utilities._sha(HERE / "evaluator_runner_v6.py"),
                   "semantic_projection_sha256": utilities._sha(HERE / "semantic_projection_v1.py"), "prior_v5_freeze_sha256": utilities._sha(HERE / "EVALUATOR_V5_FREEZE.json"),
                   "supplemental_metadata_guard_sha256": utilities._sha(GUARD_PATH), "independent_lexical_facts_sha256": utilities._sha(FACTS_PATH),
                   "approved_native_api_sha256": utilities._sha(API_PATH)})
    if target is not None:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("rows", "constructor_rows", "checks", "source_origin", "supplemental_metadata_guard")}
    if args.preflight_synthetic:
        summary["semantic_check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (result["all_checks_passed"] if args.preflight_synthetic else result["available_metrics_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
