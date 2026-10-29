"""동결된 생산적 준말의 표기·원자 유래 계약을 선택한 소스에서 확인한다."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def test_frozen_productive_contractions_and_provenance(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fixture = Path(__file__).parent / "fixtures/productive_contractions"
    package = json.loads((fixture / "packaging_manifest.json").read_text(encoding="utf-8"))
    for item in package["files"]:
        assert hashlib.sha256((fixture / item["path"]).read_bytes()).hexdigest() == item["sha256"]

    reference = tmp_path / "productive_contractions"
    shutil.copytree(fixture, reference)
    runner = reference / "binding/run_semantic_refs_v2.py"
    output = runner.parent / "reports/focused"
    selected_source = (root / "src").resolve()
    process = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-B", str(runner),
         "--src", str(selected_source), "--out", str(output)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert Path(result["source"]).resolve() == selected_source
    assert result["runner_sha256"] == package["runner_sha256"]
    assert result["gold_manifest_sha256"] == package["gold_manifest_sha256"]
    assert {name: item["path"] for name, item in result["source_support_closure"].items()} == package["native_support_closure"]
    assert result["phone_gold"] == 0
    assert result["pronunciation_accuracy_claimed"] is False

    gold = json.loads((reference / "Expected_Facts_KO.json").read_text(encoding="utf-8"))
    expected_ids = {row["사례"] for row in gold["사례"]}
    cases = {row["id"]: row for row in result["cases"]}
    assert len(result["cases"]) == len(cases) == len(expected_ids) == 48
    assert set(cases) == expected_ids
    positive_ids = {row["사례"] for row in gold["사례"]
                    if row["구분"] in {"규범_인용_예", "생산적_일반화"}}
    assert len(positive_ids) == 20
    assert all(cases[cid]["status"] == "pass" for cid in positive_ids)

    # 기존의 완전 결속 사례를 미결속으로 낮춰 보호·유래 검사를 생략하지 않는다.
    binding = package["frozen_binding"]
    assert all(cases[cid]["status"] == "pass" for cid in binding["fully_bound_ids"])
    abstract_ids = set(binding["abstract_ids"])
    assert {cid for cid, case in cases.items() if case["scope"] == "abstract_condition"} == abstract_ids
    assert all(cases[cid]["scope"] == "actual_or_packaging" for cid in expected_ids - abstract_ids)
    for case in cases.values():
        assert case["status"] in {"pass", "partial_pass", "unbound"}, case
        assert all(check["ok"] is True for check in case["checks"]), case
        if case["status"] == "pass":
            assert case["checks"] and not case["unbound_facts"], case
        elif case["status"] == "partial_pass":
            assert case["checks"] and case["unbound_facts"], case
        else:
            assert case["unbound_facts"], case
    # 부분·미결속 항목이 향후 지원되어 pass가 되는 것은 허용한다.
