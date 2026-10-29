"""공백으로 분류되는 제어 문자도 정규화 정책과 원문 span을 지킨다."""

from __future__ import annotations

import unicodedata

import pytest

from g2p_ko import ConversionPolicyError, RewriteStage, Severity, SourceSpan
from g2p_ko.normalizer import KoreanTTSNormalizer
from g2p_ko.normalizer.policy import is_permitted_whitespace, unsupported_character


_UNSAFE_WHITESPACE = "\x0b\x0c\x1c\x1d\x1e\x1f\x85"
_PERMITTED_WHITESPACE = (
    "\t\n\r \u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def _code_point_id(character: str) -> str:
    return f"U+{ord(character):04X}"


def test_all_c0_and_c1_controls_only_permit_tab_cr_lf() -> None:
    for code_point in (*range(0x20), *range(0x7F, 0xA0)):
        character = chr(code_point)
        if character in "\t\r\n":
            assert is_permitted_whitespace(character)
            assert unsupported_character(character) is None
        else:
            assert not is_permitted_whitespace(character)
            classification = unsupported_character(character)
            assert classification is not None
            assert classification[0] == "unsupported_character"


def test_unsafe_whitespace_inventory_covers_all_unicode_control_spaces() -> None:
    actual = "".join(
        chr(code_point)
        for code_point in range(0x110000)
        if chr(code_point).isspace()
        and unicodedata.category(chr(code_point)).startswith("C")
        and chr(code_point) not in "\t\r\n"
    )

    assert actual == _UNSAFE_WHITESPACE


@pytest.mark.parametrize("unsafe", _UNSAFE_WHITESPACE, ids=_code_point_id)
@pytest.mark.parametrize(
    ("prefix", "suffix", "expected_prefix", "expected_suffix"),
    [("", "", "", ""), ("가", "나", "가", "나"), ("3원", "4원", "삼 원", "사 원")],
    ids=["isolated", "plain-korean", "numeric"],
)
@pytest.mark.parametrize("policy", ["warn", "preserve"])
def test_unsafe_whitespace_is_preserved_and_incomplete_with_original_span(
    unsafe: str, prefix: str, suffix: str, expected_prefix: str, expected_suffix: str,
    policy: str,
) -> None:
    source = prefix + unsafe + suffix
    expected = expected_prefix + unsafe + expected_suffix
    normalizer = KoreanTTSNormalizer(on_ambiguous=policy)

    result = normalizer.convert(source)

    assert result.normalized_text == expected == normalizer.normalize(source)
    assert not result.complete
    if policy == "preserve":
        assert result.diagnostics == ()
    else:
        assert len(result.diagnostics) == 1
        diagnostic = result.diagnostics[0]
        assert diagnostic.code == "unsupported_character"
        assert diagnostic.severity is Severity.WARNING
        assert diagnostic.stage is RewriteStage.VERBALIZATION
        assert diagnostic.rule_id == "normalizer.unsupported_character.v1"
        assert diagnostic.source_spans == (
            SourceSpan(len(prefix), len(prefix) + 1, unsafe, len(source)),
        )


@pytest.mark.parametrize("unsafe", _UNSAFE_WHITESPACE, ids=_code_point_id)
@pytest.mark.parametrize(("prefix", "suffix"), [("", ""), ("가", "나"), ("3원", "4원")])
@pytest.mark.parametrize("method", ["normalize", "convert"])
def test_error_policy_rejects_unsafe_whitespace_in_both_paths(
    unsafe: str, prefix: str, suffix: str, method: str,
) -> None:
    source = prefix + unsafe + suffix
    normalizer = KoreanTTSNormalizer(on_ambiguous="error")

    with pytest.raises(ConversionPolicyError) as raised:
        getattr(normalizer, method)(source)

    assert raised.value.code == "unsupported_character"
    assert raised.value.rule_id == "normalizer.unsupported_character.v1"
    assert raised.value.source_span == SourceSpan(
        len(prefix), len(prefix) + 1, unsafe, len(source),
    )


@pytest.mark.parametrize("whitespace", _PERMITTED_WHITESPACE, ids=_code_point_id)
@pytest.mark.parametrize("policy", ["warn", "preserve", "error"])
def test_permitted_whitespace_remains_complete_in_fast_and_detailed_paths(
    whitespace: str, policy: str,
) -> None:
    normalizer = KoreanTTSNormalizer(on_ambiguous=policy)
    normalized_whitespace = unicodedata.normalize("NFC", whitespace)
    for source, expected in (
        (f"가{whitespace}나", f"가{normalized_whitespace}나"),
        (f"가{whitespace}3원", f"가{normalized_whitespace}삼 원"),
    ):
        result = normalizer.convert(source)

        assert result.normalized_text == expected == normalizer.normalize(source)
        assert result.complete
        assert result.diagnostics == ()


def test_control_run_after_nfc_composition_uses_original_source_span() -> None:
    source = "\u1100\u1161" + _UNSAFE_WHITESPACE + "나"
    normalizer = KoreanTTSNormalizer()

    result = normalizer.convert(source)

    assert result.normalized_text == "가" + _UNSAFE_WHITESPACE + "나"
    assert not result.complete
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].source_spans == (
        SourceSpan(2, 2 + len(_UNSAFE_WHITESPACE), _UNSAFE_WHITESPACE, len(source)),
    )
    with pytest.raises(ConversionPolicyError) as raised:
        KoreanTTSNormalizer(on_ambiguous="error").normalize(source)
    assert raised.value.source_span == result.diagnostics[0].source_spans[0]


@pytest.mark.parametrize("unsafe", _UNSAFE_WHITESPACE, ids=_code_point_id)
@pytest.mark.parametrize(
    "template",
    ["https://example.com/a{}나", "C:\\work\\a{}나", "/tmp/a{}나", "`가{}나`"],
    ids=["url", "windows-path", "posix-path", "inline-code"],
)
def test_protected_ranges_do_not_hide_unsafe_whitespace(
    unsafe: str, template: str,
) -> None:
    source = template.format(unsafe)
    result = KoreanTTSNormalizer().convert(source)
    offset = source.index(unsafe)

    assert result.normalized_text == source
    assert not result.complete
    diagnostics = [
        item for item in result.diagnostics if item.code == "unsupported_character"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0].source_spans == (
        SourceSpan(offset, offset + 1, unsafe, len(source)),
    )
    with pytest.raises(ConversionPolicyError) as raised:
        KoreanTTSNormalizer(on_ambiguous="error").normalize(source)
    assert raised.value.code == "unsupported_character"
    assert raised.value.source_span == diagnostics[0].source_spans[0]
