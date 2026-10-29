"""동결 경계 참조를 선택한 src에서 실행하고 부분 관찰과 개발 교정을 구분한다."""

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
import shutil
import subprocess
import sys


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run(arguments, root):
    return subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-B", *map(str, arguments)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
        timeout=180,
    )


def _assert_bound_action_fields(case_id, expected, check, observation, aggregate_state):
    """실제로 연결된 동작만 엄격히 비교하고 없는 관찰은 부분 미연결로 보존한다."""
    pair = check["source_pair"]
    records = [record for record in observation.get("boundaries", []) if record["source_pair"] == pair]
    eligible = any(record.get("native_evidence", {}).get("boundary_record", {}).get("applicability") == "eligible"
                   for record in records)
    eligible = eligible or any(
        event.get("boundary", {}).get("pair") == pair and event.get("applicability") == "eligible"
        for call in observation.get("native_evidence", {}).get("apply_calls", []) for event in call.get("events", [])
    )
    for key in ("applicability", "selected_article", "consumption_count", "forbidden_articles"):
        if key not in expected:
            continue
        state = check["fields"][key]
        assert state in ("passed", "unbound"), (case_id, key, check)
        observed_key = "consumed_articles" if key == "forbidden_articles" else key
        bound = any(observed_key in record.get("values", {}) for record in records)
        if bound or eligible:
            assert state == "passed", (case_id, key, check)
        elif state == "unbound":
            assert aggregate_state == "partial_unbound", (case_id, key, aggregate_state)


def test_frozen_rule_boundaries_with_explicit_partial_observations(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fixture = Path(__file__).parent / "fixtures/rule_boundaries"
    manifest = _read(fixture / "PORTABLE_FIXTURE_FREEZE.json")
    for name, expected in manifest["sha256"].items():
        assert _sha(fixture / name) == expected, name
    reference = tmp_path / "rule_boundaries"
    shutil.copytree(fixture, reference)
    here = reference / "independent_refs"
    raw_path = here / "runtime_observation.json"
    process = _run(
        [here / "evaluator_runner_v6.py", "--run-runtime", "--src", root / "src",
         "--input-mode", "controlled_structure_supplied", "--include-supplemental-guard",
         "--report", raw_path], root,
    )
    # 원래 잘못 적힌 한 행 정답 때문에 원시 실행의 종료 코드는 1일 수 있다.
    assert process.returncode in (0, 1) and raw_path.exists(), process.stdout + process.stderr
    raw_hash = _sha(raw_path)
    result = _read(raw_path)
    assert result.get("runner_version") == "r42-native-source-pinned-v6-cold-semantic-view", result
    assert result.get("acceptance") != "source_isolation_or_runtime_abort", result
    origin = result["source_origin"]
    assert Path(origin["resolved_src"]) == (root / "src").resolve()
    assert origin["source_unchanged"] is True and not origin["violations"]
    assert origin["imported_module_count"] > 0
    assert origin["project_fallback_policy"] == "deny_installed_and_editable_fallback"

    scope_path = here / "partial_observation_scope.json"
    scoped = _run(
        [here / "observation_scope_postprocess_v1.py", "--input", raw_path, "--report", scope_path], root,
    )
    assert scoped.returncode == 0, scoped.stdout + scoped.stderr
    scope = _read(scope_path)
    assert scope["preserved_input"]["sha256"] == raw_hash == _sha(raw_path)
    assert scope["partial_observation_only"] is True
    assert scope["full_78_of_78_proof_claim"] is False
    assert scope["one_row_phone_correction_applied"] is False

    spec = importlib.util.spec_from_file_location(
        "rule_boundary_frozen_phone_correction", reference / "score_phone_correction_v1.py",
    )
    scoring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scoring)
    policy = scoring.load_frozen_policy(
        here / "normative_disposition_A17_14_v1.json", here / "EVALUATOR_V5_FREEZE.json",
    )
    assert policy["original_cases_sha256"] == _sha(here / "cases.jsonl")
    assert policy["original_freeze_sha256"] == _sha(here / "FREEZE.json")
    phone_score = scoring.score_result(result, policy)
    assert phone_score["one_row"]["development_corrected_phone_state"] == "passed", phone_score
    assert phone_score["original_gold_modified"] is False
    assert phone_score["non_phone_metrics_modified"] is False
    assert phone_score["full_boundary_proof_claim"] is False

    cases = [json.loads(line) for line in (here / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    frozen = _read(here / "FREEZE.json")
    rows = {row["case_id"]: row for row in result["rows"]}
    views = {row["case_id"]: row for row in scope["rows"]}
    assert len(cases) == frozen["cases"] == len(rows) == len(views) == 78
    assert set(rows) == set(views) == {case["case_id"] for case in cases}
    assert Counter(row["evidence_scope"] for row in rows.values()) == {
        "generalization": 42, "guard": 18, "migration_only": 18,
    }
    transitions = Counter()
    partial_fields = Counter()
    for case in cases:
        case_id = case["case_id"]
        row, view = rows[case_id], views[case_id]
        assert "observation" in row, row
        observation = row["observation"]
        metrics = view["observation_metrics"]
        for key in ("public_route", "supplied_analysis_capture", "whole_phone_override_audit", "native_event_integrity"):
            assert metrics.get(key) == "passed", (case_id, key, metrics)
        assert metrics["rule_trace_capture"] == "captured", case_id
        assert metrics["declared_compound_input_delivery"] in ("passed", "not_required"), case_id
        assert observation["native_api_available"]["certify"] is True, case_id
        assert observation["native_api_available"]["apply"] is True, case_id
        assert metrics == {**row["metrics"], "native_boundary_fields": metrics["native_boundary_fields"]}
        assert view["raw_v6_metrics"] == row["metrics"]
        assert view["raw_v5_comparison"] == row.get("raw_v5_comparison", {})

        # 실제 발음은 동결 문자열로 확인하며 한 행 교정은 별도 축으로 남긴다.
        original = case["expected"]["allowed_phones"]
        actual = observation["phone"]
        raw_state = "not_required" if original is None else "passed" if actual in original else "failed"
        assert row["metrics"]["phone"] == raw_state, case_id
        if case_id == policy["case_id"]:
            assert original == policy["original_allowed_phones"]
            assert actual in policy["development_corrected_allowed_phones"], case_id
        elif original is not None:
            assert actual in original, case_id
        if original is not None and case["input"]["source"] not in original:
            transitions[case["family"]] += 1
        if case["expected"]["whole_phone_override"] == "forbidden":
            assert observation["whole_phone_override_used"] is False, case_id
        else:
            assert type(observation["whole_phone_override_used"]) is bool, case_id
        assert not row.get("native_consistency_violations"), case_id
        for record in observation.get("boundaries", []):
            values = record.get("values", {})
            count = values.get("consumption_count")
            assert type(count) is int and 0 <= count <= 1, (case_id, values)
            if count:
                native = record["native_evidence"]["boundary_record"]
                assert native["status"] == "verified" and native["applicability"] == "eligible", case_id
                assert values["consumed_articles"] and set(values["consumed_articles"]) <= {"15", "17", "29"}, case_id

        state = metrics["native_boundary_fields"]
        if state == "premise_not_met":
            assert row["absence_premise_disposition"]
            assert all(item["state"] == "premise_not_met" and item["negative_guard_credit"] is False
                       for item in row["absence_premise_disposition"])
        elif state == "unbound_input":
            assert row["conditional_guard"]["state"] == "unbound_input"
            assert observation["input_preconditions"]["semantic_identity_delivery"] == "not_delivered"
        elif state == "scope_precondition_changed":
            assert metrics["development_copular_scope_authority"] == "passed"
            assert row["copular_scope_disposition"]["scope_authority"] == "verified_scope_authority"
            assert not row["copular_scope_disposition"]["wrong_applied_article_pairs"]
        else:
            assert state in ("passed", "partial_unbound", "not_required"), (case_id, view)
            checks = view["observation_boundary_checks"]
            for expected in case["expected"]["boundaries"]:
                matching = [check for check in checks if check["source_pair"] == expected["source_pair"]]
                assert matching, case_id
                for check in matching:
                    assert "failed" not in check["fields"].values(), (case_id, check)
                    _assert_bound_action_fields(case_id, expected, check, observation, state)
                    partial_fields.update(key for key, value in check["fields"].items() if value == "unbound")
        for metric, value in metrics.items():
            if metric != "phone" or case_id != policy["case_id"]:
                assert value != "failed", (case_id, metric, view)

    for family in ("article15_semantic_eochi", "article17_formal_i_hi", "article29_nominal_compound"):
        assert transitions[family] > 0, family
    assert partial_fields, "미연결 메타데이터를 완전 증명으로 축약하지 않는다."
    constructors = result["constructor_rows"]
    invalid = [json.loads(line) for line in (here / "constructor_invalid.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(constructors) == frozen["constructor_invalid_cases"] == len(invalid) == 3
    assert {row["case_id"] for row in constructors} == {case["case_id"] for case in invalid}
    assert all(row["passed"] for row in constructors), constructors
    supplemental = result["supplemental_metadata_guard"]
    assert supplemental["metadata_guard_state"] == "passed", supplemental
    assert supplemental["phone_gold"] is None
    assert supplemental["pronunciation_accuracy_credit"] is False
    assert supplemental["normative_generalization_credit"] is False
    assert _sha(raw_path) == raw_hash
