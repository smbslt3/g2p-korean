"""고정 참조를 검증하고 별도 어댑터의 관찰값만 채점한다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read_jsonl(name):
    return [json.loads(line) for line in (ROOT / name).read_text(encoding="utf-8").splitlines() if line]


def check_freeze():
    manifest = json.loads((ROOT / "FREEZE.json").read_text(encoding="utf-8"))
    errors = []
    for name, digest in manifest["sha256"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != digest:
            errors.append(f"동결 해시 불일치: {name}")
    if errors:
        raise ValueError("; ".join(errors))
    return manifest


def validate(cases, invalid, manifest):
    errors = []
    ids = [c["case_id"] for c in cases] + [c["case_id"] for c in invalid]
    if len(set(ids)) != len(ids):
        errors.append("사례 식별자가 중복됩니다.")
    if len(cases) != manifest["cases"] or len(invalid) != manifest["constructor_invalid_cases"]:
        errors.append("동결 사례 수가 다릅니다.")
    for c in cases:
        p = c["input"]
        source = p["source"]
        if p["route"] not in ("engine.pronounce", "G2P", "GAP"):
            errors.append(c["case_id"] + ": 알려지지 않은 경로")
        if p["route"] == "GAP" and " " not in source:
            errors.append(c["case_id"] + ": ASCII 공백 없는 GAP 호출")
        for token in p["analysis_tokens"]:
            start, end = token["start"], token["end"]
            if source[start:end] != token["form"] or not 0 <= start < end <= len(source):
                errors.append(c["case_id"] + ": 표면 토큰 범위 불일치")
            if len(token["morphemes"]) != len(token["morpheme_spans"]):
                errors.append(c["case_id"] + ": 원형 출현 수 불일치")
            for a, b in token["morpheme_spans"]:
                if not start <= a <= b <= end:
                    errors.append(c["case_id"] + ": 원형 범위 불일치")
        for b in c["expected"]["boundaries"]:
            a, z = b["source_pair"]
            if not 0 <= a < z < len(source):
                errors.append(c["case_id"] + ": 음절쌍 범위 불일치")
            if b["selected_article"] in b["forbidden_articles"]:
                errors.append(c["case_id"] + ": 선택 조항과 금지 조항 모순")
        phones = c["expected"]["allowed_phones"]
        if phones is not None and (not phones or any(len(x) != len(source) for x in phones)):
            errors.append(c["case_id"] + ": 공개 기본 출력의 원문 길이 범위 불일치")
    if errors:
        raise ValueError("\n".join(errors))


def equal_subset(expected, actual, prefix, errors):
    if not isinstance(actual, dict):
        errors.append(prefix + ": 관찰 객체 누락")
        return
    for key, value in expected.items():
        if key == "forbidden_articles":
            consumed = actual.get("consumed_articles")
            if not isinstance(consumed, list):
                errors.append(prefix + ".consumed_articles: 소비 조항 관찰 누락")
            elif set(value).intersection(consumed):
                errors.append(prefix + ": 금지된 소비 조항이 실행됨")
        elif key not in actual:
            errors.append(prefix + "." + key + ": 관찰 누락")
        elif actual[key] != value:
            errors.append(prefix + "." + key + ": 기대값과 다름")


def score(case, actual):
    errors = []
    if not isinstance(actual, dict):
        return ["관찰 객체가 반환되지 않았습니다."]
    expected = case["expected"]
    if actual.get("route") != case["input"]["route"]:
        errors.append("공개 실행 경로가 요구 경로와 다릅니다.")
    if actual.get("analysis_source") != "supplied":
        errors.append("고정 제공 분석 경로의 증거가 없습니다.")
    phone = actual.get("phone")
    if expected["allowed_phones"] is not None and phone not in expected["allowed_phones"]:
        errors.append("표면 발음이 규범 허용 집합에 없습니다.")
    override = actual.get("whole_phone_override_used")
    if type(override) is not bool:
        errors.append("완성 발음 치환 사용 여부 관찰이 없습니다.")
    elif expected["whole_phone_override"] == "forbidden" and override:
        errors.append("완성 발음 치환을 사용했습니다.")
    native = actual.get("native_evidence", {})
    for key in ("invocation", "override_audit"):
        if not isinstance(native, dict) or not native.get(key):
            errors.append("네이티브 증거 누락: " + key)
    observed = actual.get("boundaries")
    if not isinstance(observed, list):
        errors.append("경계 관찰 목록이 없습니다.")
        return errors
    for i, b in enumerate(expected["boundaries"]):
        matches = [v for v in observed if isinstance(v, dict) and v.get("source_pair") == b["source_pair"]]
        if len(matches) != 1:
            errors.append(f"경계 {i}: 고유한 물리 경계 관찰이 없습니다.")
            continue
        item = matches[0]
        equal_subset(b, item, f"경계 {i}", errors)
        if item.get("consumption_count", 0) and item.get("consumed_articles") != [item.get("selected_article")]:
            errors.append(f"경계 {i}: 선택 소비자와 실제 소비 목록이 다릅니다.")
        evidence = item.get("native_evidence", {})
        for key in ("word_certificate", "surface_proof", "boundary_record"):
            if not isinstance(evidence, dict) or not evidence.get(key):
                errors.append(f"경계 {i}: 네이티브 증거 누락: {key}")
    return errors


def load_adapter(path):
    spec = importlib.util.spec_from_file_location("r42_observation_adapter", path)
    if spec is None or spec.loader is None:
        raise ValueError("어댑터를 읽을 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "evaluate", None)) or not callable(getattr(module, "construct_invalid", None)):
        raise ValueError("어댑터에 evaluate와 construct_invalid가 필요합니다.")
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    manifest = check_freeze()
    cases = read_jsonl("cases.jsonl")
    invalid = read_jsonl("constructor_invalid.jsonl")
    validate(cases, invalid, manifest)
    if args.validate_only:
        print(json.dumps({"freeze_valid": True, "cases": len(cases), "constructor_invalid": len(invalid),
                          "runtime_imported": False}, ensure_ascii=False))
        return 0
    if args.adapter is None or args.report is None:
        parser.error("실행 관찰에는 --adapter와 --report가 필요합니다.")
    adapter_path = args.adapter.resolve()
    report_path = args.report.resolve()
    if report_path.parent != ROOT or report_path.name in manifest["sha256"] or report_path.name == "FREEZE.json":
        raise ValueError("관찰 결과는 독립 참조 폴더의 새 파일에만 기록할 수 있습니다.")
    if report_path.exists():
        raise ValueError("기존 관찰 결과를 덮어쓰지 않습니다.")
    adapter = load_adapter(adapter_path)
    rows = []
    for case in cases:
        try:
            actual = adapter.evaluate(copy.deepcopy(case["input"]))
            failures = score(case, actual)
        except Exception as error:
            actual = {"exception": type(error).__name__, "message": str(error)}
            failures = ["실행 또는 관찰 예외"]
        rows.append({"case_id": case["case_id"], "evidence_scope": case["evidence_scope"],
                     "family": case["family"], "passed": not failures,
                     "failures_ko": failures, "observation": actual})
    for case in invalid:
        try:
            observed = adapter.construct_invalid({"model": case["model"], "args": copy.deepcopy(case["args"])})
        except Exception as error:
            observed = type(error).__name__
        rows.append({"case_id": case["case_id"], "evidence_scope": "constructor_only",
                     "family": "constructor_only", "passed": observed == case["expected_exception"],
                     "observed_exception": observed})
    by_scope = defaultdict(Counter)
    for row in rows:
        by_scope[row["evidence_scope"]]["passed" if row["passed"] else "failed"] += 1
    report = {"freeze_sha256": hashlib.sha256((ROOT / "FREEZE.json").read_bytes()).hexdigest(),
              "adapter_path": str(adapter_path), "adapter_sha256": hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
              "by_scope": {k: dict(v) for k, v in by_scope.items()}, "rows": rows}
    # 실행 중에도 참조가 변하지 않았음을 확인한 뒤 결과를 보존한다.
    check_freeze()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["by_scope"], ensure_ascii=False))
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
