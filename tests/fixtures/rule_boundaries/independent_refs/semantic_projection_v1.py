"""원시 증거는 보존하고 승인된 문법/음운/선행 조건 축만 구분한다."""

from __future__ import annotations


def raw_boundary(record):
    return record.get("native_evidence", {}).get("boundary_record", {})


def axes(raw):
    app = raw.get("applicability")
    grammar = raw.get("status")
    logical = "excluded" if grammar == "verified" and app == "not_required" else app
    selected = raw.get("article") if app == "eligible" else None
    return {"grammatical_evidence_status": grammar, "candidate_article": raw.get("article"),
            "applicability": app, "logical_phonological_eligibility": logical,
            "selected_article": selected}


def compare(expected, record):
    raw = raw_boundary(record)
    view = axes(raw)
    values = record.get("values", {})
    blocked = raw.get("applicability") == "blocked"
    donor_missing = raw.get("donor_origin") is None
    recipient_missing = not raw.get("recipient_origins")
    missing = set()
    if blocked:
        if raw.get("role") is None:
            missing.add("role")
        if donor_missing:
            missing.update(("left_origin", "left_origin_span", "original_coda"))
        if recipient_missing:
            missing.update(("right_origin", "right_origin_span", "original_receiver"))
        if raw.get("role") is None and donor_missing and recipient_missing and raw.get("grammar") is None:
            missing.add("status")
    checks, compared = {}, {}
    for key, wanted in expected.items():
        if key in missing:
            checks[key] = "unbound"
            compared[key] = {"axis": "not_computed_before_barrier", "raw": raw.get(key)}
            continue
        if key == "status" and wanted == "excluded" and raw.get("status") == "verified" and raw.get("applicability") == "not_required":
            actual = view["logical_phonological_eligibility"]
            compared[key] = {"axis": "logical_phonological_eligibility", "raw_grammatical_status": raw.get("status"), "value": actual}
        elif key == "status":
            actual = raw.get("status")
            compared[key] = {"axis": "grammatical_evidence_status", "value": actual}
        elif key == "selected_article":
            actual = view["selected_article"]
            compared[key] = {"axis": "selected_rule_from_applicability", "candidate_article": raw.get("article"), "value": actual}
        elif key == "forbidden_articles":
            if "consumed_articles" not in values:
                checks[key] = "unbound"
            else:
                checks[key] = "failed" if set(wanted).intersection(values["consumed_articles"]) else "passed"
            continue
        elif key in values:
            actual = values[key]
        else:
            checks[key] = "unbound"
            continue
        checks[key] = "passed" if actual == wanted else "failed"
    violations = []
    consumed = values.get("consumption_count")
    if type(consumed) is int and consumed > 0:
        if raw.get("applicability") != "eligible":
            violations.append("not_required/blocked/unresolved 경계에 실제 소비가 있다.")
        if raw.get("status") != "verified":
            violations.append("문법 근거가 검증되지 않은 경계에 실제 소비가 있다.")
    return {"source_pair": expected["source_pair"], "fields": checks, "comparison_axes": compared,
            "native_axes": view, "native_consistency_violations": violations}


def typed_copula(payload):
    parts = payload.get("canonical_parts", [])
    for index, part in enumerate(parts):
        if part["form"] == "이" and part["tag"] == "VCP" and index > 0 and index + 1 < len(parts):
            return all(p["tag"] in ("NNG", "NNP", "NNB", "NP", "NR") for p in parts[:index]) and all(p["tag"].startswith("E") for p in parts[index + 1:])
    return False


def exact_fact_coverage(payload, raw, independent_facts):
    native = raw.get("lexical_fact")
    if not isinstance(native, dict) or raw.get("status") != "verified" or not raw.get("surface_proofs"):
        return None
    for fact in independent_facts:
        source = raw.get("source")
        direct = source == "canonical_lexical_structure:" + fact["id"]
        delegated = source == "legacy_structure_delegation" and raw.get("applicability") == "not_required"
        if native.get("id") != fact["id"] or not (direct or delegated):
            continue
        if (native.get("owner_form") != fact["canonical_owner_form"] or native.get("base_span") != fact["base"]["span"]
                or native.get("affix_span") != fact["affix"]["span"] or native.get("role") != fact["affix"]["role"]
                or raw.get("role") != native.get("role")):
            continue
        owners = [p for p in payload["canonical_parts"] if p["form"] == native["owner_form"] and p["tag"] in native.get("owner_pos", []) and p["tag"] in fact["owner_pos"]]
        sources = set(native.get("source_ids", []))
        if not owners or not sources or not sources.issubset(fact["source_ids"]):
            continue
        return {"state": "premise_not_met", "fact_id": fact["id"], "owner_form": native["owner_form"],
                "negative_guard_credit": False, "phone_credit": False,
                "reason_ko": "독립적으로 검증된 정확 소유 구조 사실이 실제 lexical_fact에 있다."}
    return None


def copular_scope(payload, records, api_available):
    valid = []
    wrong_events = []
    for record in records:
        raw = raw_boundary(record)
        allowed_source = raw.get("source") == "copular_grammar" or (raw.get("source") == "legacy_structure_delegation" and raw.get("applicability") == "not_required")
        if (allowed_source and raw.get("role") == "formal_particle"
                and raw.get("relation") == "copular_attachment" and raw.get("status") == "verified"
                and raw.get("article") == "17" and raw.get("word_span") == [0, len(payload["source"])]
                and raw.get("grammar") is not None and raw.get("surface_proofs")):
            valid.append({"source_pair": raw["pair"], "authority_verified": True, "candidate_article": "17",
                          "selected_article": axes(raw)["selected_article"], "applicability": raw["applicability"],
                          "native_authority_source": raw.get("source"),
                          "delegation_reason": raw.get("reason") if raw["applicability"] == "not_required" else None})
        if any(a != "17" for a in record.get("values", {}).get("consumed_articles", [])):
            wrong_events.append(record["source_pair"])
    state = "verified_scope_authority" if valid else "scope_authority_not_verified" if api_available else "unbound_native_api"
    return {"state": "development_scope_supplement", "old_negative_guard_credit": False, "phone_gold_added": False,
            "scope_authority": state, "proofs": valid, "wrong_applied_article_pairs": wrong_events,
            "reason_ko": "정확 N+이/VCP+typed E의 새 범위는 이전 보류 가드의 음운 금지가 아니다."}


def supplemental_guard(guard, observation):
    pair = guard["metadata_assertions"]["pair"]
    records = [r for r in observation.get("boundaries", []) if r["source_pair"] == pair]
    bad_roles = []
    bad_events = []
    for record in records:
        raw = raw_boundary(record)
        if raw.get("status") == "verified" and raw.get("role") in guard["metadata_assertions"]["no_verified_internal_formal_suffix_identity"]:
            bad_roles.append(raw)
    for call in observation.get("native_evidence", {}).get("apply_calls", []):
        for event in call["events"]:
            raw = event["boundary"]
            if raw["pair"] == pair and event["applicability"] == "eligible" and raw.get("article") in guard["metadata_assertions"]["no_eligible_rule_events"]:
                bad_events.append(event)
    available = observation.get("native_api_available", {})
    producer_observed = bool(observation.get("native_evidence", {}).get("certify_calls"))
    application_observed = bool(observation.get("native_evidence", {}).get("apply_calls"))
    state = ("failed" if bad_roles or bad_events else "passed" if available.get("certify") and available.get("apply")
             and producer_observed and application_observed else "unbound_native_api")
    return {"case_id": guard["case_id"], "classification": guard["classification"], "metadata_guard_state": state,
            "bad_verified_suffix_records": bad_roles, "bad_eligible_events": bad_events,
            "phone_gold": None, "pronunciation_accuracy_credit": False, "normative_generalization_credit": False}
