"""영문 알파벳 철자 읽기를 독립 oracle과 넓은 입력 행렬로 검증한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import random
import string
import unicodedata

import pytest

from g2p_ko import G2P, InputValidationError
from g2p_ko.english.conventional import CONVENTIONAL_READINGS
from g2p_ko.pipeline import Pipeline


# 구현의 글자표를 가져오지 않고 테스트 oracle을 명시한다.
_LETTER_NAMES = {
    "A": "에이",
    "B": "비",
    "C": "씨",
    "D": "디",
    "E": "이",
    "F": "에프",
    "G": "지",
    "H": "에이치",
    "I": "아이",
    "J": "제이",
    "K": "케이",
    "L": "엘",
    "M": "엠",
    "N": "엔",
    "O": "오",
    "P": "피",
    "Q": "큐",
    "R": "알",
    "S": "에스",
    "T": "티",
    "U": "유",
    "V": "브이",
    "W": "더블유",
    "X": "엑스",
    "Y": "와이",
    "Z": "지",
}
_ASCII_LETTERS = string.ascii_uppercase
_STRUCTURAL_SAMPLES = (
    "qzx! jwv? (xqv)",
    "don't, ray’s; qzx",
    "x_qv + z-j / w.v",
    "http://qzx.example/path?jwv=1",
    "https://example.com/a?NASA=1",
    "www.example.com?q=NASA",
    "user+tag@example.com",
    "ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ",
    r"C:\NASA\qzx.txt",
    r"\\server\NASA\qzx.txt",
    "./NASA/qzx.txt",
    "`NASA qzx + AI`",
    "```text\nNASA FIFA UNESCO\n```",
    "NASA\u0305",
    "NASA\u200dTEAM",
    "NASAα",
    "café",
    "qzx\tjwv\r\nxqv\u00a0z",
    "ＡｂＣ",
    "𝐀𝑏ℂ",
    "ﬃ",
)
_NUMERIC_FORMS = ("0", "7", "４", "²", "Ⅳ", "①", "٤")
_ASCII_PUNCTUATION = string.punctuation + " \t\r\n’"
_ALPHABET_SEQUENCES = (
    string.ascii_uppercase,
    string.ascii_lowercase,
    string.ascii_uppercase[::-1],
    string.ascii_lowercase[::-1],
    "QWERTYUIOPASDFGHJKLZXCVBNM",
    "qwertyuiopasdfghjklzxcvbnm",
)
_CONTEXT_COUNT_PER_NFKC_FORM = 5
_RANDOMIZED_CONCATENATION_COUNT = 1_024


def _randomized_words() -> tuple[str, ...]:
    generator = random.Random(20261023)
    return tuple(
        "_"
        + "".join(
            generator.choice(string.ascii_letters)
            for _ in range(generator.randint(1, 32))
        )
        + "_"
        for _ in range(256)
    )


def _randomized_concatenations() -> tuple[str, ...]:
    generator = random.Random(20261023)
    samples = []
    for _ in range(_RANDOMIZED_CONCATENATION_COUNT):
        terms = [
            "".join(
                generator.choice(string.ascii_letters)
                for _ in range(generator.randint(1, 20))
            )
            for _ in range(generator.randint(2, 5))
        ]
        separators = [
            generator.choice(_ASCII_PUNCTUATION) for _ in range(len(terms) - 1)
        ]
        source = "_" + terms[0] + "_"
        for separator, term in zip(separators, terms[1:], strict=True):
            source += separator + "_" + term + "_"
        samples.append(source)
    return tuple(samples)


def _independent_expected(source: str) -> str:
    """NFC 뒤 각 입력 문자의 NFKC 영문 결과를 독립 표로 읽는다."""

    normalized = unicodedata.normalize("NFC", source)
    result: list[str] = []
    for character in normalized:
        if character.isnumeric():
            result.append(character)
            continue
        compatible = unicodedata.normalize("NFKC", character)
        if compatible and compatible.isascii() and compatible.isalpha():
            result.extend(_LETTER_NAMES[item.upper()] for item in compatible)
        else:
            result.append(character)
    return "".join(result)


def _assert_matches_independent_oracle(
    g2p: G2P,
    source: str,
    *,
    expect_complete: bool | None = None,
) -> None:
    result = g2p.convert(source)
    assert result.normalized_text == _independent_expected(source)
    assert result.surface_pronunciation == g2p(source)
    assert len(result.normalized_text) == len(result.surface_pronunciation)
    if expect_complete is not None:
        assert result.complete is expect_complete


@lru_cache(maxsize=1)
def _nfkc_ascii_letter_forms() -> tuple[str, ...]:
    """현재 Python Unicode 데이터에서 NFKC가 ASCII 영문으로 접히는 문자를 모은다."""

    result = []
    for codepoint in range(0x110000):
        character = chr(codepoint)
        if character.isnumeric():
            continue
        compatible = unicodedata.normalize("NFKC", character)
        if compatible and compatible.isascii() and compatible.isalpha():
            result.append(character)
    return tuple(result)


@lru_cache(maxsize=1)
def _nfkc_unicode_letter_forms() -> tuple[str, ...]:
    """ASCII가 아닌 NFKC 호환 영문 코드 포인트를 반환한다."""

    return tuple(character for character in _nfkc_ascii_letter_forms() if not character.isascii())


def _assert_batch_matches_oracle(
    g2p: G2P,
    sources: list[str] | tuple[str, ...],
    *,
    expect_complete: bool = True,
) -> None:
    for source, result in zip(sources, g2p.convert_many(iter(sources)), strict=True):
        assert result.source == source
        assert result.normalized_text == _independent_expected(source)
        assert len(result.normalized_text) == len(result.surface_pronunciation)
        assert result.surface_pronunciation == g2p(source)
        assert result.complete is expect_complete


def _nfkc_context_samples() -> tuple[str, ...]:
    forms = _nfkc_unicode_letter_forms()
    samples = []
    for character in forms:
        samples.extend(
            (
                f"https://example.test/path/{character}?q=NASA",
                f"{character}@example.test",
                f"C:\\review\\{character}.txt",
                f"```text\n{character}\n```",
                f"국물 _{character}_ 와",
            )
        )
    return tuple(samples)


def _punctuation_cross_product() -> tuple[str, ...]:
    forms = (*string.ascii_letters, *_ALPHABET_SEQUENCES)
    return tuple(
        f"x{separator}{form}{separator}q"
        for form in forms
        for separator in _ASCII_PUNCTUATION
    )


def _fullwidth_ascii_letters(value: str) -> str:
    return "".join(chr(ord(character) + 0xFEE0) for character in value)


def _independent_josa(reading: str) -> tuple[str, str, str, str, str]:
    """끝 음절의 종성을 직접 계산해 다섯 조사 짝을 독립적으로 고른다."""

    if not reading or not "가" <= reading[-1] <= "힣":
        raise AssertionError(f"관용 읽기 끝이 한글 음절이 아닙니다: {reading!r}")
    jongseong = (ord(reading[-1]) - ord("가")) % 28
    has_batchim = jongseong != 0
    has_rieul = jongseong == 8
    return (
        "은" if has_batchim else "는",
        "이" if has_batchim else "가",
        "을" if has_batchim else "를",
        "과" if has_batchim else "와",
        "로" if not has_batchim or has_rieul else "으로",
    )


def _conventional_entry_josa_samples() -> tuple[list[str], list[str]]:
    sources: list[str] = []
    expected: list[str] = []
    for spelling, reading in CONVENTIONAL_READINGS.items():
        variants = (spelling, spelling.lower(), _fullwidth_ascii_letters(spelling))
        for variant in variants:
            for particle in _independent_josa(reading):
                sources.append(variant + particle)
                expected.append(reading + particle)
    return sources, expected


def _batched_source_groups() -> dict[str, list[str]]:
    conventional_sources, _ = _conventional_entry_josa_samples()
    return {
        "ascii_letter_punctuation": list(_punctuation_cross_product()),
        "unicode_nfkc_context": list(_nfkc_context_samples()),
        "randomized_concatenations": list(_randomized_concatenations()),
        "conventional_entry_josa": conventional_sources,
    }


def test_every_ascii_letter_uppercase_and_lowercase_matches_independent_oracle() -> None:
    g2p = G2P()
    for character in string.ascii_letters:
        result = g2p.convert(character)
        assert result.normalized_text == _LETTER_NAMES[character.upper()]
        assert result.complete
        assert not result.diagnostics.pronunciation.diagnostics
        assert result.surface_pronunciation == g2p(character)

    for alphabet in (_ASCII_LETTERS, _ASCII_LETTERS.lower()):
        _assert_matches_independent_oracle(g2p, alphabet, expect_complete=True)
        _assert_matches_independent_oracle(g2p, alphabet[::-1], expect_complete=True)


def test_all_ordered_ascii_letter_pairs_spell_in_identifier_context() -> None:
    g2p = G2P()
    pairs = [f"_{left}{right}_" for left in _ASCII_LETTERS for right in _ASCII_LETTERS]
    source = "|".join(pairs)
    _assert_matches_independent_oracle(g2p, source, expect_complete=True)


def test_deterministic_randomized_ascii_words_spell_without_lexical_lookup() -> None:
    words = _randomized_words()
    source = "|".join(words)
    assert len(source) < 10_000
    _assert_matches_independent_oracle(G2P(), source, expect_complete=True)


def test_every_unicode_character_with_nfkc_ascii_letters_spells_by_letter() -> None:
    forms = _nfkc_ascii_letter_forms()
    assert len(forms) >= 52
    assert set(string.ascii_letters).issubset(forms)

    # 밑줄로 각 후보를 감싸 관용 단어 표와 무관하게 글자 이름 규칙을 검증한다.
    source = "|".join(f"_{character}_" for character in forms)
    assert len(source) < 10_000
    _assert_matches_independent_oracle(G2P(), source, expect_complete=True)


def test_ascii_letter_and_alphabet_sequence_punctuation_cross_product() -> None:
    samples = _punctuation_cross_product()
    assert len(samples) == (52 + len(_ALPHABET_SEQUENCES)) * len(_ASCII_PUNCTUATION)
    _assert_batch_matches_oracle(G2P(), samples)


def test_every_nfkc_unicode_alternative_in_five_text_contexts() -> None:
    forms = _nfkc_unicode_letter_forms()
    samples = _nfkc_context_samples()
    assert len(samples) == len(forms) * _CONTEXT_COUNT_PER_NFKC_FORM
    _assert_batch_matches_oracle(G2P(), samples)


def test_seeded_random_ascii_concatenations_match_batch_and_scalar_paths() -> None:
    samples = _randomized_concatenations()
    assert len(samples) == _RANDOMIZED_CONCATENATION_COUNT
    _assert_batch_matches_oracle(G2P(), samples)


def test_every_conventional_entry_and_josa_variant_resolves_without_resolver_oracle() -> None:
    sources, expected = _conventional_entry_josa_samples()
    assert sources
    g2p = G2P()
    for source, expected_normalized, result in zip(
        sources,
        expected,
        g2p.convert_many(iter(sources)),
        strict=True,
    ):
        assert result.normalized_text == expected_normalized
        assert result.surface_pronunciation == g2p(expected_normalized)
        assert result.complete
        assert not result.diagnostics.pronunciation.diagnostics


def test_ten_thousand_character_input_boundary_and_long_expansion() -> None:
    source = "Q" * 10_000
    result = G2P(max_length=10_000).convert(source)
    expected = _independent_expected(source)
    assert result.normalized_text == expected
    assert result.surface_pronunciation == G2P()(source)
    assert result.complete
    with pytest.raises(InputValidationError, match="최대 길이 10000"):
        G2P(max_length=10_000).convert(source + "Q")


def test_repeated_calls_and_shared_instance_thread_pool_are_stable() -> None:
    g2p = G2P()
    sources = [
        "_qzx_",
        "국물 _jwv_ 와",
        "https://example.test/_NASA_?k=qzx",
        r"C:\review\_xqv_.txt",
        "```text\nNASA\n```",
        "NASAα",
    ] * 12
    expected_surface = []
    for _ in range(3):
        current = []
        for source in sources:
            result = g2p.convert(source)
            assert result.normalized_text == _independent_expected(source)
            current.append(result.surface_pronunciation)
            assert g2p(source) == result.surface_pronunciation
        expected_surface.append(current)
    assert expected_surface[0] == expected_surface[1] == expected_surface[2]

    with ThreadPoolExecutor(max_workers=4) as executor:
        concurrent = list(executor.map(g2p, sources))
    assert concurrent == expected_surface[0]


@pytest.mark.parametrize(
    "source",
    _STRUCTURAL_SAMPLES,
)
def test_structural_unicode_and_mixed_script_inputs_keep_each_english_letter(
    source: str,
) -> None:
    _assert_matches_independent_oracle(G2P(), source)


@pytest.mark.parametrize("digit", _NUMERIC_FORMS)
def test_remaining_numeric_forms_stay_unconverted_and_point_to_source(digit: str) -> None:
    source = f"qzx{digit}jwv"
    result = G2P().convert(source)
    assert result.normalized_text == _independent_expected(source)
    assert not result.complete

    report = result.diagnostics.pronunciation
    assert report.source == unicodedata.normalize("NFC", source)
    numeric = [item for item in report.diagnostics if item.code == "unconverted_numeric"]
    assert numeric
    for diagnostic in numeric:
        assert diagnostic.source_spans
        for span in diagnostic.source_spans:
            assert span.surface == report.source[span.start : span.end]


def test_nonbreaking_space_is_preserved_and_reported_while_letters_are_read() -> None:
    source = "qzx\u00a0jwv"
    result = G2P().convert(source)
    assert result.normalized_text == _independent_expected(source)
    assert not result.complete
    diagnostics = result.diagnostics.pronunciation.diagnostics
    assert {item.code for item in diagnostics} == {"unsupported_symbol"}
    assert {item.rule_id for item in diagnostics} == {"output.validate"}
    assert any(
        span.surface == "\u00a0"
        for diagnostic in diagnostics
        for span in diagnostic.source_spans
    )


def test_mixed_nfc_nfd_trace_no_trace_and_batch_paths_agree() -> None:
    g2p = G2P()
    nfc = "국물 qzx3와 fjv"
    nfd = unicodedata.normalize("NFD", nfc)
    expected = _independent_expected(nfc)

    normalized_result = g2p.convert(nfc)
    decomposed_result = g2p.convert(nfd)
    assert normalized_result.normalized_text == expected
    assert decomposed_result.normalized_text == expected
    assert decomposed_result.surface_pronunciation == normalized_result.surface_pronunciation
    assert decomposed_result.diagnostics.normalization.source == nfd
    assert decomposed_result.diagnostics.pronunciation.source == nfc

    for normalize in (True, False):
        assert g2p(nfc, normalize=normalize) == normalized_result.surface_pronunciation
        assert g2p(nfd, normalize=normalize) == decomposed_result.surface_pronunciation
        detailed = g2p.convert(nfd, normalize=normalize)
        assert detailed.normalized_text == expected
        assert detailed.surface_pronunciation == g2p(nfd, normalize=normalize)

    for diagnostic in decomposed_result.diagnostics.pronunciation.diagnostics:
        for span in diagnostic.source_spans:
            assert span.surface == nfc[span.start : span.end]

    sources = [nfc, nfd, "https://qzx.example/x", "NASAα", "user+tag@example.com"]
    pronounced = list(g2p.pronounce_many(iter(sources)))
    detailed = list(g2p.convert_many(iter(sources)))
    assert pronounced == [g2p(source) for source in sources]
    assert [item.surface_pronunciation for item in detailed] == pronounced
    assert [item.normalized_text for item in detailed] == [
        g2p.convert(source).normalized_text for source in sources
    ]


def test_lexical_rewrite_spans_point_back_to_original_unicode_input() -> None:
    source = unicodedata.normalize("NFD", "각") + " QZX 𝐖 ﬃ"
    result = Pipeline(max_length=10_000).run(source)
    assert result.normalized_text == _independent_expected(source)
    assert result.surface_pronunciation == G2P()(source)
    assert result.complete
    assert result.rewrites
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.source_length == len(source)
            assert span.surface == source[span.start : span.end]


def test_expansion_budget_uses_raw_input_length_and_rejects_over_limit() -> None:
    g2p = G2P(max_length=1)
    result = g2p.convert("ﬃ")
    assert result.normalized_text == "에프에프아이"
    assert result.complete
    with pytest.raises(InputValidationError, match="최대 길이 1"):
        g2p.convert("ﬃﬃ")


def matrix_sample_counts() -> dict[str, int]:
    """재현 보고서에 항목 종류별 결정적 표본 수를 반환한다."""

    batch_groups = _batched_source_groups()
    batch_item_conversions = sum(len(sources) for sources in batch_groups.values())
    unique_batch_sources = len(
        {source for sources in batch_groups.values() for source in sources}
    )
    return {
        "unicode_codepoints_scanned_by_python_unicode_database": 0x110000,
        "direct_ascii_single_letter_api_calls": 52,
        "direct_full_alphabet_sequence_api_calls": 4,
        "ascii_ordered_pair_tokens_in_one_corpus": 26 * 26,
        "ascii_ordered_pair_corpus_api_calls": 1,
        "ascii_letter_punctuation_cross_product_source_calls": len(
            _punctuation_cross_product()
        ),
        "random_identifier_tokens_in_one_corpus": len(_randomized_words()),
        "random_identifier_corpus_api_calls": 1,
        "seeded_randomized_concatenation_source_calls": len(
            _randomized_concatenations()
        ),
        "unicode_nfkc_ascii_letter_codepoints_in_one_corpus": len(
            _nfkc_ascii_letter_forms()
        ),
        "unicode_nfkc_character_corpus_api_calls": 1,
        "unicode_nfkc_context_source_calls": len(_nfkc_context_samples()),
        "conventional_table_entries": len(CONVENTIONAL_READINGS),
        "conventional_entry_case_and_josa_source_calls": 3 * 5 * len(
            CONVENTIONAL_READINGS
        ),
        "structural_and_mixed_script_source_cases": len(_STRUCTURAL_SAMPLES),
        "numeric_passthrough_source_cases": len(_NUMERIC_FORMS),
        "nfc_nfd_scalar_batch_source_group_size": 5,
        "input_limit_boundary_cases": 2,
        "long_boundary_input_codepoints": 10_000,
        "repeat_calls_per_pass": 6 * 12,
        "repeat_call_pass_count": 3,
        "thread_pool_shared_instance_source_calls": 6 * 12,
        "batched_end_to_end_item_conversions": batch_item_conversions,
        "unique_sources_across_bulk_batches": unique_batch_sources,
    }
