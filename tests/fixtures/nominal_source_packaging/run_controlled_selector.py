"""별도 실행 승인 뒤 쓰는 R48 통제 선택기 관찰기. import만으로 실행하지 않는다."""

import argparse
from copy import deepcopy
import dataclasses
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback


TOKEN_FIELDS = ("form", "tag", "start", "end", "morphemes")
CHOICE_FIELDS = ("start", "end", "spelling", "sense_id", "evidence", "reason")
EVIDENCE_FIELDS = (
    "relation", "target_start", "target_end", "anchor_start", "anchor_end", "semantic_class",
)


class RunnerGuard(ValueError):
    """실패 메시지에는 정해진 검사명만 둔다."""


def _need(condition, code):
    if not condition:
        raise RunnerGuard(code)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inventory(src):
    # 바이트코드/캐시는 원본 소스 재고에 넣지 않는다. 생산 소스를 해석하지 않는다.
    inventory = {}
    for path in sorted(src.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            _need(path.resolve().is_relative_to(src), "source_inventory_path_escape")
            inventory[path.relative_to(src).as_posix()] = {"sha256": _sha(path), "size": path.stat().st_size}
    return inventory


def _origins(src):
    origins = {}
    for name, module in sorted(sys.modules.items()):
        if name == "g2p_ko" or name.startswith("g2p_ko."):
            raw = getattr(module, "__file__", None)
            _need(raw is not None, "project_module_origin_missing")
            path = Path(raw).resolve()
            _need(path.is_relative_to(src), "project_module_origin_outside_selected_src")
            origins[name] = {"path": str(path), "sha256": _sha(path)}
    return origins


def _public(value, names):
    # 공개 필드 전체를 보존한다. dataclass인 실제 DTO의 필드 누락/추가는 거부한다.
    if dataclasses.is_dataclass(value):
        _need({f.name for f in dataclasses.fields(value)} == set(names), "public_dto_fields_changed")
    return {name: getattr(value, name) for name in names}


def _tokens(tokens):
    output = []
    for token in tokens:
        value = _public(token, TOKEN_FIELDS)
        _need(isinstance(value["morphemes"], tuple) and all(
            isinstance(pair, tuple) and len(pair) == 2 for pair in value["morphemes"]),
            "original_morpheme_tuple_shape")
        value["morphemes"] = [list(pair) for pair in value["morphemes"]]
        output.append(value)
    return output


def _selections(raw):
    _need(isinstance(raw, tuple), "selector_return_tuple_shape")
    output = []
    for selection in raw:
        value = _public(selection, CHOICE_FIELDS)
        _need(isinstance(value["evidence"], tuple), "evidence_return_tuple_shape")
        value["evidence"] = [_public(e, EVIDENCE_FIELDS) for e in value["evidence"]]
        output.append(value)
    return output


def _checker():
    path = Path(__file__).with_name("pure_checker.py")
    spec = importlib.util.spec_from_file_location("r48_frozen_pure_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(args):
    _need(sys.flags.isolated == 1 and sys.dont_write_bytecode and sys.flags.utf8_mode == 1,
          "require_isolated_no_bytecode_utf8")
    src, refs, out = (Path(value).resolve() for value in (args.src, args.refs, args.out))
    _need(src.is_dir() and refs.is_file(), "explicit_source_and_reference_required")
    _need(not out.is_relative_to(src) and not src.is_relative_to(out) and
          not refs.is_relative_to(out), "output_must_not_overlap_source_or_reference")
    _need(not any(name == "g2p_ko" or name.startswith("g2p_ko.") for name in sys.modules),
          "project_module_loaded_before_binding")
    out.mkdir(parents=True, exist_ok=False)
    checker = _checker()
    refs_sha = _sha(refs)
    source_before = _inventory(src)
    _need(bool(source_before), "empty_source_inventory")
    checker_sha = _sha(Path(__file__).with_name("pure_checker.py"))
    runner_sha = _sha(Path(__file__))
    _write(out / "source_inventory_before.json", source_before)
    _write(out / "module_origins_before.json", _origins(src))
    try:
        document = json.loads(refs.read_text(encoding="utf-8"))
        checker.validate_references(document)
    except Exception:
        (out / "reference_preflight_exception_private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        _write(out / "parent_safe_controlled_summary.json", {
            "status": "CONTROLLED_HOLD", "check": "reference_preflight_failed", "selector_call_count": 0,
        })
        raise RunnerGuard("reference_preflight_failed") from None
    raw_records, safe_records = [], []
    calls = 0
    run_failure = None
    try:
        # -I의 표준 경로를 유지하고 지정 src 하나만 명시적으로 추가한다.
        sys.path.insert(0, str(src))
        policy = importlib.import_module("g2p_ko.korean.semantic_policy")
        SemanticToken, select_senses = policy.SemanticToken, policy.select_senses
        _need(SemanticToken.__module__ == policy.__name__ and
              select_senses.__module__ == policy.__name__, "public_callable_module_binding")
        _write(out / "module_origins_bound_before_calls.json", _origins(src))
        for record in document["records"]:
            record_id = record["id"]
            target_ids = [target["id"] for target in record["targets"]]
            original = {key: deepcopy(record[key]) for key in ("text", "tokens", "hard_boundaries")}
            private = {"record_id": record_id, "target_ids": target_ids,
                       "original_input": original, "premises": deepcopy(record["premises"]),
                       "call_count": 0}
            raw_records.append(private)
            if record["premises"]["binding"] == "unbound":
                if record["scope"] == "abstract":
                    result = checker.check_record(record, None, None, None)
                else:
                    # 입력 미결을 억지 호출/정답 유보로 바꾸지 않는다.
                    result = {"record_id": record_id, "status": "not_executed_unbound",
                              "targets": [{"target_id": tid, "semantic_scored": False,
                                           "observed": False} for tid in target_ids],
                              "failures": [], "semantic_scored": 0}
                private["check"] = result
                safe_records.append(result)
                continue
            before = None
            token_args = None
            hard_args = None
            raw = None
            try:
                token_args = tuple(SemanticToken(
                    form=t["form"], tag=t["tag"], start=t["start"], end=t["end"],
                    morphemes=tuple(tuple(pair) for pair in t["morphemes"]),
                ) for t in record["tokens"])
                hard_args = frozenset(record["hard_boundaries"])
                before = {"text": record["text"], "tokens": _tokens(token_args),
                          "hard_boundaries": list(record["hard_boundaries"])}
                _need(before == original, "constructed_input_not_exact")
                private["input_before"] = before
                private["hard_argument_values"] = sorted(hard_args)
                calls += 1
                private["call_count"] = 1
                raw = select_senses(record["text"], token_args, hard_args)
                observed = _selections(raw)
                after = {"text": record["text"], "tokens": _tokens(token_args),
                         "hard_boundaries": list(record["hard_boundaries"])}
                _need(hard_args == frozenset(original["hard_boundaries"]), "hard_argument_changed")
                private.update(input_after=after, selections=observed)
                result = checker.check_record(record, observed, before, after)
                private["check"] = result
                safe_records.append(result)
            except Exception as error:
                # 원반환/전체 예외는 비공개로 남기고 부모에게는 ID/검사명만 보낸다.
                private["traceback"] = traceback.format_exc()
                if raw is not None:
                    private["unconverted_return_repr"] = repr(raw)
                if token_args is not None:
                    try:
                        private["input_after_exception"] = {"text": record["text"],
                            "tokens": _tokens(token_args),
                            "hard_boundaries": list(record["hard_boundaries"])}
                    except Exception:
                        private["snapshot_traceback"] = traceback.format_exc()
                code = str(error) if isinstance(error, (RunnerGuard, checker.ContractError)) else "controlled_observation_exception"
                safe_records.append({"record_id": record_id, "status": "observation_failed",
                    "target_ids": target_ids, "semantic_scored": 0,
                    "failures": [{"check": code, "target_id": None}]})
    except Exception as error:
        (out / "binding_exception_private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        run_failure = str(error) if isinstance(error, RunnerGuard) else "public_binding_exception"
    finally:
        _write(out / "raw_controlled_observations_private.json", raw_records)
        source_after = _inventory(src)
        _write(out / "source_inventory_after.json", source_after)
        try:
            origins = _origins(src)
            origins_valid = True
            _write(out / "module_origins_after.json", origins)
        except Exception:
            origins_valid = False
            (out / "origin_exception_private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        unvisited = [record for record in document["records"]
                     if record["id"] not in {r["record_id"] for r in safe_records}]
        for record in unvisited:
            safe_records.append({"record_id": record["id"], "status": "not_executed_binding_failure",
                                 "target_ids": [t["id"] for t in record["targets"]],
                                 "semantic_scored": 0, "failures": []})
        unchanged = source_before == source_after
        refs_unchanged = refs_sha == _sha(refs)
        support_unchanged = checker_sha == _sha(Path(__file__).with_name("pure_checker.py")) and runner_sha == _sha(Path(__file__))
        failed_records = sum(bool(r.get("failures")) for r in safe_records)
        scored = sum(r["semantic_scored"] for r in safe_records)
        unscored_targets = sum(t["expected"]["decision"] == "unscored"
                               for r in document["records"] for t in r["targets"])
        unbound_records = sum(r["premises"]["binding"] == "unbound" for r in document["records"])
        partial_records = sum(r["premises"]["binding"] == "partial" for r in document["records"])
        held = bool(run_failure or failed_records or not unchanged or not refs_unchanged or
                    not support_unchanged or not origins_valid)
        status = "CONTROLLED_HOLD" if held else (
            "CONTROLLED_PARTIAL_CHECKED" if unscored_targets or unbound_records or partial_records
            else "CONTROLLED_CHECKED")
        summary = {"status": status,
                   "run_failure_check": run_failure, "records": safe_records,
                   "record_count": len(document["records"]),
                   "target_count": sum(len(r["targets"]) for r in document["records"]),
                   "selector_call_count": calls, "failed_record_count": failed_records,
                   "semantic_scored": scored, "semantic_unscored_target_count": unscored_targets,
                   "partial_record_count": partial_records, "unbound_not_called_record_count": unbound_records,
                   "semantic_scope_status": "SCORED_TARGETS_ONLY" if scored else "NO_SCORED_SEMANTIC_TARGETS",
                   "source_file_count": len(source_before), "source_unchanged": unchanged,
                   "reference_sha256": refs_sha, "references_unchanged": refs_unchanged,
                   "runner_sha256": runner_sha, "checker_sha256": checker_sha,
                   "support_unchanged": support_unchanged, "module_origins_valid": origins_valid,
                   "g2p_kiwi_model_calls_requested": 0,
                   "native_input_or_phone_accuracy_claimed": False}
        _write(out / "parent_safe_controlled_summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="R48 승인 후 통제 선택기 바인딩")
    parser.add_argument("--src", required=True)
    parser.add_argument("--refs", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        summary = _run(args)
    except Exception as error:
        # 입력 본문이나 예외 값을 stdout/stderr에 노출하지 않는다.
        check = str(error) if isinstance(error, RunnerGuard) else "controlled_preparation_or_io_guard"
        print(json.dumps({"status": "CONTROLLED_HOLD", "check": check}))
        return 2
    print(json.dumps({key: summary[key] for key in (
        "status", "record_count", "target_count", "selector_call_count", "failed_record_count",
    )}))
    return 0 if summary["status"] in {"CONTROLLED_CHECKED", "CONTROLLED_PARTIAL_CHECKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
