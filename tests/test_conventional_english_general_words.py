"""사람이 검수한 공통 영문 읽기의 경계와 TTS 계약을 검사한다."""

from __future__ import annotations

import re

import pytest

from g2p_ko import ConversionPolicyError, G2P
from g2p_ko.english.classify import spell_ascii_letters
from g2p_ko.normalizer import KoreanTTSNormalizer


# 실제 코퍼스 문장을 복사하지 않고 검수된 단어만 합성 입력에 쓴다.
GENERAL_WORDS = (
    ("game", "게임"),
    ("okay", "오케이"),
    ("brand", "브랜드"),
    ("drama", "드라마"),
    ("cafe", "카페"),
    ("style", "스타일"),
    ("coffee", "커피"),
    ("menu", "메뉴"),
    ("hotel", "호텔"),
    ("test", "테스트"),
)


@pytest.fixture(scope="module")
def tts() -> KoreanTTSNormalizer:
    return KoreanTTSNormalizer(output_policy="tts")


@pytest.mark.parametrize(("word", "reading"), GENERAL_WORDS)
@pytest.mark.parametrize("case", [str.lower, str.title, str.upper])
def test_common_english_word_survives_tts_case_and_korean_suffix(
    tts: KoreanTTSNormalizer, word: str, reading: str, case,
) -> None:
    source = f"{case(word)}에서!"
    result = tts.convert_tts(source)

    assert result.complete
    assert result.normalized_text == reading + "에서!"
    assert re.fullmatch(r"[가-힣 ,.!?]*", result.normalized_text)
    assert tts(result.normalized_text) == result.normalized_text
    assert any(rewrite.before == case(word) for rewrite in result.rewrites)
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == source[span.start:span.end]


@pytest.mark.parametrize(("word", "reading"), GENERAL_WORDS)
def test_common_word_and_number_keep_projected_original_spans(
    tts: KoreanTTSNormalizer, word: str, reading: str,
) -> None:
    source = f"**{word.title()}**에서, <b>2</b>시에! 국물."
    result = tts.convert_tts(source)

    assert result.complete
    assert result.normalized_text == f"{reading}에서, 두 시에! 국물."
    assert tts(result.normalized_text) == result.normalized_text
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == source[span.start:span.end]


@pytest.mark.parametrize("source", ["gamely", "coffees", "menubar", "hotelier", "testimony"])
def test_common_word_is_not_matched_inside_a_longer_latin_word(
    tts: KoreanTTSNormalizer, source: str,
) -> None:
    assert tts(source) == spell_ascii_letters(source)


@pytest.mark.parametrize("source", ["GAME_test", "foo.MENU.bar", "fooCOFFEEbar", "HOTELier"])
def test_legacy_preserve_keeps_identifiers_containing_common_words(source: str) -> None:
    assert KoreanTTSNormalizer()(source) == source


@pytest.mark.parametrize(("word", "reading"), GENERAL_WORDS)
def test_legacy_preserve_does_not_enable_lowercase_latin_fallback(word: str, reading: str) -> None:
    normalizer = KoreanTTSNormalizer()

    assert normalizer(word) == word
    assert normalizer(word.upper()) == reading


def test_existing_trusted_readings_and_ambiguous_case_words_are_preserved(tts: KoreanTTSNormalizer) -> None:
    assert tts("TV AI NASA IT") == "티비 에이아이 나사 아이티"
    for source in ("US", "us", "HOT", "hot", "REAL", "real"):
        assert tts(source) == spell_ascii_letters(source)


def test_explicit_lexicon_still_precedes_the_common_word() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"coffee": "음료"})
    source = "**coffee**에서 3개"
    result = normalizer.convert_tts(source)

    assert result.complete
    assert result.normalized_text == "음료에서 세 개"
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == source[span.start:span.end]


def test_common_word_inside_url_or_email_is_spelled_structurally(tts: KoreanTTSNormalizer) -> None:
    url = "https://coffee.example/GAME01"
    email = "menu+01@example.com"
    for source, rule in ((url, "normalizer.tts.url.v1"), (email, "normalizer.tts.email.v1")):
        result = tts.convert_tts(source)

        assert result.complete
        assert "커피" not in result.normalized_text
        assert "게임" not in result.normalized_text
        assert "메뉴" not in result.normalized_text
        assert "공 일" in result.normalized_text
        assert any(rewrite.rule_id == rule and rewrite.before == source for rewrite in result.rewrites)
        assert re.fullmatch(r"[가-힣 ,.!?]*", result.normalized_text)


@pytest.mark.parametrize(
    "source,expected,complete",
    [
        ("foo.TEAM.bar", "에프오오.티이에이엠.비에이알", True),
        ("BLOG.example", "비엘오지.이엑스에이엠피엘이", True),
        ("NASA.AI", "엔에이에스에이.에이아이", True),
        ("foo_TEAM_bar", "에프오오_티이에이엠_비에이알", False),
        ("TEAM‑25", "티이에이엠‑이십오", False),
        ("TEAM/25", "티이에이엠/이십오", False),
        ("TEAM:25", "티이에이엠,이십오", True),
        ("TEAM/MENU", "티이에이엠/엠이엔유", False),
        ("TEAM+MENU", "티이에이엠+엠이엔유", False),
        ("TEAM-MENU", "티이에이엠 하이픈 엠이엔유", True),
    ],
)
def test_joined_tokens_never_apply_partial_conventional_readings(
    tts: KoreanTTSNormalizer, source: str, expected: str, complete: bool,
) -> None:
    result = tts.convert_tts(source)

    assert result.normalized_text == expected
    assert result.complete is complete
    assert not any(rewrite.rule_id in {
        "normalizer.tts.english_conventional.v1", "normalizer.english_acronym_exception.v1",
    } for rewrite in result.rewrites)
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]
    if not complete:
        assert result.diagnostics
        with pytest.raises(ConversionPolicyError):
            tts(source)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("TEAM. MENU! NASA에서?", "팀. 메뉴! 나사에서?"),
        ("TEAM: 안내", "팀, 안내"),
        ("TEAM과 NASA에서 25GB와 12 Hz를 비교했다.", "팀과 나사에서 이십오 기가바이트와 십이 헤르츠를 비교했다."),
        ("25km/h와 12MB/s를 측정했다.", "시속 이십오 킬로미터와 십이 메가바이트 퍼 세컨드를 측정했다."),
    ],
)
def test_safe_word_boundaries_preserve_separate_words_and_supported_units(
    tts: KoreanTTSNormalizer, source: str, expected: str,
) -> None:
    result = tts.convert_tts(source)

    assert result.complete
    assert result.normalized_text == expected == tts(source)
    assert tts(expected) == expected


def test_common_word_normalization_keeps_orthography_before_optional_g2p(tts: KoreanTTSNormalizer) -> None:
    result = tts.convert_tts("Coffee와 국물 닫는 닫고.")

    assert result.complete
    assert result.normalized_text == "커피와 국물 닫는 닫고."
    pronunciation = G2P().convert(result.normalized_text, normalize=False)
    assert pronunciation.complete
    assert pronunciation.normalized_text == result.normalized_text
    assert "궁물" in pronunciation.surface_pronunciation
    assert re.fullmatch(r"[가-힣 ,.!?]*", pronunciation.surface_pronunciation)
