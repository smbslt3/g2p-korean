# SPDX-License-Identifier: MIT
"""동결된 유한 참조를 현재 src의 표면 증명에만 연결한다."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures" / "irregular_ds"
SUPPORT = (
    "g2p_ko/analysis_features.py",
    "g2p_ko/model.py",
    "g2p_ko/korean/hangul.py",
    "g2p_ko/korean/word_grammar.py",
    "g2p_ko/korean/surface_proof.py",
)


def test_irregular_ds_frozen_semantics_and_provenance():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    payloads = {name: (FIXTURES / name).read_bytes() for name in manifest["files"]}
    assert {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()} == manifest["files"]
    assert set(payloads) == {"check_references.py", "references.jsonl"}
    refs = [json.loads(line) for line in payloads["references.jsonl"].decode("utf-8").splitlines()]
    assert len(refs) == 32 and manifest["phone_gold"] == 0
    assert all(ref["expect"]["phone_gold"] == 0 for ref in refs)
    semantic = {ref["id"]: ref for ref in refs if ref["binding"] == "semantic_unbound"}
    abstract = sorted(ref["id"] for ref in refs if ref["binding"] == "abstract_unbound")
    assert len(semantic) == 25 and abstract == [f"A{i:02}" for i in range(1, 8)]

    # 현재 src의 다섯 파일만 HERE 아래 임시 작업공간으로 옮긴다.
    source_root = (ROOT / "src").resolve()
    with tempfile.TemporaryDirectory(prefix="_irregular_ds_", dir=HERE) as temporary:
        work = Path(temporary).resolve()
        selected_src = work / "src"
        selected_hashes = {}
        for relative in SUPPORT:
            original = (source_root / relative).resolve()
            original.relative_to(source_root)
            data = original.read_bytes()
            target = selected_src / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            selected_hashes[relative] = hashlib.sha256(data).hexdigest()
        assert {p.relative_to(selected_src).as_posix() for p in selected_src.rglob("*") if p.is_file()} == set(SUPPORT)

        # 원래 검사기의 상대 경로 계약을 그대로 재현한다.
        round_root = work / "output" / "g2p_progressive_round44_20261028"
        checker = round_root / "independent_checker" / "check_references.py"
        reference = round_root / "independent_refs" / "references.jsonl"
        for target, name in ((checker, "check_references.py"), (reference, "references.jsonl")):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payloads[name])
        out = work / "report"
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", str(checker),
             "--src", str(selected_src), "--out", str(out)],
            cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert Path(report["source_root"]).resolve() == selected_src.resolve()
        assert selected_src.resolve() != source_root
        assert len(report["source_files"]) == 5
        assert {item["path"]: item["sha256"] for item in report["source_files"]} == selected_hashes

        # 미연결 조건은 실행 통과로 세지 않고 공개 필드의 결과만 대조한다.
        assert report["phone_gold"] == report["weak_failures"] == report["strong_failures"] == 0
        assert report["semantic_records"] == 25
        assert report["strong_unbound"] == ["G10", "G11", "G12"]
        assert report["abstract_unbound"] == abstract
        rows = report["records"]
        assert len(rows) == 25 and {row["id"] for row in rows} == set(semantic)
        strong_count = 0
        for row in rows:
            ref = semantic[row["id"]]
            expected_weak = ref["expect"]["weak_spelling"] == "성공"
            assert row["weak"] == row["expected_weak"] == expected_weak
            assert row["weak_pass"] is True
            if row["id"] in report["strong_unbound"]:
                assert row["strong"] == []
                assert row["strong_status"] == "원시범위_미연결_철자길이불일치"
                continue
            assert row["strong_status"] == "연결됨"
            assert [case["start"] for case in row["strong"]] == [0, 7]
            expected_strong = ref["expect"]["strong_token_proof"] != "거부"
            for case in row["strong"]:
                assert case["present"] == case["expected_present"] == expected_strong
                assert case["pass"] is True and case["errors"] == []
                strong_count += 1
        assert strong_count == 44
