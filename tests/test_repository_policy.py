"""저장소에서만 적용되는 릴리스 정책과 CI 구성을 검사한다."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def test_project_metadata_and_dependencies_are_minimal() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "g2p-ko"
    assert metadata["project"]["dependencies"] == ["kiwipiepy==0.24.1"]
    assert set(metadata["project"]["optional-dependencies"]) == {"number-reader"}
    assert "onnxruntime>=1.30,<2; python_version >= '3.11'" in metadata["project"]["optional-dependencies"]["number-reader"]
    assert metadata["project"]["license"] == "MIT"
    assert metadata["project"]["license-files"] == ["LICENSE", "NOTICE"]
    assert metadata["project"]["urls"]["Repository"] == "https://github.com/smbslt3/g2p-korean"
    assert metadata["build-system"]["requires"] == ["hatchling==1.31.0"]
    assert "Programming Language :: Python :: 3.14" in metadata["project"]["classifiers"]
    assert "sources" not in metadata["tool"]["uv"]
    assert "metadata" not in metadata["tool"]["hatch"]
    assert "kiwipiepy==0.24.1" not in metadata["dependency-groups"]["dev"]
    assert metadata["tool"]["uv"]["extra-build-dependencies"]["kiwipiepy"] == [
        "cmake>=3.12"
    ]
    assert "force-include" not in metadata["tool"]["hatch"]["build"]["targets"]["wheel"]
    sdist_include = metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert {"/src", "/tests", "/tools", "/docs"} <= set(sdist_include)
    assert {"/README.md", "/README.en.md", "/NOTICE"} <= set(sdist_include)
    assert not any(item.startswith("/benchmarks/") for item in sdist_include)
    assert metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"] == [
        "/tests/test_repository_policy.py",
        "/docs/ADVERSARIAL_*",
        "/docs/G2P_IMPLEMENTATION_FINDINGS_*",
        "/docs/KIWI_*",
        "/docs/KOREAN_G2P_IMPLEMENTATION_COMPARISON_*",
    ]


def test_ci_covers_representative_runtimes_and_reproducible_builds() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    for runtime in (
        '- os: ubuntu-latest\n            python-version: "3.10"',
        '- os: ubuntu-latest\n            python-version: "3.11"',
        '- os: ubuntu-latest\n            python-version: "3.12"',
        '- os: ubuntu-latest\n            python-version: "3.13"',
        '- os: ubuntu-latest\n            python-version: "3.14"',
        '- os: windows-latest\n            python-version: "3.13"',
    ):
        assert runtime in workflow
    assert "cancel-in-progress: true" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "SOURCE_DATE_EPOCH" in workflow
    assert "재현 빌드 SHA-256 비교" in workflow


def test_kiwi_lock_uses_a_registry_release() -> None:
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    kiwi = next(item for item in lock["package"] if item["name"] == "kiwipiepy")

    assert kiwi["source"] == {"registry": "https://pypi.org/simple"}
    assert kiwi["version"] == "0.24.1"
    model = next(item for item in lock["package"] if item["name"] == "kiwipiepy-model")
    assert model["version"] == "0.24.0"
