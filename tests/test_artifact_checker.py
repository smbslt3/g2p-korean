from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from tools.check_artifacts import check_artifact


_DATA = Path(__file__).resolve().parents[1] / "src" / "g2p_ko" / "data"
_LICENSE_TEXT = (Path(__file__).resolve().parents[1] / "LICENSE").read_text(
    encoding="utf-8"
)
_KIWI_REQUIREMENT = "kiwipiepy>=0.23.2"
_MODEL_NOTICE = """159. 숫자가 포함된 패턴 발화 데이터
https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&dataSetSn=484
https://www.aihub.or.kr/intrcn/guid/usagepolicy.do
"""


def _valid_json_assets() -> dict[str, str]:
    return {
        f"g2p_ko/data/{name}": (_DATA / name).read_text(encoding="utf-8")
        for name in ("number_reading_model.json",)
    }


def _write_wheel(
    path: Path,
    *,
    omit_file: str | None = None,
    requirements: tuple[str, ...] = (_KIWI_REQUIREMENT,),
    provides_extra: bool = False,
    json_overrides: dict[str, str] | None = None,
    extra_files: dict[str, str | bytes] | None = None,
    license_expression: str = "MIT",
    license_text: str = _LICENSE_TEXT,
    notice_text: str = _MODEL_NOTICE,
) -> None:
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: g2p-ko\n"
        "Version: 1.0.0\n"
        f"License-Expression: {license_expression}\n"
        "License-File: LICENSE\n"
        "License-File: NOTICE\n"
    )
    if provides_extra:
        metadata += "Provides-Extra: g2p\n"
    for requirement in requirements:
        metadata += f"Requires-Dist: {requirement}\n"
    files = {
        "g2p_ko/__init__.py": "",
        "g2p_ko/py.typed": "",
        **_valid_json_assets(),
        "g2p_ko-1.0.0.dist-info/METADATA": metadata,
        "g2p_ko-1.0.0.dist-info/licenses/LICENSE": license_text,
        "g2p_ko-1.0.0.dist-info/licenses/NOTICE": notice_text,
    }
    files.update(json_overrides or {})
    files.update(extra_files or {})
    if omit_file is not None:
        del files[omit_file]
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_artifact_checker_accepts_required_runtime_dependency(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact)

    report = check_artifact(artifact)

    assert report["ok"] is True
    assert report["checks"]["package_data"]["ok"] is True
    assert report["checks"]["package_payload"]["ok"] is True
    assert report["checks"]["license"]["ok"] is True
    assert report["checks"]["license_body"]["ok"] is True
    assert report["checks"]["no_legacy"]["ok"] is True
    assert report["checks"]["json_assets"]["ok"] is True
    assert report["checks"]["archive_hygiene"]["ok"] is True
    assert report["checks"]["license_metadata"]["ok"] is True
    assert report["checks"]["model_notice"]["ok"] is True
    assert report["checks"]["runtime_dependencies"]["ok"] is True


def test_artifact_checker_rejects_invalid_json_schema(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    member = "g2p_ko/data/number_reading_model.json"
    _write_wheel(artifact, json_overrides={member: "{}"})

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["json_assets"]["ok"] is False


def test_artifact_checker_rejects_malformed_packaged_json(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(
        artifact,
        json_overrides={"g2p_ko/data/number_reading_model.json": "{"},
    )

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["json_assets"]["ok"] is False


def test_artifact_checker_rejects_unpublished_extra_declaration(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, provides_extra=True)

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["runtime_dependencies"]["ok"] is False


@pytest.mark.parametrize(
    "missing_file, check",
    [
        ("g2p_ko/data/number_reading_model.json", "package_data"),
        ("g2p_ko/py.typed", "package_data"),
        ("g2p_ko-1.0.0.dist-info/METADATA", "runtime_dependencies"),
        ("g2p_ko-1.0.0.dist-info/licenses/LICENSE", "license"),
        ("g2p_ko-1.0.0.dist-info/licenses/NOTICE", "license"),
    ],
)
def test_artifact_checker_rejects_missing_required_file(
    tmp_path: Path,
    missing_file: str,
    check: str,
) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, omit_file=missing_file)

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"][check]["ok"] is False


@pytest.mark.parametrize(
    "member",
    [
        "g2p_ko/__pycache__/engine.cpython-313.pyc",
        "docs/evaluation.csv",
    ],
)
def test_artifact_checker_rejects_cache_and_table_files(
    tmp_path: Path,
    member: str,
) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, extra_files={member: b"forbidden"})

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["archive_hygiene"]["ok"] is False


def test_artifact_checker_rejects_unexpected_package_binary(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, extra_files={"g2p_ko/data/lexicon.bin": b"opaque"})

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["package_payload"]["ok"] is False


def test_artifact_checker_rejects_non_mit_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, license_expression="Apache-2.0")

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["license_metadata"]["ok"] is False


def test_artifact_checker_rejects_non_mit_license_body(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, license_text="not a license")

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["license_body"]["ok"] is False


def test_artifact_checker_rejects_notice_without_model_source(tmp_path: Path) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, notice_text="")

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["model_notice"]["ok"] is False


@pytest.mark.parametrize(
    "requirements",
    [
        (),
        ("kiwipiepy",),
        ("kiwipiepy>=0.23.3",),
        ("kiwipiepy @ git+https://github.com/bab2min/kiwipiepy.git@main",),
        ("requests>=2", _KIWI_REQUIREMENT),
    ],
)
def test_artifact_checker_rejects_incorrect_runtime_dependency(
    tmp_path: Path,
    requirements: tuple[str, ...],
) -> None:
    artifact = tmp_path / "g2p_ko-1.0.0-py3-none-any.whl"
    _write_wheel(artifact, requirements=requirements)

    report = check_artifact(artifact)

    assert report["ok"] is False
    assert report["checks"]["runtime_dependencies"]["ok"] is False
