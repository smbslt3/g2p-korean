"""원본 점수를 보존하고 고정된 개발 정책 보완만 별도로 판정한다."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
_REQUIRED_CERTIFICATE_FIELDS = {
    "start", "end", "parts", "lexical_status", "final_category",
    "host_state", "tail_state", "surface_status", "reason",
}


def _counts(records):
    counts = Counter((row["kind"], row["pass"]) for row in records)
    return {
        "total": len(records),
        "passed": sum(row["pass"] for row in records),
        "failed": sum(not row["pass"] for row in records),
        "by_kind": {kind: {"passed": counts[kind, True], "failed": counts[kind, False]}
                    for kind in sorted({row["kind"] for row in records})},
    }


def score_result(result, supplement):
    """전달 자료를 수정하지 않고 원점수와 개발 보완 판정을 반환한다."""
    if supplement.get("schema") != "r41_independent_policy_supplement.v1":
        raise ValueError("지원하지 않는 정책 보완 자료입니다.")
    if supplement.get("untouched_holdout") is not False:
        raise ValueError("정책 보완은 미열람 검증 집합으로 표시할 수 없습니다.")
    records = result.get("records")
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("kind"), str)
        or not isinstance(row.get("id"), str) or type(row.get("pass")) is not bool
        or not isinstance(row.get("errors"), list) for row in records
    ):
        raise ValueError("원본 결과 레코드가 올바르지 않습니다.")
    raw = {key: deepcopy(result.get(key)) for key in ("total", "passed", "failed", "by_kind")}
    validation_errors = []
    if raw != _counts(records):
        validation_errors.append("원본 집계와 원본 레코드 수가 다릅니다.")
    index = {}
    for row in records:
        key = (row["kind"], row["id"])
        if key in index:
            validation_errors.append("원본 결과에 중복 레코드가 있습니다: " + repr(key))
        index[key] = row
        if row["pass"] != (not row["errors"]):
            validation_errors.append("원본 pass와 errors가 다릅니다: " + repr(key))

    amended, amendments = {}, []
    for amendment in supplement.get("amendments", []):
        before, after = amendment["expected_before"], amendment["expected_after"]
        for variant in amendment["variants"]:
            key = ("certificate", amendment["case_id"] + ":" + variant)
            if key in amended:
                validation_errors.append("정책 보완에 중복 대상이 있습니다: " + repr(key))
                continue
            errors, row = [], index.get(key)
            if row is None:
                errors.append("정책 보완 대상의 원본 관찰이 없습니다.")
                observed = {}
            else:
                observed = row.get("observed", {})
                if not isinstance(observed, dict):
                    observed = {}
                    errors.append("관찰 레코드가 객체가 아닙니다.")
                certificate = observed.get("certificate")
                if not isinstance(certificate, dict):
                    certificate = {}
                    errors.append("공유 증명 관찰이 없습니다.")
                missing = sorted(_REQUIRED_CERTIFICATE_FIELDS - certificate.keys())
                if missing:
                    errors.append("공유 증명 필수 필드 누락: " + ", ".join(missing))
                for expected_key, field in (("lexical_status", "lexical_status"),
                                            ("host", "host_state"), ("tail", "tail_state"),
                                            ("surface_status", "surface_status")):
                    if after.get(expected_key) is not None and certificate.get(field) != after[expected_key]:
                        errors.append("정책 보완 " + field + " 불일치")
                if after.get("assert_category") and certificate.get("final_category") != after["final_category"]:
                    errors.append("정책 보완 final_category 불일치")
                for field, wanted in (("liaison_target", after["lexical_status"] == "eligible"),
                                      ("n_target", after["n_target"])):
                    if type(observed.get(field)) is not bool or observed[field] != wanted:
                        errors.append("정책 보완 " + field + " 불일치 또는 누락")
                if (type(certificate.get("start")) is not int or type(certificate.get("end")) is not int
                        or not 0 <= certificate.get("start", -1) < certificate.get("end", -1)):
                    errors.append("공유 증명 원문 좌표가 올바르지 않습니다.")
                parts = certificate.get("parts")
                if not isinstance(parts, (list, tuple)) or not parts or any(
                    not isinstance(part, (list, tuple)) or len(part) != 2
                    or any(not isinstance(item, str) or not item for item in part) for part in parts
                ):
                    errors.append("공유 증명 원형 출현열이 올바르지 않습니다.")
                if not isinstance(certificate.get("reason"), str) or not certificate.get("reason"):
                    errors.append("공유 증명 이유가 없습니다.")

                # 바뀐 기대값에 대응하는 오류만 대체한다. 다른 불변 조건은 유지한다.
                allowed = set()
                if before["lexical_status"] != after["lexical_status"]:
                    allowed.update({"lexical_status 불일치", "연음 소비자와 공유 어휘 적격성 불일치"})
                if before["n_target"] != after["n_target"]:
                    allowed.add("단어 ㄴ 첨가 소비자와 공유 어휘 적격성 불일치")
                errors.extend("원본 불변 조건 실패: " + str(error)
                              for error in row["errors"] if error not in allowed)
            amended[key] = not errors
            amendments.append({"kind": key[0], "id": key[1], "original_pass": row["pass"] if row else None,
                               "adjudicated_pass": not errors, "expected_after": deepcopy(after), "errors": errors})
    if not amended:
        validation_errors.append("정책 보완 대상이 없습니다.")
    other_failures = [{"kind": row["kind"], "id": row["id"], "errors": deepcopy(row["errors"])}
                      for row in records if (row["kind"], row["id"]) not in amended and not row["pass"]]
    adjusted = [{"kind": row["kind"], "pass": amended.get((row["kind"], row["id"]), row["pass"])}
                for row in records]
    adjudicated = _counts(adjusted)
    return {
        "schema": "r41_post03_adjudicated_score.v1",
        "development_stage": supplement["development_stage"], "untouched_holdout": False,
        "ok": not validation_errors and not other_failures and all(amended.values()),
        "original_raw_counts": raw, "adjudicated_counts": adjudicated,
        "amendments": amendments, "other_failures": other_failures, "validation_errors": validation_errors,
        "scope_ko": "원점수는 보존하며 후보 03 이후 개발 정책 보완만 별도 계산한다. 미열람 검증 성능이 아니다.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, default=HERE / "post03_lexical_class_adjudication_v1.json")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and not args.out.resolve().is_relative_to(HERE):
        raise ValueError("평가 출력은 복사된 기준 자료 폴더 안에만 기록합니다.")
    report = score_result(json.loads(args.result.read_text(encoding="utf-8")),
                          json.loads(args.supplement.read_text(encoding="utf-8")))
    report["input_sha256"] = {"result": hashlib.sha256(args.result.read_bytes()).hexdigest(),
                              "supplement": hashlib.sha256(args.supplement.read_bytes()).hexdigest()}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
