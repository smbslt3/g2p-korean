"""동결 제어 분석을 실제 공개 G2P 경로에 주입하는 한정된 독립 실행기다."""

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import importlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(type(value).__name__)


def snapshot(value):
    return json.loads(json.dumps(value, default=default, ensure_ascii=False))


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=default)
        handle.write("\n")


def digest(path):
    """체크아웃 줄바꿈만 정규화한 지원 파일 해시다."""
    return hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()


def local_entries(entries, boundary):
    return [entry for entry in entries if any(
        span["start"] < boundary + 1 and span["end"] > boundary - 1
        for span in entry["source_spans"])]


def preflight(refs, rules):
    from copy import deepcopy
    sample = refs["records"][0]["input"]["analyses"]["within_token"]
    altered = deepcopy(sample)
    altered[0]["tag"] = "NNG"
    entries = [{"rule_id": rules["11_daman"], "source_spans": [{"start": i, "end": i + 1}]} for i in range(2)]
    entries.append({"rule_id": "other", "source_spans": [{"start": 4, "end": 5}]})
    local = local_entries(entries, 1)
    checks = {
        "분석 보존": snapshot(sample) == snapshot(deepcopy(sample)),
        "원 태그 변경 검출": snapshot(sample) != snapshot(altered),
        "국소 provenance 선택": len(local) == 2,
        "정렬 두 항목을 실행 횟수로 바꾸지 않음": Counter(e["rule_id"] for e in local) == {rules["11_daman"]: 2},
        "제어 의미 사례 9건": sum(r["scope"] == "controlled" for r in refs["records"]) == 9,
        "추상 조건 4건 미바인딩": sum(r["scope"] == "abstract" and r["input"]["analyses"] is None for r in refs["records"]) == 4,
        "동결 발음 9건": sum(r["expected"]["phones"] is not None for r in refs["records"]) == 9,
    }
    return {"scope": "pure_synthetic_checker", "passed": all(checks.values()), "checks": checks,
            "source_imports": 0, "runtime_calls": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    src, out = args.src.resolve(), args.out.resolve()
    refs_path = HERE
    refs, plan = read(refs_path / "references.json"), read(HERE / "binding_plan.json")
    if args.preflight:
        report = preflight(refs, plan["rule_ids"])
        write_new(out / "preflight.json", report)
        return 0 if report["passed"] else 1
    freeze = read(HERE / "support_copy_receipt.json")
    for name, expected in freeze["artifact_sha256"].items():
        if digest(HERE / name) != expected:
            raise RuntimeError("바인딩 동결 파일이 바뀌었습니다.")
    if any(name == "g2p_ko" or name.startswith("g2p_ko.") for name in sys.modules):
        raise RuntimeError("프로젝트 모듈이 이미 로드되었습니다.")
    source_hash = hashlib.sha256()
    files = sorted((src / "g2p_ko").rglob("*.py"))
    for file in files:
        source_hash.update(file.relative_to(src).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    sys.path.insert(0, str(src))
    package = importlib.import_module("g2p_ko")
    model = importlib.import_module("g2p_ko.model")
    engine = importlib.import_module("g2p_ko.korean.engine")
    proof_api = importlib.import_module("g2p_ko.korean.surface_proof")
    if any(not Path(module.__file__).resolve().is_relative_to(src) for module in (package, model, engine, proof_api)):
        raise RuntimeError("선택 source 외부의 프로젝트 모듈을 가져왔습니다.")
    original_factory, g2p, rows = engine.KiwiAnalyzer, package.G2P(), []
    counts = Counter()
    for record in refs["records"]:
        if record["scope"] == "abstract":
            rows.append({"ref_id": record["id"], "packaging": None, "status": "unbound",
                         "reason": "새 native 입력·증명을 만들지 않아 추상 조건은 미바인딩",
                         "phone_matches": None, "rule_presence_matches": None, "execution_count": None})
            continue
        for packaging, supplied in record["input"]["analyses"].items():
            tokens = tuple(model.AnalysisToken(**data) for data in supplied)
            before, calls, supplementary = snapshot(tokens), [], []
            text = record["input"]["text"]

            class StaticAnalyzer:
                """모델 출력이라는 주장 없이 공급 토큰을 원래 필드 그대로 돌려준다."""
                def analyze(self, observed, **kwargs):
                    return self._supply(observed, "analyze", kwargs)
                def analyze_components(self, observed):
                    return self._supply(observed, "analyze_components", {})
                def _supply(self, observed, method, kwargs):
                    calls.append({"method": method, "text": observed, "kwargs": kwargs})
                    if observed != text:
                        raise ValueError("동결된 전체 입력 이외의 분석 요청은 지원하지 않습니다.")
                    return tokens
                def saisiot_positions(self, observed):
                    supplementary.append({"method": "saisiot_positions", "text": observed})
                    if observed != text:
                        raise ValueError("동결되지 않은 사이시옷 분석 요청입니다.")
                    return ()

            row = {"ref_id": record["id"], "packaging": packaging, "status": "executed",
                   "input": supplied, "analysis_before": before, "analysis_calls": calls,
                   "supplementary_calls": supplementary, "whole_word_grammar": "unobserved_by_public_result",
                   "new_internal_eligibility": "unconfirmed", "execution_count": None,
                   "execution_count_scope": "공개 정렬 항목 수는 실제 소비 실행 횟수가 아님"}
            row["token_surface_proofs"] = []
            for index, token in enumerate(tokens):
                counts["verified_token_surface"] += 1
                supplementary.append({"method": "verified_token_surface", "token_index": index})
                try:
                    proof = proof_api.verified_token_surface(token)
                    row["token_surface_proofs"].append({"status": "observed" if proof is not None else "missing", "proof": snapshot(proof)})
                except Exception as error:
                    row["token_surface_proofs"].append({"status": "error", "error": repr(error)})
            static = StaticAnalyzer()
            engine.KiwiAnalyzer = lambda: static
            try:
                counts["g2p_convert_with_alignment"] += 1
                aligned = g2p.convert_with_alignment(text)
                alignment = aligned.alignment.to_dict()
                local = local_entries(alignment["entries"], record["input"]["target_boundary"])
                rule_counts = Counter(entry["rule_id"] for entry in local if entry.get("rule_id"))
                wanted = plan["rule_ids"][record["expected"]["local"]["family"]]
                row.update(result=aligned.result.to_dict(), alignment=alignment, local_entries=local,
                           rule_entry_counts=dict(rule_counts), expected_rule_id=wanted,
                           phone_matches=aligned.result.surface_pronunciation == record["expected"]["phones"]["segmental"],
                           rule_presence_matches=(wanted in rule_counts) == (record["expected"]["local"][packaging] == "apply"))
            except Exception as error:
                row.update(status="error", error=repr(error), phone_matches=None, rule_presence_matches=None)
            finally:
                engine.KiwiAnalyzer = original_factory
            row["analysis_after"] = snapshot(tokens)
            row["analysis_preserved"] = before == row["analysis_after"] == supplied
            counts["analysis_calls"] += len(calls)
            counts["saisiot_positions"] += sum(call["method"] == "saisiot_positions" for call in supplementary)
            rows.append(row)
    origins = {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
               if (name == "g2p_ko" or name.startswith("g2p_ko.")) and getattr(module, "__file__", None)}
    if not origins or any(not Path(path).is_relative_to(src) for path in origins.values()):
        raise RuntimeError("선택 source 외부의 프로젝트 모듈이 로드되었습니다.")
    write_new(out / "execution.json", {"selected_source": str(src), "source_sha256": source_hash.hexdigest(),
        "source_files": len(files), "module_origins": origins, "mode": "controlled_internal_test_injection",
        "public_custom_analyzer_feature": False, "actual_kiwi_packaging_measured": False,
        "model_constructors_by_runner": 0, "call_counts": dict(counts), "records": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
