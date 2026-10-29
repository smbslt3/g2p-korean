"""10회 적대적 공격에서 확정한 G2P 회귀 사례를 검증한다."""

import json
from pathlib import Path
import unicodedata

import pytest

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.errors import InputValidationError
from g2p_ko.model import AnalysisToken
from g2p_ko.english.structures import scan_english_structures
from g2p_ko.pipeline import Pipeline


@pytest.mark.parametrize("source,expected", json.loads(
    (Path(__file__).parent / "fixtures/adversarial_r03.json").read_text(encoding="utf-8")
))
def test_r03_code_and_quote_boundaries(source: str, expected: str) -> None:
    result = G2P().convert(source)
    assert result.normalized_text == expected
    assert result.surface_pronunciation == G2P()(source)


@pytest.mark.parametrize("source,expected", [
    ("싫증", "실쯩"), ("싫증이", "실쯩이"), ("싫증을", "실쯩을"),
    ("싫증의", "실쯩에"), ("싫증난다", "실쯩난다"),
    ("싫다", "실타"), ("싫지만", "실치만"),
])
def test_r04_lexical_hieuh_exception_and_regular_controls(source: str, expected: str) -> None:
    assert G2P()(source) == expected


@pytest.mark.parametrize("source,expected", [
    ("%Google%", "%지오오지엘이%"), ("${NASA}", "${엔에이에스에이}"),
    ("${coffee}", "${씨오에프에프이이}"),
    ("Google$Column", "지오오지엘이$씨오엘유엠엔"),
    ("Google＄Column", "지오오지엘이＄씨오엘유엠엔"),
    ("{NASA}", "{나사}"), ("!Google!", "!구글!"),
])
def test_r05_explicit_variable_and_member_names(source: str, expected: str) -> None:
    assert G2P().convert(source + " NASA").normalized_text == expected + " 나사"


@pytest.mark.parametrize("numeric", ["¼", "½", "¾", "⅓", "⅒", "⒈", "⑴", "㊿"])
@pytest.mark.parametrize("prefix", [True, False])
def test_r05_expanded_numeric_neighbors_block_word_reading(numeric: str, prefix: bool) -> None:
    source = numeric + "NASA" if prefix else "NASA" + numeric
    expected = numeric + "엔에이에스에이" if prefix else "엔에이에스에이" + numeric
    result = G2P().convert(source)
    assert result.normalized_text == expected
    assert not result.complete
    assert any(item.code == "unconverted_numeric" for item in result.diagnostics.pronunciation.diagnostics)


@pytest.mark.parametrize("local", ["NASA", "NASA/coffee", "NASA`coffee", "NASA!coffee", "NASA%coffee"])
def test_r07_full_email_atom_still_matches(local: str) -> None:
    source = local + "@example.com"
    ranges = scan_english_structures(source)
    assert len(ranges) == 1
    assert (ranges[0].start, ranges[0].end) == (0, len(source))
    result = Pipeline(max_length=10000).run(source)
    assert not any(item.rule_id == "english.conventional.v1" for item in result.rewrites)


@pytest.mark.parametrize("source", ["\u0344", "\u0958", "\u0f73", "\u0f75", "\u0f81"])
def test_r08_raw_input_limit_allows_nfc_expansion(source: str) -> None:
    g2p = G2P(max_length=1)
    result = g2p.convert(source)
    assert result.normalized_text == unicodedata.normalize("NFC", source)
    assert g2p(source) == result.surface_pronunciation
    assert result.diagnostics.pronunciation.source == unicodedata.normalize("NFC", source)
    for operation in (g2p, g2p.convert):
        with pytest.raises(InputValidationError):
            operation(source + "A")


@pytest.mark.parametrize("tokens", [(), (AnalysisToken("굳", "VV", 0, 1),)])
def test_r08_incomplete_analyzer_response_is_diagnosed(monkeypatch: pytest.MonkeyPatch, tokens: tuple) -> None:
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: tokens)
    result = G2P().convert("굳이")
    assert not result.complete
    assert {item.code for item in result.diagnostics.pronunciation.diagnostics} >= {"analyzer_failed", "morphology_rule_skipped"}
    assert G2P()("굳이") == result.surface_pronunciation


@pytest.mark.parametrize("tag", [1, ["NNG"], {"tag": "NNG"}, ("NNG",), True, b"NNG"])
def test_r09_invalid_tag_type_is_diagnosed(monkeypatch: pytest.MonkeyPatch, tag: object) -> None:
    tokens = (AnalysisToken("나", "NNG", 0, 1), AnalysisToken("의", tag, 1, 2))
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: tokens)
    result = G2P().convert("나의")
    assert not result.complete
    assert any(item.code == "analyzer_failed" for item in result.diagnostics.pronunciation.diagnostics)
    assert G2P()("나의") == result.surface_pronunciation


@pytest.mark.parametrize("source", [
    "(https://NASA.example/coffee)NASA", "[https://NASA.example/coffee]NASA",
    "[coffee](https://NASA.example/coffee)NASA",
    "(https://NASA.example/(coffee))NASA", "([http://[::1]?q=(coffee)])NASA",
    "(NASA.example/(coffee))NASA", "(localhost/?q=coffee)NASA",
])
def test_r09_parenthetical_address_stops_before_prose(source: str) -> None:
    result = G2P().convert(source)
    assert result.normalized_text.endswith("나사")
    assert "씨오에프에프이이" in result.normalized_text


@pytest.mark.parametrize("source,expected", [
    (r"\``NASA` TEAM", r"\``엔에이에스에이` 팀"),
    (r"\```NASA`` TEAM", r"\```엔에이에스에이`` 팀"),
    ("> `NASA\n>\n> TEAM`", "> `나사\n>\n> 팀`"),
    ("> `NASA\r\n>\r\n> TEAM`", "> `나사\r\n>\r\n> 팀`"),
])
def test_r09_escaped_runs_and_quoted_paragraphs(source: str, expected: str) -> None:
    assert G2P().convert(source).normalized_text == expected


@pytest.mark.parametrize("source", [
    '{"NASA TEAM"@coffee.example}coffee', '\'"NASA TEAM"@coffee.example\' coffee',
    '("C:\\NASA) TEAM")coffee', '("/NASA) TEAM")coffee',
])
def test_r09_quoted_structure_delimiters_preserve_inner_words(source: str) -> None:
    result = G2P().convert(source)
    assert "엔에이에스에이" in result.normalized_text
    assert "티이에이엠" in result.normalized_text
    assert result.normalized_text.endswith("커피")


@pytest.mark.parametrize("prefix,continuation", [("- > ", "  > "), ("> - > ", ">   > ")])
@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_r09_mixed_list_quote_fences(prefix: str, continuation: str, fence: str) -> None:
    source = f"{prefix}{fence}\n{continuation}NASA\n{continuation}{fence}\n\nTEAM"
    expected = source.replace("NASA", "엔에이에스에이").replace("TEAM", "팀")
    assert G2P().convert(source).normalized_text == expected


@pytest.mark.parametrize("source,expected", [
    (r"TEAM \`NASA` FIFA", r"팀 \`나사` 피파"),
    (r"TEAM \``NASA` FIFA", r"팀 \``엔에이에스에이` 피파"),
    (r"TEAM \\`NASA` FIFA", r"팀 \\`엔에이에스에이` 피파"),
    (r"TEAM \ NASA", r"티이에이엠 \ 엔에이에스에이"),
])
def test_r10_backtick_escape_is_not_a_spaced_operator(source: str, expected: str) -> None:
    assert G2P().convert(source).normalized_text == expected


@pytest.mark.parametrize("source", [
    "(`[` https://game.example/coffee)menu",
    "[`(` https://game.example/coffee]menu",
    "(\n```\n[\n```\nhttps://game.example/coffee)menu",
])
def test_r10_code_brackets_do_not_poison_url_enclosures(source: str) -> None:
    result = G2P().convert(source)
    assert result.normalized_text.endswith("메뉴")
    assert "씨오에프에프이이" in result.normalized_text


@pytest.mark.parametrize("separator", ["‥", "…", "︰", "⩴", "⩵", "⩶", "․․", "﹒﹒"])
def test_r01_nfkc_expanded_joiners_keep_identifier_spelling(separator: str) -> None:
    result = G2P().convert(f"NASA{separator}TEAM")
    assert result.normalized_text == f"엔에이에스에이{separator}티이에이엠"


@pytest.mark.parametrize("source,expected", [
    ("NASA…", "나사…"), ("NASA… 안내", "나사… 안내"),
    ("NASA. TEAM", "나사. 팀"),
])
def test_r01_prose_punctuation_keeps_independent_reading(source: str, expected: str) -> None:
    assert G2P().convert(source).normalized_text == expected


@pytest.mark.parametrize("source", [
    '"NASA"@example.com', '"NASA coffee"@example.com',
    '"NASA\\" coffee"@example.com', '"NASA"@[127.0.0.1]',
    '"NASA"@[IPv6:::1]', '"NASA"@한국.한국',
    'http://[::1]?q=(NASA)', '[::1]?q=(NASA)',
    '127.0.0.1?q=(NASA)', 'localhost?q=(NASA)',
    'NASA。com?coffee', 'NASA｡com?coffee',
    '"C:\\NASA TEAM"', '"..\\NASA\\TEAM FIFA"',
    '"/NASA/TEAM FIFA"', '"../NASA/TEAM FIFA"',
    '"\\\\NASA\\TEAM\\FIFA coffee"',
])
def test_r02_quoted_email_and_address_queries_spell_names(source: str) -> None:
    result = Pipeline(max_length=10000).run(source)
    assert not any(item.rule_id == "english.conventional.v1" for item in result.rewrites)
    assert "엔에이에스에이" in result.normalized_text
    assert G2P().convert(source + " NASA").normalized_text.endswith(" 나사")
