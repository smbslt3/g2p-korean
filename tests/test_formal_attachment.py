"""고정 기대와 제공 형태 분석으로 실제 pair 실행을 검사한다."""
from pathlib import Path
from unittest.mock import patch
import json
import sys

import g2p_ko.analyzer as analyzer_module
import g2p_ko.korean.engine as engine
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
from g2p_ko.reading_conditions import _MappedReadingBoundary

HERE = Path(__file__).parent
CASES = json.loads((HERE / "formal_attachment_cases_v1.json").read_text(encoding="utf-8"))["cases"]
ERRATA = json.loads((HERE / "formal_attachment_reporting_errata_v1.json").read_text(encoding="utf-8"))["corrections"]
AMENDMENT = json.loads((HERE / "formal_attachment_reporting_amendment_v2.json").read_text(encoding="utf-8"))["corrections"]


def run_case(case):
    """실제 Kiwi 생성은 금지하고 원문에 고정한 분석만 공급한다."""
    text = case["source"]
    tokens = tuple(AnalysisToken(form, tag, start, start+len(form), tuple(map(tuple, parts)),
                                **({"morpheme_spans": tuple(map(tuple, spans))} if spans
                                   and "morpheme_spans" in AnalysisToken.__dataclass_fields__ else {}))
                   for form, tag, start, parts, spans in case["tokens"])

    class ProvidedAnalyzer:
        def analyze(self, given):
            assert given == text
            return tokens

    if case["barrier"] == "hard":
        segments = (OutputSegment(text[:case["offset"]],
                    (SourceSpan.from_source(text, 0, case["offset"]),), Handler.KOREAN,
                    "제공 분석", boundary_after=Boundary.HARD),
                    OutputSegment(text[case["offset"]:],
                    (SourceSpan.from_source(text, case["offset"], len(text)),), Handler.KOREAN,
                    "제공 분석", boundary_before=Boundary.HARD))
    else:
        segments = (OutputSegment(text, (SourceSpan.from_source(text, 0, len(text)),),
                    Handler.PROTECTED if case["barrier"] == "protected" else Handler.KOREAN,
                    "제공 분석"),)
    requests = (() if case["relation"] == "default" else tuple(
        _MappedReadingBoundary(case["offset"], case["offset"], case["offset"], case["relation"])
        for _ in range(case["repeats"])))
    with patch.object(analyzer_module, "_create_kiwi", side_effect=AssertionError("실제 Kiwi 생성 금지")), \
         patch.object(engine, "KiwiAnalyzer", ProvidedAnalyzer):
        result = engine.pronounce(segments, reading_conditions=requests)
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert text[span.start:span.end] == span.surface
            assert span.source_length == len(text)
    assert len(result.text) == len(text)
    return {"id": case["id"], "output": result.text,
            "executions": [item.to_dict() for item in result.condition_executions],
            "rewrites": [item.to_dict() for item in result.rewrites],
            "diagnostics": [item.to_dict() for item in result.diagnostics]}


def failures(case, result, *, apply_errata=True):
    """발음, 적격성, 해당 pair의 실제 규칙을 각각 비교한다."""
    if apply_errata:
        case = case | ERRATA.get(case["id"], {}) | AMENDMENT.get(case["id"], {})
    errors = []
    if result["output"] != case["expected"]:
        errors.append(f"output: {result['output']!r} != {case['expected']!r}")
    for entry in result["executions"]:
        for key in ("status", "applicability"):
            if entry[key] != case[key]:
                errors.append(f"{key}: {entry[key]} != {case[key]}")
        if "reason" in case and entry["reason"] != case["reason"]:
            errors.append(f"reason: {entry['reason']} != {case['reason']}")
        if "sound_effect" in case and entry["sound_effect"] != case["sound_effect"]:
            errors.append(f"sound_effect: {entry['sound_effect']} != {case['sound_effect']}")
        if tuple(entry["rule_ids"]) != tuple(case["rules"]):
            errors.append(f"rules: {entry['rule_ids']} != {case['rules']}")
    # 중복 요청은 같은 경계의 소리를 한 번만 소비해야 한다.
    if case["repeats"] > 1:
        pair = result["executions"][0]["output_pair"]
        events = [row for row in result["rewrites"] if row["rule_id"] in case["rules"]
                  and row["source_spans"][0]["start"] == pair[0]]
        if len(events) != 1:
            errors.append(f"physical event count: {len(events)} != 1")
    return errors


def test_frozen_matrix():
    for case in CASES:
        result = run_case(case)
        assert not failures(case, result), (case["id"], failures(case, result))


if __name__ == "__main__":
    target = Path(sys.argv[1])
    assert not target.exists(), "기존 실행 원본은 덮어쓰지 않습니다."
    records = []
    for case in CASES:
        try:
            result = run_case(case)
            result["original_failures"] = failures(case, result, apply_errata=False)
            result["failures"] = failures(case, result)
        except Exception as error:
            result = {"id": case["id"], "error": repr(error), "failures": [repr(error)]}
        records.append(result)
    data = {"cases": len(records), "passed": sum(not row["failures"] for row in records),
            "records": records}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({key: data[key] for key in ("cases", "passed")}))
    for row in records:
        if row["failures"]:
            print(row["id"], "; ".join(row["failures"]))
