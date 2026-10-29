"""추가 10회 적대적 공격에서 확정한 회귀 사례를 검증한다."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from g2p_ko import G2P
from g2p_ko.english.structures import scan_english_structures
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.model import AnalysisToken
from g2p_ko.pipeline import Pipeline
import g2p_ko.analyzer as analyzer_module


@pytest.mark.parametrize("host", ["[fe80::1%eth0]", "[fe80::1%25en0]", "[fe80::1%en-0]", "[::1]"])
@pytest.mark.parametrize("scheme", ["", "http://"])
@pytest.mark.parametrize("suffix", ["?q=(NASA)", "/(NASA)", "#(NASA)"])
def test_r11_scoped_ipv6_keeps_query_in_address(host: str, scheme: str, suffix: str) -> None:
    address = scheme + host + suffix
    source = address + " NASA"
    ranges = scan_english_structures(source)
    assert any(item.start == 0 and item.end == len(address) for item in ranges)
    result = G2P().convert(source)
    assert result.normalized_text.endswith(suffix.replace("q", "큐").replace("NASA", "엔에이에스에이") + " 나사")
    assert not result.complete


@pytest.mark.parametrize("space", ["\u2000", "\u2001", "\u2002", "\u2003"])
def test_r11_public_diagnostic_spans_use_report_source(space: str) -> None:
    result = G2P().convert("NASA" + space + "FIFA")
    report = result.diagnostics.pronunciation
    for diagnostic in report.diagnostics:
        for span in diagnostic.source_spans:
            assert report.source[span.start:span.end] == span.surface


@pytest.mark.parametrize("source,expected", [
    case for case in json.loads(
        (Path(__file__).parent / "fixtures/adversarial_r12.json").read_text(encoding="utf-8")
    )
    # 고립형의 명사 뜻은 아래 통제 분석 검사에서 검증한다. 원본 정답은 보존한다.
    if case[0] != "밭이랑"
])
def test_r12_verified_lexical_pronunciations(source: str, expected: str) -> None:
    result = G2P().convert(source)
    assert result.normalized_text == source
    assert result.surface_pronunciation == expected
    assert G2P()(source) == expected
    assert result.complete


@pytest.mark.parametrize("noun", [True, False])
def test_r12_furrow_noun_and_conjunctive_particle_are_distinct(monkeypatch, noun: bool) -> None:
    tokens = (AnalysisToken("밭이랑", "NNG", 0, 3),) if noun else (
        AnalysisToken("밭", "NNG", 0, 1), AnalysisToken("이랑", "JC", 1, 3),
    )
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: tokens)
    expected = "반니랑" if noun else "바치랑"
    result = G2P().convert("밭이랑")
    assert result.normalized_text == "밭이랑"
    assert result.surface_pronunciation == expected
    assert G2P()("밭이랑") == expected
    assert result.complete


@pytest.mark.parametrize("tag", ["NNG+JC", "NNG+JX", "JC+NNG", "NNP+VCP"])
def test_r13_mixed_noun_particle_annotation_does_not_force_noun_reading(monkeypatch, tag: str) -> None:
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: (
        AnalysisToken("밭이랑", tag, 0, 3),
    ))
    result = Pipeline(max_length=10000).run("밭이랑")
    assert not any(item.rule_id == "ko.official.morpheme" for item in result.rewrites)


@pytest.mark.parametrize("codepoint", [0x3130, 0x318F, 0xD7C7, 0xD7C8, 0xD7C9, 0xD7CA])
@pytest.mark.parametrize("wrapped", [False, True])
def test_r14_unassigned_hangul_block_holes_are_diagnosed(codepoint: int, wrapped: bool) -> None:
    character = chr(codepoint)
    source = "NASA" + character + "가" if wrapped else character
    result = G2P().convert(source)
    assert character in result.normalized_text
    assert character in result.surface_pronunciation
    assert not result.complete
    report = result.diagnostics.pronunciation
    assert any(item.code == "unsupported_character" and any(
        span.surface == character and report.source[span.start:span.end] == character
        for span in item.source_spans
    ) for item in report.diagnostics)


@pytest.mark.parametrize("field,value", [
    ("start", False), ("start", 0.2), ("start", "0"),
    ("len", 3.2), ("len", "3"), ("len", True),
    ("tag", None), ("tag", 1), ("tag", b"NNG"), ("tag", []),
])
def test_r15_raw_backend_does_not_coerce_invalid_types(monkeypatch, field, value) -> None:
    fields = {"start": 0, "len": 3, "tag": "NNG"}
    fields[field] = value
    backend = SimpleNamespace(tokenize=lambda text, **kwargs: [SimpleNamespace(**fields)])
    monkeypatch.setattr(analyzer_module, "_runtime_kiwi", backend)
    result = G2P().convert("밭이랑")
    assert not result.complete
    assert any(item.code == "analyzer_failed" for item in result.diagnostics.pronunciation.diagnostics)


def test_r15_boolean_analysis_coordinate_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(KiwiAnalyzer, "analyze_components", lambda self, text: (
        AnalysisToken("밭이랑", "NNG", False, 3),
    ))
    result = G2P().convert("밭이랑")
    assert not result.complete
    assert any(item.code == "analyzer_failed" for item in result.diagnostics.pronunciation.diagnostics)


@pytest.mark.parametrize("source,expected", json.loads(
    (Path(__file__).parent / "fixtures/adversarial_r17_korean.json").read_text(encoding="utf-8")
))
def test_r17_verified_compound_forms(source: str, expected: str) -> None:
    result = G2P().convert(source)
    assert result.normalized_text == source
    assert result.surface_pronunciation == expected
    assert result.complete


@pytest.mark.parametrize("source,expected", json.loads(
    (Path(__file__).parent / "fixtures/adversarial_r17_midi.json").read_text(encoding="utf-8")
))
def test_r17_midi_reading_and_structure_controls(source: str, expected: str) -> None:
    assert G2P().convert(source).normalized_text == expected


@pytest.mark.parametrize("address", [
    "https://example.com/NASA", "example.com/NASA", "localhost/NASA",
    "[fe80::1%eth0]/NASA", "127.0.0.1/NASA", "NASA。example/FIFA",
])
@pytest.mark.parametrize("delimiter", ["`", "``", "｀"])
@pytest.mark.parametrize("word,reading", [("MIDI", "미디"), ("NASA", "나사"), ("UNESCO", "유네스코")])
def test_r19_address_inside_inline_code_stops_at_closing_delimiter(
    address: str, delimiter: str, word: str, reading: str,
) -> None:
    code = delimiter + address + delimiter
    source = code + word
    ranges = scan_english_structures(source)
    assert [(item.start, item.end) for item in ranges] == [(0, len(code))]
    reader = G2P()
    result = reader.convert(source)
    assert result.normalized_text == reader.convert(code).normalized_text + reading
    assert reader(source) == result.surface_pronunciation


@pytest.mark.parametrize("literal", [
    '"C:/NASA`MIDI`/UNESCO"', '"../NASA`MIDI`/TEAM"',
    '"NASA`MIDI`"@example.com', '"NASA`MIDI`"@[IPv6:::1]',
])
def test_r19_outer_quoted_structure_keeps_literal_backticks(literal: str) -> None:
    source = literal + " NASA"
    ranges = scan_english_structures(source)
    assert [(item.start, item.end) for item in ranges] == [(0, len(literal))]
    normalized = G2P().convert(source).normalized_text
    assert "엠아이디아이" in normalized
    assert normalized.endswith(" 나사")


_R20_HOSTS = ["https://a.example", "a.example", "localhost", "[fe80::1%eth0]", "a。example", "127.0.0.1"]


@pytest.mark.parametrize("first_host", _R20_HOSTS)
@pytest.mark.parametrize("second_host", _R20_HOSTS)
@pytest.mark.parametrize("code", [True, False])
def test_r20_clipped_address_does_not_skip_the_following_address(
    first_host: str, second_host: str, code: bool,
) -> None:
    first = first_host + "/(NASA)"
    first = "`" + first + "`" if code else "(" + first + ")"
    source = first + "MIDI(" + second_host + "/(UNESCO))MIDI"
    ranges = scan_english_structures(source)
    for word in ("NASA", "UNESCO"):
        start = source.index(word)
        assert any(item.start <= start and start + len(word) <= item.end for item in ranges)
    for start in (len(first), len(source) - 4):
        assert not any(item.start < start + 4 and start < item.end for item in ranges)
    normalized = G2P().convert(source).normalized_text
    assert "엔에이에스에이" in normalized
    assert "유엔이에스씨오" in normalized
    assert normalized.count("미디") == 2


@pytest.mark.parametrize("source,expected", [
    ("{ }NASA@example.com", "{ }엔에이에스에이@이엑스에이엠피엘이.씨오엠"),
    ("{ }NASA@example.com MIDI", "{ }엔에이에스에이@이엑스에이엠피엘이.씨오엠 미디"),
    ("{ \n}NASA@example.com", "{ \n}엔에이에스에이@이엑스에이엠피엘이.씨오엠"),
    ("｛ ｝ＮＡＳＡ＠example.com", "｛ ｝엔에이에스에이＠이엑스에이엠피엘이.씨오엠"),
    ("앞 { }NASA@example.com 뒤", "앞 { }엔에이에스에이@이엑스에이엠피엘이.씨오엠 뒤"),
    ("{\t}NASA@example.com", "{\t}엔에이에스에이@이엑스에이엠피엘이.씨오엠"),
])
def test_r20_empty_clipped_email_candidate_does_not_raise(source: str, expected: str) -> None:
    reader = G2P()
    result = reader.convert(source)
    assert result.normalized_text == expected
    assert reader(source) == result.surface_pronunciation
    assert all(item.start < item.end for item in scan_english_structures(source))


@pytest.mark.parametrize("code", [True, False])
def test_r20_many_adjacent_addresses_keep_each_boundary(code: bool) -> None:
    address = "a.example/(NASA)"
    block = "`" + address + "`" if code else "(" + address + ")"
    normalized = G2P().convert((block + "MIDI") * 100).normalized_text
    assert normalized.count("엔에이에스에이") == 100
    assert normalized.count("미디") == 100
