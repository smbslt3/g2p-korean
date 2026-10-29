"""주소·코드·혼합 식별자를 일반 단어로 오인한 사례를 재현한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.english.structures import scan_english_structures
from g2p_ko.pipeline import Pipeline


@pytest.mark.parametrize("source", [
    "```python\nNASA = TEAM\n```", "~~~python\nNASA = TEAM\n~~~",
    "   ````text\r\nNASA\r\n```\r\nTEAM\r\n`````",
    "```python\nNASA\n", "~~~\nNASA\n```\nTEAM",
    "> ```\n> NASA = TEAM\n> ```", "- ```\n  NASA = TEAM\n  ```",
    "> - ~~~\n>   NASA = TEAM\n>   ~~~", "1. ```\n   NASA = TEAM\n   ```",
    "www.example.com?q=NASA", "example.com?q=NASA&word=TEAM",
    "example.com#NASA", "coffee.한국?q=NASA", "user@coffee.한국",
    "foo@FIFA.세계", "ｃｏｆｆｅｅ．ｃｏｍ？ｑ＝ＮＡＳＡ",
    "ｗｗｗ．ｅｘａｍｐｌｅ．ｃｏｍ？ｑ＝ＴＥＡＭ",
    "custom+app://host?q=NASA", "https://example.com?q=NASA\u200dTEAM",
    "#NASA", "@NASA", "$NASA", ".NASA", "＃ＮＡＳＡ", "NASA@",
    "NASA=TEAM", "NASA&TEAM", "NASA?TEAM", "NASA#TEAM",
    "NASA\u0305", "NASA\u200dTEAM", "NASAα", "NASAЖ", "NASA𝛼", "NASA中",
    "αNASA", "ЖNASA", "𝛼NASA", "中NASA",
])
def test_structural_names_never_use_conventional_readings(source: str) -> None:
    result = Pipeline(max_length=10_000).run(source)
    assert not any(item.rule_id == "english.conventional.v1" for item in result.rewrites)
    assert result.surface_pronunciation == G2P()(source)
    for item in (*result.rewrites, *result.diagnostics):
        for span in item.source_spans:
            assert span.surface == source[span.start:span.end]


@pytest.mark.parametrize("source,expected", [
    ("NASA. TEAM!", "나사. 팀!"), ("NASA? TEAM", "나사? 팀"),
    ("(NASA) [TEAM]", "(나사) [팀]"), ("NASA와 TEAM이", "나사와 팀이"),
    ("```\nNASA\n```\nTEAM", "```\n엔에이에스에이\n```\n팀"),
    ("~~~\nNASA\n~~~\nTEAM", "~~~\n엔에이에스에이\n~~~\n팀"),
    ("> ```\n> NASA\n> ```\nTEAM", "> ```\n> 엔에이에스에이\n> ```\n팀"),
    ("> ```\n> NASA\nTEAM", "> ```\n> 엔에이에스에이\n팀"),
    ("- ```\n  NASA\n  ```\nTEAM", "- ```\n  엔에이에스에이\n  ```\n팀"),
    ("- ```\n  NASA\nTEAM", "- ```\n  엔에이에스에이\n팀"),
    ("coﬀee.com?q=NASA TEAM", "씨오에프에프이이.씨오엠?큐=엔에이에스에이 팀"),
])
def test_structure_protection_stops_before_independent_prose(source: str, expected: str) -> None:
    assert G2P().convert(source).normalized_text == expected


def test_compatibility_structure_coordinates_cover_the_original_token() -> None:
    source = "앞 coﬀee.한국?q=ＮＡＳＡ 뒤"
    ranges = scan_english_structures(source)
    assert [(item.start, item.end, source[item.start:item.end]) for item in ranges] == [
        (2, len(source) - 2, "coﬀee.한국?q=ＮＡＳＡ"),
    ]


def test_structural_spelling_keeps_unresolved_characters_visible() -> None:
    result = G2P().convert("```\nNASA1\u200dTEAM\n```")
    assert not result.complete
    assert {item.code for item in result.diagnostics.pronunciation.diagnostics} == {
        "unconverted_numeric", "unsupported_character",
    }
