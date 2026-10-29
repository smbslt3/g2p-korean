"""관용 영문 읽기와 철자 읽기의 경계 및 음운 변환을 검증한다."""

import unicodedata

import pytest

from g2p_ko import G2P
from g2p_ko.english.classify import ascii_letter_form, spell_ascii_letters
from g2p_ko.pipeline import Pipeline


@pytest.fixture(scope="module")
def g2p() -> G2P:
    return G2P()


@pytest.mark.parametrize(
    ("source", "reading"),
    [
        ("NASA", "나사"), ("nasa", "나사"), ("NaSa", "나사"),
        ("NATO", "나토"), ("UNESCO", "유네스코"), ("FIFA", "피파"),
        ("laser", "레이저"), ("coffee", "커피"), ("game", "게임"),
        ("TV", "티비"), ("Ａｌｂｕｍ", "앨범"), ("𝐍𝐀𝐒𝐀", "나사"),
        ("coﬀee", "커피"), ("NASA와", "나사와"), ("RAM이", "램이"),
        ("TEAM이", "팀이"), ("ALBUM에서", "앨범에서"),
        ("TEAM 이름", "팀 이름"), ("GAME 이름", "게임 이름"),
        ("RAM 용량", "램 용량"), ("HOTEL 여름", "호텔 여름"),
        ("NASA. coffee!", "나사. 커피!"), ("'NASA'", "'나사'"),
    ],
)
def test_conventional_readings_and_phonology(g2p: G2P, source: str, reading: str) -> None:
    for normalize in (True, False):
        result = g2p.convert(source, normalize=normalize)
        assert result.normalized_text == reading
        assert result.surface_pronunciation == g2p(reading) == g2p(source, normalize=normalize)
        assert result.complete
        assert not result.diagnostics.pronunciation.diagnostics
        assert len(result.normalized_text) == len(result.surface_pronunciation)


@pytest.mark.parametrize(
    "source",
    [
        "hello", "Qzxv", "gamely", "coffees", "menubar", "hotelier", "testimony",
        "US", "us", "HOT", "REAL", "AI", "API", "URL", "NASA_test",
        "foo.NASA.bar", "BLOG.example", "NASA.AI", "TEAM/MENU", "TEAM+MENU",
        "TEAM-MENU", "TEAM / MENU", "NASA's", "https://coffee.example/GAME",
        "menu@example.com", "ｃｏｆｆｅｅ＠ｅｘａｍｐｌｅ．ｃｏｍ",
        r"C:\NASA\coffee.txt", "./NASA/coffee.txt", "`NASA coffee`",
        "foo．ＮＡＳＡ．bar", "NASA＿test", "NASÁ",
    ],
)
def test_structures_and_unknown_words_keep_spelling(g2p: G2P, source: str) -> None:
    source = unicodedata.normalize("NFC", source)
    expected = "".join(
        spell_ascii_letters(letters) if (letters := ascii_letter_form(char)) else char
        for char in source
    )
    result = g2p.convert(source)
    assert result.normalized_text == expected
    assert result.surface_pronunciation == g2p(source)


def test_conventional_trace_uses_original_coordinates() -> None:
    source = "각 ＮＡＳＡ와 coﬀee, TEAM이 좋아요."
    result = Pipeline(max_length=10_000).run(source)
    rewrites = [item for item in result.rewrites if item.rule_id == "english.conventional.v1"]
    assert [(item.before, item.after) for item in rewrites] == [
        ("ＮＡＳＡ", "나사"), ("coﬀee", "커피"), ("TEAM", "팀"),
    ]
    for item in (*result.rewrites, *result.diagnostics):
        for span in item.source_spans:
            assert span.surface == source[span.start:span.end]


def test_url_spelling_does_not_consume_numbers_or_separators(g2p: G2P) -> None:
    result = g2p.convert("https://coffee.com/TV?x=1")
    assert result.normalized_text == "에이치티티피에스://씨오에프에프이이.씨오엠/티브이?엑스=1"
    assert not result.complete
    assert [item.code for item in result.diagnostics.pronunciation.diagnostics] == [
        "unconverted_numeric",
    ]


def test_letter_names_do_not_trigger_word_n_insertion(g2p: G2P) -> None:
    assert g2p("M I") == "엠 아이"
    assert g2p("TEAM 이름") == "팀 니름"


def test_word_reading_respects_original_input_budget() -> None:
    assert G2P(max_length=4).convert("NASA").normalized_text == "나사"
