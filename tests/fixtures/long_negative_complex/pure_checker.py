"""R48 동결 참고용 순수 DTO 검사. 생산 모듈을 읽거나 실행하지 않는다."""

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path


LICENSED = "licensed_long_negative_complex"
UNRESOLVED = "unresolved_long_negative_complex"
LICENSED_CLASS = "nonassertive_predicate_complex"
UNRESOLVED_CLASS = "unresolved_relation"
NON_MEANING_OBSERVATION_PREFIX = "lexical_domain_observation/"
ARGUMENT_RESTRICTION_PREFIX = "lexical_domain_restriction/argument/"
UNRESOLVED_REASONS = {
    "unsupported_relation", "unsupported_analysis", "conflicting_evidence",
    "unresolved_quote_ownership",
}
# 현 계약에서 확인한 메타데이터 최소 집합이며 전체 의미 클래스 열거가 아니다.
NON_MEANING_CLASSES = {
    LICENSED_CLASS, UNRESOLVED_CLASS, "unresolved_modifier", "neutral_modifier",
}
TOKEN_FIELDS = {"form", "tag", "start", "end", "morphemes"}
CHOICE_FIELDS = {"start", "end", "spelling", "sense_id", "evidence", "reason"}
EVIDENCE_FIELDS = {
    "relation", "target_start", "target_end", "anchor_start", "anchor_end",
    "semantic_class",
}


class ContractError(ValueError):
    """본문 대신 정해진 검사명만 노출한다."""


def _need(condition, code):
    if not condition:
        raise ContractError(code)


def _integer(value):
    return type(value) is int


def _span(start, end, length):
    return _integer(start) and _integer(end) and 0 <= start < end <= length


def _strings(values):
    return isinstance(values, list) and all(isinstance(v, str) for v in values)


def _argument_domain_family(relation):
    if relation == "predicate_argument":
        return True
    if not isinstance(relation, str) or not relation.startswith(ARGUMENT_RESTRICTION_PREFIX):
        return False
    identity = relation[len(ARGUMENT_RESTRICTION_PREFIX):]
    # 출처 ID는 불투명하게 보존한다. 비어 있거나 경로가 더 붙은 형식은 가족이 아니다.
    return bool(identity) and "/" not in identity and not any(c.isspace() for c in identity)


def _restriction_source_identity(relation):
    """선언된 기본 자료 구조만 해제한다. 출처 문자열이나 언어 규칙은 실행하지 않는다."""
    if not isinstance(relation, str):
        return None
    parts = relation.split("/")
    if (len(parts) != 3 or parts[0] != "lexical_domain_restriction" or
            parts[1] not in {"argument", "relative", "nominal"}):
        return None
    identity_hex = parts[2]
    if (not identity_hex or len(identity_hex) % 2 or
            any(c not in "0123456789abcdef" for c in identity_hex)):
        return None
    try:
        identity = ast.literal_eval(bytes.fromhex(identity_hex).decode("utf-8"))
    except (ValueError, SyntaxError, UnicodeError, TypeError, RecursionError, MemoryError):
        return None
    if type(identity) is not tuple or len(identity) != 6:
        return None
    occurrences, predicate, tag, role, supports, domains = identity
    if (type(occurrences) is not tuple or not all(
            type(row) is tuple and len(row) == 2 and all(type(v) is int for v in row)
            for row in occurrences)):
        return None
    if not all(type(value) is str for value in (predicate, tag, role)):
        return None
    if (type(supports) is not tuple or not all(
            type(row) is tuple and len(row) == 3 and all(type(v) is int for v in row)
            for row in supports)):
        return None
    if (type(domains) is not tuple or not all(type(v) is str for v in domains) or
            domains != tuple(sorted(domains))):
        return None
    if parts[1] == "nominal" and (occurrences != () or predicate != "" or tag != ""):
        return None
    # 부호/구간/유일성/빈 P/태그 열거를 새로 강제하지 않고 원자료 순서도 바꾸지 않는다.
    return parts[1], identity


def _specialized_domain_family(relation):
    if relation in {"relative_part_owner", "transaction_price"}:
        return relation
    source = _restriction_source_identity(relation)
    if source is None:
        return None
    kind, identity = source
    return {
        ("relative", "direct_part_owner"): "relative_part_owner",
        ("argument", "transaction_price"): "transaction_price",
    }.get((kind, identity[3]))


def _relation_matches(required, actual):
    # 기존 일반 논항과 두 선언 특수 가족만 요구/금지에서 대칭 인식한다.
    if required == actual or (_argument_domain_family(required) and _argument_domain_family(actual)):
        return True
    family = _specialized_domain_family(required)
    return family is not None and family == _specialized_domain_family(actual)


def _input(record):
    # 원래 배열 순서와 공급 태그/원형/겹친 토큰 좌표를 그대로 보존한다.
    return {key: deepcopy(record[key]) for key in ("text", "tokens", "hard_boundaries")}


def verify_contract(root, freeze_path):
    """허가된 두 클린 문서만 해시 검사한다. 나머지 파일을 탐색하지 않는다."""
    root = Path(root).resolve()
    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    checked = 0
    for relative, digest in freeze["files"].items():
        if Path(relative).name not in {
            "Final_Long_Negative_Complex_Contract_KO.md",
            "Long_Negative_Observable_API_KO.json",
        }:
            continue
        path = (root / relative).resolve()
        _need(path.is_relative_to(root), "contract_path_outside_root")
        _need(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
              "contract_hash_mismatch")
        checked += 1
    _need(checked == 2, "contract_required_documents_missing")
    return checked


def validate_references(document):
    """고정 참고의 필드/좌표/전제만 검사한다. 언어 규칙을 재구현하지 않는다."""
    _need(document.get("format") == "r48_long_negative_refs_v1", "reference_format")
    _need(isinstance(document.get("records"), list), "reference_records")
    record_ids = set()
    for record in document["records"]:
        _need(isinstance(record.get("id"), str) and record["id"] not in record_ids,
              "reference_record_id")
        record_ids.add(record["id"])
        _need(record.get("scope") in {"controlled_analysis", "abstract"}, "record_scope")
        premises = record.get("premises", {})
        _need(premises.get("binding") in {"bound", "partial", "unbound"}, "record_binding")
        _need(_strings(premises.get("required")) and _strings(premises.get("unfulfilled")),
              "record_premise_fields")
        abstract = record["scope"] == "abstract"
        _need((record.get("text") is None if abstract else isinstance(record.get("text"), str)),
              "record_text")
        _need(isinstance(record.get("tokens"), list) and
              isinstance(record.get("hard_boundaries"), list), "record_input_fields")
        if abstract:
            _need(not record["tokens"] and not record["hard_boundaries"] and
                  premises["binding"] == "unbound", "abstract_input_unbound")
        length = len(record["text"]) if not abstract else 0
        for token in record["tokens"]:
            _need(isinstance(token, dict) and set(token) == TOKEN_FIELDS, "token_fields")
            _need(isinstance(token["form"], str) and isinstance(token["tag"], str), "token_strings")
            _need(_span(token["start"], token["end"], length), "token_coordinates")
            _need(isinstance(token["morphemes"], list) and all(
                isinstance(pair, list) and len(pair) == 2 and
                all(isinstance(v, str) for v in pair) for pair in token["morphemes"]),
                "original_morpheme_pairs")
        cuts = record["hard_boundaries"]
        _need(all(_integer(v) and 0 <= v <= length for v in cuts) and
              len(cuts) == len(set(cuts)), "hard_coordinates")
        _need(isinstance(record.get("targets"), list), "reference_targets")
        target_ids, target_keys = set(), set()
        for target in record["targets"]:
            _need(isinstance(target.get("id"), str) and target["id"] not in target_ids,
                  "reference_target_id")
            target_ids.add(target["id"])
            _need(not abstract, "abstract_target_must_remain_unbound")
            _need(_span(target.get("start"), target.get("end"), length) and
                  isinstance(target.get("spelling"), str), "target_coordinates")
            key = (target["start"], target["end"], target["spelling"])
            _need(key not in target_keys, "reference_target_duplicate")
            target_keys.add(key)
            tp, expected = target.get("premises", {}), target.get("expected", {})
            _need(tp.get("semantic") in {"fulfilled", "unfulfilled"} and
                  tp.get("structure") in {"fulfilled", "unfulfilled"} and
                  _strings(tp.get("required")) and _strings(tp.get("unfulfilled")),
                  "target_premise_fields")
            decision = expected.get("decision")
            _need(decision in {"selected", "abstain", "unscored"}, "reference_decision")
            _need((isinstance(expected.get("sense_id"), str) if decision == "selected"
                   else expected.get("sense_id") is None), "reference_sense")
            _need(decision == "unscored" or tp["semantic"] == "fulfilled",
                  "missing_semantic_premise_scored")
            _need(premises["binding"] != "unbound" or decision == "unscored",
                  "unbound_semantics_scored")
            _need(_strings(expected.get("reason_allowed")) and
                  _strings(expected.get("forbidden_relations")), "reference_constraint_lists")
            for field in ("licensed_complexes", "unresolved_complexes"):
                complexes = expected.get(field)
                _need(complexes is None or isinstance(complexes, list), "complex_list")
                # 명시 부재 []는 양성 소유 증명이 아니다. 미공급 구조의 양성 앵커만 금지한다.
                _need(tp["structure"] == "fulfilled" or complexes is None or complexes == [],
                      "missing_structure_premise_scored")
                anchors = set()
                for item in complexes or []:
                    anchor = item.get("anchor")
                    _need(isinstance(anchor, list) and len(anchor) == 2 and
                          _span(*anchor, length), "reference_anchor")
                    _need(anchor[0] in {t["start"] for t in record["tokens"]} and
                          anchor[1] in {t["end"] for t in record["tokens"]},
                          "anchor_original_token_endpoints")
                    _need(not any(anchor[0] < cut < anchor[1] for cut in cuts),
                          "reference_anchor_crosses_hard")
                    _need(type(item.get("count")) is int and item["count"] == 1 and
                          tuple(anchor) not in anchors,
                          "reference_structural_duplicate")
                    anchors.add(tuple(anchor))
            required = expected.get("required_evidence")
            _need(isinstance(required, list), "required_evidence_list")
            for evidence in required:
                _need(evidence.get("relation") is None or
                      (isinstance(evidence["relation"], str) and
                       evidence["relation"] not in {LICENSED, UNRESOLVED}),
                      "ordinary_required_relation")
                _need(evidence.get("semantic_class") is None or
                      isinstance(evidence["semantic_class"], str), "required_class")
                if evidence["relation"] is None:
                    _need(isinstance(evidence["semantic_class"], str) and
                          bool(evidence["semantic_class"]) and
                          evidence["semantic_class"] not in NON_MEANING_CLASSES,
                          "class_only_requires_concrete_ordinary_meaning")
                anchor = evidence.get("anchor")
                _need(anchor is None or (isinstance(anchor, list) and len(anchor) == 2 and
                      _span(*anchor, length)), "required_anchor")
            _need(decision != "selected" or any(
                e["semantic_class"] not in NON_MEANING_CLASSES for e in required),
                "selected_requires_ordinary_meaning_constraint")
    return {"records": len(document["records"]), "reference_shape_valid": True}


def check_record(record, selections, input_before, input_after):
    """원반환을 변경하지 않고 ID/개수/검사명만 반환한다."""
    validate_references({"format": "r48_long_negative_refs_v1", "records": [record]})
    if record["scope"] == "abstract":
        _need(selections is None, "abstract_must_not_execute")
        return {"record_id": record["id"], "status": "not_executed_unbound",
                "targets": [], "failures": [], "semantic_scored": 0}
    failures = []

    def require(condition, code, target_id=None):
        if not condition:
            failures.append({"check": code, "target_id": target_id})

    original = _input(record)
    require(input_before == original, "original_call_input_exact")
    require(input_after == input_before, "call_input_preserved")
    _need(isinstance(selections, list), "selection_array")
    saved = deepcopy(selections)
    length, by_key = len(record["text"]), {}
    evidence_total, ordinary_total = 0, 0
    for selection in selections:
        _need(isinstance(selection, dict) and set(selection) == CHOICE_FIELDS,
              "selection_public_fields")
        _need(_span(selection["start"], selection["end"], length) and
              isinstance(selection["spelling"], str), "selection_coordinates")
        _need((selection["sense_id"] is None or isinstance(selection["sense_id"], str)) and
              isinstance(selection["reason"], str) and isinstance(selection["evidence"], list),
              "selection_public_types")
        key = (selection["start"], selection["end"], selection["spelling"])
        require(key not in by_key, "duplicate_selection")
        by_key[key] = selection
        require((selection["sense_id"] is not None) == (selection["reason"] == "selected"),
                "sense_reason_consistency")
        # 아래는 표지 ID의 직접 누출만 막는다. 유효 뜻의 독립 근거는 참고/소스 검토가 필요하다.
        require(selection["sense_id"] not in {LICENSED, UNRESOLVED, LICENSED_CLASS, UNRESOLVED_CLASS},
                "structural_marker_is_not_sense")
        structural_keys = set()
        for evidence in selection["evidence"]:
            _need(isinstance(evidence, dict) and set(evidence) == EVIDENCE_FIELDS,
                  "evidence_public_fields")
            _need(isinstance(evidence["relation"], str) and
                  isinstance(evidence["semantic_class"], str), "evidence_public_types")
            _need(_integer(evidence["target_start"]) and _integer(evidence["target_end"]) and
                  _integer(evidence["anchor_start"]) and _integer(evidence["anchor_end"]),
                  "evidence_coordinate_types")
            require((evidence["target_start"], evidence["target_end"]) == key[:2],
                    "evidence_actual_target_binding")
            require(_span(evidence["anchor_start"], evidence["anchor_end"], length),
                    "evidence_source_coordinates")
            relation = evidence["relation"]
            if relation in {LICENSED, UNRESOLVED}:
                required_class = LICENSED_CLASS if relation == LICENSED else UNRESOLVED_CLASS
                require(evidence["semantic_class"] == required_class, "structural_marker_class")
                marker_key = (relation, evidence["anchor_start"], evidence["anchor_end"])
                require(marker_key not in structural_keys, "duplicate_structural_marker")
                structural_keys.add(marker_key)
                require(not any(evidence["anchor_start"] < cut < evidence["anchor_end"]
                                for cut in record["hard_boundaries"]), "marker_crosses_hard")
                if relation == UNRESOLVED:
                    require(selection["sense_id"] is None, "unresolved_cannot_select")
                    require(selection["reason"] in UNRESOLVED_REASONS,
                            "unresolved_reason_or_existing_priority")
            else:
                if not relation.startswith(NON_MEANING_OBSERVATION_PREFIX):
                    ordinary_total += 1
                require(evidence["semantic_class"] != LICENSED_CLASS,
                        "structural_class_leaked_to_ordinary_evidence")
            evidence_total += 1
    targets, scored = [], 0
    for target in record["targets"]:
        target_id, expected = target["id"], target["expected"]
        key = (target["start"], target["end"], target["spelling"])
        selection = by_key.get(key)
        require(selection is not None, "missing_exact_target", target_id)
        status = {"target_id": target_id, "decision": expected["decision"],
                  "observed": selection is not None,
                  "semantic_scored": expected["decision"] != "unscored",
                  "structure_scored": target["premises"]["structure"] == "fulfilled"}
        targets.append(status)
        if selection is None:
            continue
        decision = expected["decision"]
        if decision != "unscored":
            scored += 1
            require(selection["sense_id"] == expected["sense_id"], "semantic_outcome", target_id)
        if expected["reason_allowed"]:
            require(selection["reason"] in expected["reason_allowed"], "reason_priority", target_id)
        evidence = selection["evidence"]
        for field, relation in (("licensed_complexes", LICENSED), ("unresolved_complexes", UNRESOLVED)):
            if expected[field] is not None:
                wanted = Counter({tuple(item["anchor"]): item["count"] for item in expected[field]})
                actual = Counter((e["anchor_start"], e["anchor_end"]) for e in evidence
                                 if e["relation"] == relation)
                require(actual == wanted, "exact_" + field, target_id)
        for required in expected["required_evidence"]:
            # 도메인을 기록한 관찰은 클래스가 같아도 뜻을 허가하는 근거가 아니다.
            require(any(not e["relation"].startswith(NON_MEANING_OBSERVATION_PREFIX) and
                        ((required["relation"] is None and
                          e["relation"] not in {LICENSED, UNRESOLVED} and
                          e["semantic_class"] not in NON_MEANING_CLASSES) or
                         _relation_matches(required["relation"], e["relation"])) and
                        (required["semantic_class"] is None or
                         e["semantic_class"] == required["semantic_class"]) and
                        (required["anchor"] is None or
                         [e["anchor_start"], e["anchor_end"]] == required["anchor"])
                        for e in evidence), "required_ordinary_evidence", target_id)
        require(not any(not e["relation"].startswith(NON_MEANING_OBSERVATION_PREFIX) and
                        any(_relation_matches(forbidden, e["relation"]) for forbidden in expected["forbidden_relations"])
                        for e in evidence),
                "forbidden_relation", target_id)
    require(selections == saved, "all_original_returns_preserved")
    return {"record_id": record["id"], "status": "checked" if not failures else "failed",
            "targets": targets, "failures": failures, "semantic_scored": scored,
            "selections_observed": len(selections), "evidence_observed": evidence_total,
            "ordinary_evidence_observed": ordinary_total}
