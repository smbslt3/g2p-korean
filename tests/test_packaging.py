"""sdist 안에서도 실행 가능한 공개 패키지 계약을 검증한다."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
import subprocess
import sys
from inspect import signature


def test_normalizer_and_normalized_g2p_import_without_kiwi() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = f"""
import importlib.abc
import sys

sys.path.insert(0, {str(source_root)!r})

class BlockKiwi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "kiwipiepy" or fullname.startswith("kiwipiepy."):
            raise AssertionError("normalizer import가 Kiwi를 요청했습니다.")
        return None

sys.meta_path.insert(0, BlockKiwi())

from g2p_ko import G2P, KoreanTTSNormalizer, normalize_numbers

assert KoreanTTSNormalizer()("3개") == "세 개"
assert callable(G2P())
assert normalize_numbers("사과 3개") == "사과 3개"
assert G2P()("123") == "123"
assert "kiwipiepy" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_public_detailed_result_is_available_from_top_level_package() -> None:
    from g2p_ko import DiagnosticReport, G2PDiagnostics, G2PResult

    assert DiagnosticReport.__module__ == "g2p_ko.model"
    assert G2PDiagnostics.__module__ == "g2p_ko.model"
    assert G2PResult.__module__ == "g2p_ko.model"


def test_foundation_data_is_package_resource() -> None:
    package = importlib.resources.files("g2p_ko")
    assert package.joinpath("py.typed").is_file()
    assert not package.joinpath("data/number_reading_model.json").is_file()
    assert not package.joinpath("data/number_reading_lm.json").is_file()


def test_public_constructors_do_not_expose_backend_selection() -> None:
    from g2p_ko import G2P, KoreanTTSNormalizer

    assert set(signature(G2P).parameters) == {"max_length"}
    assert not {"kiwi", "analyzer"} & set(signature(KoreanTTSNormalizer).parameters)
