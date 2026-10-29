"""명시한 불변 src에 공개 발음 평가를 고정하는 버전 2 실행기다."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.abc
import importlib.machinery
import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import evaluator_binding_v1 as binding
import evaluator_runner_v1 as v1
import run_refs as frozen


ROOT = Path(__file__).resolve().parent
RUNNER_VERSION = "r42-source-pinned-available-metrics-v2"
MANIFEST_EXCLUDED_COMPONENTS = frozenset({"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
MANIFEST_EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})


class SourceIsolationError(RuntimeError):
    """선택한 원본 밖의 코드 또는 변경된 원본을 발견한 경우다."""


def project_name(name):
    return name == "g2p_ko" or name.startswith("g2p_ko.")


def inside(path, source_root):
    """문자열 접두사가 아니라 실제 해석한 경로의 포함 관계를 확인한다."""
    try:
        return path.resolve().is_relative_to(source_root.resolve())
    except (OSError, RuntimeError):
        return False


def source_manifest(source_root):
    """선택한 src의 비캐시 파일 전체를 해시하며 본문은 결과에 내보내지 않는다."""
    records = {}
    for path in sorted(source_root.rglob("*")):
        relative = path.relative_to(source_root)
        if any(p in MANIFEST_EXCLUDED_COMPONENTS for p in relative.parts) or path.suffix in MANIFEST_EXCLUDED_SUFFIXES:
            continue
        if not inside(path, source_root):
            raise SourceIsolationError("선택 src의 파일/연결이 원본 범위를 벗어났습니다: " + str(relative))
        if path.is_file():
            content = path.read_bytes()
            records[relative.as_posix()] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"tree_sha256": hashlib.sha256(encoded).hexdigest(), "files": records,
            "excluded_components": sorted(MANIFEST_EXCLUDED_COMPONENTS),
            "excluded_suffixes": sorted(MANIFEST_EXCLUDED_SUFFIXES)}


def file_record(filename, source_root, manifest):
    """실제 모듈 파일의 범위와 동결 시점 바이트를 확인한다."""
    if not isinstance(filename, str) or not filename or filename in ("built-in", "frozen"):
        raise SourceIsolationError("g2p_ko 모듈의 실제 파일 출처가 없습니다.")
    path = Path(filename).resolve()
    if not inside(path, source_root):
        raise SourceIsolationError("g2p_ko 모듈이 선택한 src 밖에 있습니다: " + str(path))
    relative = path.relative_to(source_root).as_posix()
    expected = manifest["files"].get(relative)
    if expected is None:
        raise SourceIsolationError("모듈 파일이 실행 전 src 목록에 없습니다: " + relative)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected != {"size": len(content), "sha256": digest}:
        raise SourceIsolationError("모듈 원본이 실행 전 해시와 다릅니다: " + relative)
    return {"file": str(path), "relative_file": relative, "sha256": digest, "size": len(content)}


def audit_module_origins(source_root, manifest, modules):
    """가져온 모든 g2p_ko 모듈의 파일·명세·패키지 검색 범위를 확인한다."""
    result = {}
    for name, module in list(modules.items()):
        if not project_name(name):
            continue
        record = file_record(getattr(module, "__file__", None), source_root, manifest)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        spec_record = file_record(origin, source_root, manifest)
        if spec_record["file"] != record["file"]:
            raise SourceIsolationError("모듈 __file__과 __spec__.origin이 다릅니다: " + name)
        package_paths = []
        for path in getattr(module, "__path__", ()):
            resolved = Path(path).resolve()
            if not inside(resolved, source_root):
                raise SourceIsolationError("패키지 검색 범위가 선택 src 밖에 있습니다: " + name)
            package_paths.append(str(resolved))
        result[name] = {**record, "spec_origin": spec_record["file"], "package_paths": package_paths}
    return result


def require_fresh_project_modules(modules):
    """이전 설치본이나 다른 원본이 남은 프로세스에서 비교를 시작하지 않는다."""
    found = sorted(name for name in modules if project_name(name))
    if found:
        raise SourceIsolationError("이미 가져온 g2p_ko 모듈이 있습니다. 새 Python 프로세스가 필요합니다: " + ", ".join(found))


class VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
    """검증한 원본 바이트를 직접 컴파일하여 남은 pyc를 읽지 않는다."""

    def __init__(self, name, path, source_root, manifest):
        super().__init__(name, path)
        self.source_root = source_root
        self.manifest = manifest

    def get_code(self, fullname):
        record = file_record(self.path, self.source_root, self.manifest)
        content = self.get_data(self.path)
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise SourceIsolationError("검증과 컴파일 사이에 원본 바이트가 바뀌었습니다: " + fullname)
        return self.source_to_code(content, self.path)


class PinnedProjectFinder(importlib.abc.MetaPathFinder):
    """g2p_ko만 선택 src에서 찾고 설치본/편집 설치본으로 대체하지 않는다."""

    def __init__(self, source_root, manifest, requests, violations):
        self.source_root = source_root
        self.manifest = manifest
        self.requests = requests
        self.violations = violations

    def find_spec(self, fullname, path=None, target=None):
        if not project_name(fullname):
            return None
        try:
            search = [str(self.source_root)] if fullname == "g2p_ko" else list(path or ())
            if not search or any(not inside(Path(p), self.source_root) for p in search):
                raise SourceIsolationError("선택 src 밖의 하위 모듈 검색 요청입니다: " + fullname)
            # 다른 meta_path의 편집 설치 검색기를 통과하지 않는다.
            spec = importlib.machinery.PathFinder.find_spec(fullname, search, target)
            if spec is None:
                raise SourceIsolationError("선택 src에 모듈이 없습니다. 설치본 대체를 차단합니다: " + fullname)
            record = file_record(spec.origin, self.source_root, self.manifest)
            for package_path in spec.submodule_search_locations or ():
                if not inside(Path(package_path), self.source_root):
                    raise SourceIsolationError("반환된 패키지 검색 범위가 선택 src 밖에 있습니다: " + fullname)
            if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
                spec.loader = VerifiedSourceLoader(fullname, spec.origin, self.source_root, self.manifest)
                load_mode = "compile_verified_source_bytes_without_pyc"
            else:
                load_mode = type(spec.loader).__name__
            self.requests.append({"module": fullname, **record, "load_mode": load_mode})
            return spec
        except Exception as error:
            self.violations.append({"module": fullname, "exception": type(error).__name__, "message": str(error)})
            raise


class SourceSession:
    """한 실행 전체에서 원본 선택과 모듈 출처 검증을 유지한다."""

    def __init__(self, requested):
        self.requested = str(requested)
        # Windows 제한 환경의 strict 경로 확인은 존재하는 폴더에도 접근 거부를
        # 낼 수 있어, 해석한 경로의 디렉터리/표제 파일과 실제 바이트를 따로 확인한다.
        self.source_root = Path(requested).resolve()
        if not self.source_root.is_dir() or not (self.source_root / "g2p_ko" / "__init__.py").is_file():
            raise SourceIsolationError("--src는 g2p_ko/__init__.py를 포함하는 src 폴더여야 합니다.")
        self.before = source_manifest(self.source_root)
        self.after = None
        self.unchanged = None
        self.imports = {}
        self.requests = []
        self.violations = []
        self.finder = PinnedProjectFinder(self.source_root, self.before, self.requests, self.violations)
        self.path_insertions = []
        self.started = False

    def __enter__(self):
        require_fresh_project_modules(sys.modules)
        self.old_path = list(sys.path)
        self.old_meta_path = list(sys.meta_path)
        self.old_dont_write_bytecode = sys.dont_write_bytecode
        sys.path.insert(0, str(self.source_root))
        self.path_insertions.append(str(self.source_root))
        sys.meta_path.insert(0, self.finder)
        sys.dont_write_bytecode = True
        self.started = True
        return self

    def audit(self):
        self.imports.update(audit_module_origins(self.source_root, self.before, sys.modules))
        if self.violations:
            raise SourceIsolationError("선택 원본의 가져오기 차단 기록이 있습니다.")

    def __exit__(self, exc_type, exc_value, traceback):
        isolation_error = None
        try:
            self.audit()
            self.after = source_manifest(self.source_root)
            self.unchanged = self.before == self.after
            if not self.unchanged:
                raise SourceIsolationError("실행 중 선택 src의 파일 목록 또는 바이트가 바뀌었습니다.")
        except Exception as error:
            isolation_error = error
            self.violations.append({"stage": "final_source_audit", "exception": type(error).__name__, "message": str(error)})
        finally:
            sys.path[:] = self.old_path
            sys.meta_path[:] = self.old_meta_path
            sys.dont_write_bytecode = self.old_dont_write_bytecode
        if isolation_error is not None:
            raise isolation_error
        return False

    def receipt(self):
        return {"requested_src": self.requested, "resolved_src": str(self.source_root),
                "path_insertions": self.path_insertions,
                "project_fallback_policy": "deny_installed_and_editable_fallback",
                "fresh_process_required": True, "bytecode_writes_disabled": self.started,
                "source_bytecode_cache_reads": "bypassed_for_python_source_modules",
                "manifest_before": self.before, "manifest_after": self.after,
                "source_unchanged": self.unchanged,
                "imported_module_count": len(self.imports), "imported_module_origins": self.imports,
                "module_spec_requests": self.requests, "violations": self.violations}


def require_source_option(run_runtime, source):
    if run_runtime and source is None:
        raise ValueError("--run-runtime에는 명시적인 --src가 필요합니다.")
    if not run_runtime and source is not None:
        raise ValueError("--src는 --run-runtime에서만 사용합니다. 모의 점검에서 후보 원본을 읽지 않습니다.")


def synthetic_preflight():
    """가짜 파일과 모듈 DTO만 사용하며 어떤 g2p_ko 코드도 가져오지 않는다."""
    checks = {}
    checks["원래_동결_보존"] = frozen.check_freeze()["cases"] == 78
    try:
        require_source_option(True, None)
        checks["런타임_src_필수"] = False
    except ValueError:
        checks["런타임_src_필수"] = True
    require_source_option(False, None)
    checks["모의점검_src_불필요"] = True
    with tempfile.TemporaryDirectory(prefix="r42_v2_synthetic_", dir=ROOT) as temporary:
        base = Path(temporary)
        if base.resolve().parent != ROOT.resolve():
            raise SourceIsolationError("모의 임시 폴더가 독립 참조 범위를 벗어났습니다.")
        checks["모의임시폴더_정리범위_확인"] = True
        source = base / "selected_src"
        package = source / "g2p_ko"
        package.mkdir(parents=True)
        init = package / "__init__.py"
        model = package / "model.py"
        init.write_text("# 모의 패키지 파일이며 실행하지 않는다.\n", encoding="utf-8")
        model.write_text("# 모의 모델 파일이며 실행하지 않는다.\n", encoding="utf-8")
        outside = base / "selected_src_other" / "g2p_ko" / "model.py"
        outside.parent.mkdir(parents=True)
        outside.write_text("# 범위 밖의 모의 파일이다.\n", encoding="utf-8")
        manifest = source_manifest(source)
        checks["선택원본_전체_목록"] = set(manifest["files"]) == {"g2p_ko/__init__.py", "g2p_ko/model.py"}
        checks["선택원본_해시_재현"] = source_manifest(source) == manifest
        module = SimpleNamespace(__file__=str(model), __spec__=SimpleNamespace(origin=str(model)))
        top = SimpleNamespace(__file__=str(init), __spec__=SimpleNamespace(origin=str(init)), __path__=[str(package)])
        observed = audit_module_origins(source, manifest, {"g2p_ko": top, "g2p_ko.model": module})
        checks["선택원본_모듈_출처"] = set(observed) == {"g2p_ko", "g2p_ko.model"}
        checks["접두사_유사경로_차단"] = not inside(outside, source)
        requests, violations = [], []
        finder = PinnedProjectFinder(source, manifest, requests, violations)
        spec = finder.find_spec("g2p_ko")
        checks["선택원본_명세_고정"] = Path(spec.origin).resolve() == init.resolve()
        checks["남은_pyc_미사용_로더"] = isinstance(spec.loader, VerifiedSourceLoader)
        checks["다른패키지_검색_불개입"] = finder.find_spec("unrelated_package") is None

        def rejected(label, function):
            try:
                function()
                checks[label] = False
            except SourceIsolationError:
                checks[label] = True

        rejected("설치본_대체_차단", lambda: finder.find_spec("g2p_ko.absent", [str(package)]))
        rejected("범위밖_모듈파일_거부", lambda: audit_module_origins(source, manifest, {"g2p_ko.model": SimpleNamespace(__file__=str(outside), __spec__=SimpleNamespace(origin=str(outside)))}))
        rejected("명세_출처_불일치_거부", lambda: audit_module_origins(source, manifest, {"g2p_ko.model": SimpleNamespace(__file__=str(model), __spec__=SimpleNamespace(origin=str(outside)))}))
        rejected("패키지_외부검색범위_거부", lambda: audit_module_origins(source, manifest, {"g2p_ko": SimpleNamespace(__file__=str(init), __spec__=SimpleNamespace(origin=str(init)), __path__=[str(outside.parent)])}))
        rejected("선행_가져오기_거부", lambda: require_fresh_project_modules({"g2p_ko.model": module}))
        rejected("파일출처_누락_거부", lambda: audit_module_origins(source, manifest, {"g2p_ko.model": SimpleNamespace()}))
        new_file = package / "new.py"
        new_file.write_text("# 동결 뒤 추가한 모의 파일이다.\n", encoding="utf-8")
        rejected("실행전_목록밖_모듈_거부", lambda: file_record(str(new_file), source, manifest))
        checks["파일추가_변경검출"] = source_manifest(source) != manifest
        original_bytes = model.read_bytes()
        model.write_text("# 바뀐 모의 파일이다.\n", encoding="utf-8")
        rejected("모듈_바이트변경_거부", lambda: file_record(str(model), source, manifest))
        checks["원본_변경검출"] = source_manifest(source) != manifest
        model.write_bytes(original_bytes)
        # 이 폴더는 위에서 만든 임시 모의 파일만 소유하며 생산 원본이 아니다.
        new_file.unlink()
        checks["모의원본_복원확인"] = source_manifest(source) == manifest
        clean_session = SourceSession(source)
        before_path = list(sys.path)
        before_meta = list(sys.meta_path)
        with clean_session:
            checks["선택_src만_경로추가"] = sys.path == [str(source.resolve())] + before_path
            checks["가져오기_방어_최우선"] = sys.meta_path[0] is clean_session.finder
            checks["바이트코드_쓰기_금지"] = sys.dont_write_bytecode is True
        checks["기존_검색경로_복원"] = sys.path == before_path and sys.meta_path == before_meta
        checks["실행후_원본_해시_동일"] = clean_session.receipt()["source_unchanged"] is True
    checks["생산_모듈_미수입"] = not any(project_name(name) for name in sys.modules)
    return {"runner_version": RUNNER_VERSION, "synthetic_only": True,
            "project_runtime_imported": not checks["생산_모듈_미수입"],
            "kiwi_executed": False, "checks": checks, "all_checks_passed": all(checks.values()),
            "new_authority_binding": "unbound"}


def run_pinned(cases, invalid, session):
    """공개 평가마다 가져온 모듈 출처를 확인하고 격리 위반이면 중단한다."""
    rows, constructors = [], []
    for case in cases:
        try:
            observation = binding.evaluate(copy.deepcopy(case["input"]))
            row = {**v1.score_available(case, observation), "observation": observation}
        except Exception as error:
            row = {"available_metrics_passed": False, "acceptance": "runtime_or_binding_exception",
                   "exception": type(error).__name__, "message": str(error), "metrics": {"runtime": "failed"}}
        session.audit()
        rows.append({"case_id": case["case_id"], "evidence_scope": case["evidence_scope"], **row})
    for case in invalid:
        try:
            actual = binding.construct_invalid({"model": case["model"], "args": copy.deepcopy(case["args"])})
        except Exception as error:
            actual = type(error).__name__
        session.audit()
        constructors.append({"case_id": case["case_id"], "evidence_scope": "constructor_only",
                             "passed": actual == case["expected_exception"], "observed_exception": actual})
    by_scope = defaultdict(Counter)
    for row in rows:
        for metric, state in row["metrics"].items():
            by_scope[row["evidence_scope"]][metric + ":" + state] += 1
    return {"rows": rows, "constructor_rows": constructors, "by_scope": {k: dict(v) for k, v in by_scope.items()},
            "acceptance": "incomplete_unbound_authority",
            "available_metrics_passed": all(row["available_metrics_passed"] for row in rows)
                                        and all(row["passed"] for row in constructors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path)
    parser.add_argument("--run-runtime", action="store_true")
    parser.add_argument("--preflight-synthetic", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        require_source_option(args.run_runtime, args.src)
    except ValueError as error:
        parser.error(str(error))
    if args.run_runtime and args.preflight_synthetic:
        parser.error("런타임 실행과 모의 점검을 섞지 않습니다.")
    _, cases, invalid = v1._manifest()
    target = v1._new_report_path(args.report) if args.report is not None else None
    if args.run_runtime:
        if target is None:
            parser.error("런타임 실행에는 새 --report 경로가 필요합니다.")
        session = SourceSession(args.src)
        try:
            with session:
                result = run_pinned(cases, invalid, session)
        except Exception as error:
            result = {"acceptance": "source_isolation_or_runtime_abort", "available_metrics_passed": False,
                      "exception": type(error).__name__, "message": str(error)}
        result["source_origin"] = session.receipt()
    elif args.preflight_synthetic:
        result = synthetic_preflight()
    else:
        print(json.dumps({"freeze_valid": True, "cases": len(cases), "constructor_invalid": len(invalid),
                          "runtime_imported": False, "runtime_requires_explicit_src": True}, ensure_ascii=False))
        return 0
    frozen.check_freeze()
    result.update({"created_at_utc": datetime.now(timezone.utc).isoformat(), "runner_version": RUNNER_VERSION,
                   "python_executable": sys.executable, "python_version": sys.version,
                   "binding_version": binding.BINDING_VERSION, "freeze_sha256": v1._sha(ROOT / "FREEZE.json"),
                   "runner_v2_sha256": v1._sha(ROOT / "evaluator_runner_v2.py"),
                   "runner_v1_sha256": v1._sha(ROOT / "evaluator_runner_v1.py"),
                   "binding_v1_sha256": v1._sha(ROOT / "evaluator_binding_v1.py"),
                   "helper_sha256": v1._sha(ROOT / "public_entrypoints_helper.py")})
    if target is not None:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k not in ("rows", "constructor_rows", "checks", "source_origin")}
    if args.preflight_synthetic:
        summary["check_count"] = len(result["checks"])
    print(json.dumps(summary, ensure_ascii=False))
    passed = result["all_checks_passed"] if args.preflight_synthetic else result["available_metrics_passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
