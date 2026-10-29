"""명시적인 Unicode 경로의 원문 보존과 보호 경계를 검증한다."""

from __future__ import annotations

import unicodedata

import pytest

from g2p_ko import G2P, KoreanTTSNormalizer
from g2p_ko.scanner import ProtectedRange, scan_protected


_PATHS = (
    "./국물/readme.txt",
    "./국물/같이",
    "../국물/같이",
    "../../국물/5kg/같이",
    "./국물/../같이/",
    r".\국물\readme.txt",
    r".\국물\같이",
    r"..\국물\같이",
    r"..\..\국물\5kg\같이",
    ".\\국물\\..\\같이\\",
    r"\\국물\공유\readme.txt",
    r"\\국물\공유\같이",
    "\\\\국물\\공유\\5kg\\같이\\",
)
_OTHER_SCRIPT_PATHS = (
    "./국물/資料/かな/café.txt",
    r"\\국물\資料\かな\café.txt",
)


@pytest.fixture(scope="module")
def g2p() -> G2P:
    return G2P()


def spelled_path(path: str) -> str:
    """경로 보호 없이 읽어야 하는 영문 부분의 고정 기대값이다."""
    return (path.replace("readme", "알이에이디엠이").replace("txt", "티엑스티")
            .replace("kg", "케이지").replace("caf", "씨에이에프"))


def pronounced_path(path: str) -> str:
    return (spelled_path(path).replace("국물", "궁물").replace("같이", "가치")
            .replace("알이에이디엠이", "아리에이디에미").replace("티엑스티", "티엑쓰티"))


@pytest.mark.parametrize("path", _PATHS + _OTHER_SCRIPT_PATHS)
def test_unicode_path_is_one_complete_protected_range(path: str) -> None:
    kind = "windows_path" if "\\" in path else "posix_path"

    assert scan_protected(path) == (ProtectedRange(0, len(path), kind),)


@pytest.mark.parametrize("path", _PATHS)
def test_g2p_reads_unicode_paths_while_legacy_normalizer_preserves_them(g2p: G2P, path: str) -> None:
    normalizer = KoreanTTSNormalizer()
    normalized = normalizer.convert(path)

    assert normalizer(path) == normalized.normalized_text == path
    assert normalized.complete
    assert normalized.rewrites == ()
    assert normalized.diagnostics == ()
    for normalize in (True, False):
        result = g2p.convert(path, normalize=normalize)
        assert g2p(path, normalize=normalize) == result.surface_pronunciation == pronounced_path(path)
        assert result.normalized_text == spelled_path(path)
        assert result.complete is ("5" not in path)
        assert result.diagnostics.normalization.diagnostics == ()
        assert [d.code for d in result.diagnostics.pronunciation.diagnostics] == (
            ["unconverted_numeric"] if "5" in path else []
        )


@pytest.mark.parametrize("path", _PATHS)
def test_nfd_public_paths_keep_the_normalized_whole_path(g2p: G2P, path: str) -> None:
    source = unicodedata.normalize("NFD", path)
    normalizer = KoreanTTSNormalizer()

    assert normalizer(source) == normalizer.convert(source).normalized_text == path
    for normalize in (True, False):
        result = g2p.convert(source, normalize=normalize)
        assert result.source == source
        assert result.normalized_text == spelled_path(path)
        assert result.surface_pronunciation == pronounced_path(path)
        assert g2p(source, normalize=normalize) == pronounced_path(path)
        assert result.complete is ("5" not in path)


@pytest.mark.parametrize(
    "path", ["./국물/readme.txt", r".\국물\readme.txt", r"\\국물\공유\readme.txt"]
)
@pytest.mark.parametrize("particle", ["를", "에서만"])
def test_filename_particles_and_neighboring_prose_are_outside_path(
    g2p: G2P, path: str, particle: str
) -> None:
    prefix = "국물 "
    source = prefix + path + particle + " 같이."
    kind = "windows_path" if "\\" in path else "posix_path"

    assert scan_protected(source) == (
        ProtectedRange(len(prefix), len(prefix) + len(path), kind),
    )
    result = g2p.convert(source)
    assert result.normalized_text == "국물 " + spelled_path(path) + particle + " 같이."
    assert result.surface_pronunciation == "궁물 " + pronounced_path(path) + particle + " 가치."
    assert g2p(source) == result.surface_pronunciation
    assert result.complete


@pytest.mark.parametrize("path", ["./국물/같이", r".\국물\같이", r"\\국물\공유\같이"])
def test_korean_only_filename_is_not_mistaken_for_trailing_particle(path: str) -> None:
    source = path + " 국물"

    assert [source[item.start : item.end] for item in scan_protected(source)] == [path]


@pytest.mark.parametrize("prefix", ["./국물/", ".\\국물\\", "\\\\국물\\공유\\"])
@pytest.mark.parametrize("unsafe", ["\x00", "\x0b", "\u200b", "\ue000", "\u0378"])
def test_unsafe_path_character_remains_unprotected_and_diagnosed(
    g2p: G2P, prefix: str, unsafe: str
) -> None:
    source = prefix + "같이" + unsafe + "국물"
    unsafe_index = source.index(unsafe)

    assert all(not (item.start <= unsafe_index < item.end) for item in scan_protected(source))
    for normalize in (True, False):
        result = g2p.convert(source, normalize=normalize)
        assert unsafe in result.normalized_text
        assert unsafe in result.surface_pronunciation
        assert not result.complete
        diagnostics = (
            result.diagnostics.normalization.diagnostics
            + result.diagnostics.pronunciation.diagnostics
        )
        assert "unsupported_character" in {item.code for item in diagnostics}


@pytest.mark.parametrize(
    "path", ("./국물/ж.txt", r".\국물\ж.txt", r"\\국물\공유\ж.txt") + _OTHER_SCRIPT_PATHS
)
def test_unsupported_path_script_is_preserved_but_still_diagnosed(g2p: G2P, path: str) -> None:
    result = g2p.convert(path)

    assert len(scan_protected(path)) == 1
    assert result.normalized_text == spelled_path(path)
    assert result.surface_pronunciation == pronounced_path(path)
    assert not result.complete
    assert "unsupported_script" in {
        item.code for item in result.diagnostics.pronunciation.diagnostics
    }


@pytest.mark.parametrize(
    "source",
    [
        "국물\\같이",
        r"A\B",
        "3\\개",
        "3\\개를 읽습니다.",
        "3/4",
        "290㎞/h",
        "일반 문장./다음 문장",
        "국물./같이",
        "국물.\\같이",
    ],
)
def test_unicode_support_does_not_expand_ambiguous_bare_paths(source: str) -> None:
    assert scan_protected(source) == ()
