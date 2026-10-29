"""넓은 영문 철자 읽기 행렬을 실행하고 재현 보고서를 저장한다."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import importlib.util
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import unicodedata


def _load_matrix_module(project_root: Path):
    """테스트에 정의된 결정적 샘플 수를 구현 글자표와 분리해 읽는다."""

    test_path = project_root / "tests" / "test_english_reading_matrix.py"
    spec = importlib.util.spec_from_file_location("english_reading_matrix", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"테스트 모듈을 불러올 수 없습니다: {test_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_report_path(project_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        project_root
        / "output"
        / "english_review"
        / f"english_reading_matrix_{timestamp}.json"
    )


def _source_hash_manifest(project_root: Path) -> dict[str, object]:
    paths = sorted((project_root / "src" / "g2p_ko").rglob("*.py"))
    paths.extend(
        (
            project_root / "tests" / "test_english_reading_matrix.py",
            project_root / "tools" / "verify_english_reading.py",
        )
    )
    unique_paths = sorted(set(paths))
    file_hashes: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for path in unique_paths:
        relative = path.relative_to(project_root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_hashes[relative] = digest
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return {
        "algorithm": "sha256",
        "aggregate_sha256": aggregate.hexdigest(),
        "files": file_hashes,
    }


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _git_head(project_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _run(project_root: Path, report_path: Path) -> int:
    sys.path.insert(0, str(project_root))
    matrix = _load_matrix_module(project_root)
    counts = matrix.matrix_sample_counts()
    source_hashes_before = _source_hash_manifest(project_root)
    test_path = project_root / "tests" / "test_english_reading_matrix.py"
    cache_root = Path.home() / ".cache" / "g2p-english-reading"
    cache_root.mkdir(parents=True, exist_ok=True)
    basetemp = cache_root / datetime.now(timezone.utc).strftime("pytest-%Y%m%dT%H%M%S-%f")

    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(basetemp),
        "--tb=short",
        str(test_path),
    ]
    completed = subprocess.run(
        command,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    source_hashes_after = _source_hash_manifest(project_root)
    if source_hashes_before != source_hashes_after:
        raise RuntimeError("검사 도중 소스가 변경되어 해당 결과를 확정할 수 없습니다.")
    output = (completed.stdout + completed.stderr).strip()
    summary_match = re.search(
        r"(?:\d+ (?:passed|failed|skipped|error|errors)(?:, )?)+(?: in [^\r\n]+)?",
        output,
    )
    summary = summary_match.group(0) if summary_match else "요약을 읽지 못했습니다."

    summary_counts = {
        label: int(value)
        for value, label in re.findall(
            r"(\d+)\s+(passed|failed|skipped|errors?)\b", summary
        )
    }
    passed = summary_counts.get("passed", 0)
    failed = summary_counts.get("failed", 0)
    skipped = summary_counts.get("skipped", 0)
    errors = summary_counts.get("error", 0) + summary_counts.get("errors", 0)
    failure_lines = [
        line.strip()
        for line in output.splitlines()
        if line.startswith(("FAILED ", "ERROR "))
    ]

    report = {
        "schema_version": 1,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "repository": project_root.name,
        "git_head": _git_head(project_root),
        "environment": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_full_version": sys.version,
            "unicode_database_version": unicodedata.unidata_version,
            "pytest_version": _version("pytest"),
            "kiwipiepy_version": _version("kiwipiepy"),
            "platform": platform.platform(),
        },
        "source_hash_manifest": source_hashes_after,
        "source_unchanged_during_validation": True,
        "validator": {
            "test_file": str(test_path.relative_to(project_root)).replace("\\", "/"),
            "command": command,
            "exit_code": completed.returncode,
            "summary": summary,
            "pytest_cases_passed": passed,
            "pytest_cases_failed": failed,
            "pytest_cases_skipped": skipped,
            "pytest_collection_or_execution_errors": errors,
            "pytest_failure_lines": failure_lines,
            "batched_end_to_end_item_conversions": counts[
                "batched_end_to_end_item_conversions"
            ],
            "unique_sources_across_bulk_batches": counts[
                "unique_sources_across_bulk_batches"
            ],
            "counting_note": "pytest 사례, 입력별 API 변환, 한 입력에 포함된 토큰, Unicode 코드 포인트는 단위가 다르므로 합산하지 않습니다.",
            "matrix_counts_by_unit": counts,
            "random_seed": 20261023,
            "coverage_categories": [
                "ASCII A-Z 및 a-z 각 글자",
                "ASCII 알파벳의 모든 676개 순서쌍",
                "고정 seed로 만든 256개 임의 식별자",
                "Unicode 전체 범위에서 숫자를 제외하고 NFKC 결과가 ASCII 알파벳인 문자",
                "URL, 이메일, Windows/POSIX 경로, 인라인 코드와 여러 줄 fenced code",
                "구두점, 공백, 밑줄 식별자, 영어와 한글 혼합",
                "결합문자, zero-width joiner, 그리스 문자와 악센트 라틴 문자",
                "ASCII, 전각, 위첨자, 로마 숫자와 아라비아 숫자의 앞단 잔류 진단",
                "NFC/NFD, source span, scalar/batch, trace/no-trace와 입력 길이 제한",
            ],
            "assertion_coverage": [
                "각 letter oracle은 독립 명시 표로 normalized_text를 비교",
                "각 batch source는 변환 결과, 표면/정규화 길이, 완료 상태를 검증",
                "모든 관용표 항목은 대소문자·전각 표기와 다섯 조사를 변환하며 조사는 독립 종성 계산으로 선택",
                "Unicode 및 numeric source span은 보고서 source slice와 대조",
                "scalar, detailed, batch, repeated-call, shared-instance thread-pool 결과를 교차 비교",
            ],
            "oracle": "test file에 별도로 적은 26개 한국어 글자 이름과 Python 표준 Unicode 정규화",
            "numeric_policy": "isnumeric 문자는 영문 NFKC 확장보다 먼저 보존하며 앞단 숫자 변환 누락으로 진단",
        },
        "known_scope_limit": {
            "sample": "café",
            "observed_behavior": "c, a, f는 알파벳 이름으로 읽고 é는 보존하며 unsupported_script로 진단",
            "status": "영어 알파벳 및 NFKC 호환 글자 행렬 바깥의 악센트 문자는 현재 다루지 않음",
        },
        "preserved_unsupported_separator": {
            "sample": "qzx jwv",
            "observed_behavior": "문자는 보존되고 주변 ASCII 알파벳은 읽지만 unsupported_symbol 진단으로 complete=False",
        },
        "pytest_output": output,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8", newline="\n") as report_file:
        json.dump(report, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")

    print(output)
    print(f"JSON 보고서: {report_path}")
    return completed.returncode


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=_default_report_path(project_root),
        help="새 JSON 보고서 경로 (기존 파일은 덮어쓰지 않습니다)",
    )
    arguments = parser.parse_args()
    report_path = arguments.report.resolve()
    if report_path.exists():
        parser.error(f"보고서가 이미 존재합니다. 다른 --report 경로를 지정하세요: {report_path}")
    try:
        return _run(project_root, report_path)
    except FileExistsError:
        parser.error(f"보고서가 이미 존재합니다. 다른 --report 경로를 지정하세요: {report_path}")
    except subprocess.CalledProcessError as error:
        parser.error(f"pytest 버전을 읽지 못했습니다: {error}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
