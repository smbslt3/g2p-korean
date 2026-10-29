"""일반 수량·배율 계층·독립형 수사의 값과 원문 좌표를 검증한다."""

from __future__ import annotations

from decimal import Inexact, localcontext
import random

import pytest

from g2p_ko import KoreanTTSNormalizer
from g2p_ko.errors import ConversionPolicyError
from g2p_ko.normalizer.numbers import read_sino
from g2p_ko.normalizer.output_policy import is_tts_text


@pytest.mark.parametrize(("source", "expected"), [
    ("2박 3일 쉬어요.", "이 박 삼 일 쉬어요."),
    ("2박3일", "이 박 삼 일"),
    ("2박3일은", "이 박 삼 일은"),
    ("지하철 2호선입니다.", "지하철 이 호선입니다."),
    ("2호선은", "이 호선은"),
    ("밝기를 3칸 올려요.", "밝기를 세 칸 올려요."),
    ("42칸", "마흔두 칸"),
    ("21자리 남았어요.", "스물한 자리 남았어요."),
    ("3자리 수", "세 자리 수"),
    ("2만 3천 원입니다.", "이만삼천 원입니다."),
    ("3천 명입니다.", "삼천 명입니다."),
    ("3천명은", "삼천 명은"),
    ("3천여 명", "삼천여 명"),
    ("2만 3천 400원", "이만삼천사백 원"),
    ("1만2천3백4십5원", "만이천삼백사십오 원"),
    ("1억 2천만 원", "일억이천만 원"),
    ("1억 2천 만 원", "일억이천만 원"),
    ("2천만원", "이천만 원"),
    ("2천 만원", "이천만 원"),
    ("2천 만 원", "이천만 원"),
    ("1조 3천억 원", "일조삼천억 원"),
    ("1억2천3백40만5천원", "일억이천삼백사십만오천 원"),
    ("2천3백만원", "이천삼백만 원"),
    ("2천3만원", "이천삼만 원"),
    ("1.5만 원", "만오천 원"),
    ("1.5만2천원", "만칠천 원"),
    ("3.5천명", "삼천오백 명"),
    ("-1억2천만원", "마이너스 일억이천만 원"),
    ("+2만3천원", "플러스 이만삼천 원"),
    ("2만 원에서 3만 원까지", "이만 원에서 삼만 원까지"),
    ("3천kg", "삼천 킬로그램"),
    ("4천167㎢", "사천백육십칠 제곱킬로미터"),
])
@pytest.mark.parametrize("output_policy", ["preserve", "tts"])
def test_general_quantities_read_without_losing_value(source, expected, output_policy):
    normalizer = KoreanTTSNormalizer(output_policy=output_policy)
    result = normalizer.convert(source)
    assert result.complete
    assert result.normalized_text == expected
    assert normalizer(expected) == expected
    if output_policy == "tts":
        assert is_tts_text(expected)


@pytest.mark.parametrize("source", [
    "2만3억원", "2만 3억 원", "2만3천만원", "2백3천원", "2천3천원",
    "2만30천원", "1억20000만원", "2만30000원", "1천20백원",
    "2만03천원", "02천명", "1,23만4천원", "3.000천명", "1억2.000천만원",
    "1억2천 만3억 원", "2천 만 만 원", "2천 억3조 원",
    "1억+2천만원", "1억-2천만원", "12345678901천명",
    "3천명단", "3천 명칭", "2호선도시", "3자리잡기", "2박3일정",
    "02박3일", "2.5박3일", "2박12345678901일", "2만3천원A", "x.3천명",
    "-<b>2만3천</b>원", "**2**박**3**일",
])
def test_ambiguous_quantities_never_become_successful_tts(source):
    preserve = KoreanTTSNormalizer().convert(source)
    if "<" not in source and "*" not in source:
        assert preserve.normalized_text == source
        assert not preserve.complete
    strict = KoreanTTSNormalizer(output_policy="tts")
    assert not strict.convert(source).complete
    with pytest.raises(ConversionPolicyError):
        strict(source)


@pytest.mark.parametrize("source", [
    "**2만3천**원", "<b>1억</b> 2천만원",
    "\u1100\u1161 **42**칸과 <b>21</b>자리",
])
def test_projected_quantities_keep_original_spans_and_repeat_safely(source):
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    result = normalizer.convert(source)
    assert result.complete and is_tts_text(result.normalized_text)
    assert normalizer(result.normalized_text) == result.normalized_text
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]


class _ForcedRun:
    def __init__(self, calls):
        self.calls = calls

    def decide(self, start, end, **options):
        self.calls.append((start, end, options))
        return "native"

    def take_failure(self):
        return None


class _ForcedReader:
    def __init__(self):
        self.calls = []

    def new_run(self, text):
        return _ForcedRun(self.calls)


@pytest.mark.parametrize(("source", "expected"), [
    ("1 더", "하나 더"), ("2 더", "둘 더"), ("3 더", "셋 더"), ("4 더", "넷 더"),
    ("20 더", "스물 더"), ("21 더", "스물하나 더"),
    ("16 더", "열여섯 더"), ("68 더", "예순여덟 더"),
    ("3명", "세 명"), ("20개", "스무 개"),
    ("42칸", "마흔두 칸"), ("21자리", "스물한 자리"),
])
def test_native_context_uses_standalone_or_unit_form(source, expected):
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    normalizer._number_reader = _ForcedReader()
    assert normalizer(source) == expected


@pytest.mark.parametrize("source", ["012", "12345678901", "1e3", "2만03천원"])
def test_native_context_does_not_bypass_numeric_defenses(source):
    reader = _ForcedReader()
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    normalizer._number_reader = reader
    assert not normalizer.convert(source).complete
    assert reader.calls == []


def test_unconfigured_reader_keeps_rule_default_for_bare_number():
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    assert normalizer("1 더") == "일 더"


def test_hierarchical_quantities_preserve_independently_computed_values():
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    generator = random.Random(2718)
    for _ in range(100):
        a = generator.randint(1, 9)
        digits = [generator.randint(0, 9) for _ in range(12)]
        b, c, d, e, f, g, h, i, j, k, l, m = digits
        source = f"{a}조 {b}천{c}백{d}십{e}억 {f}천{g}백{h}십{i}만 {j}천{k}백{l}십{m}원"
        value = a * 10**12 + (b * 1000 + c * 100 + d * 10 + e) * 10**8
        value += (f * 1000 + g * 100 + h * 10 + i) * 10**4
        value += j * 1000 + k * 100 + l * 10 + m
        assert normalizer(source) == read_sino(str(value)) + " 원"


def test_quantity_arithmetic_is_independent_of_callers_decimal_context():
    normalizer = KoreanTTSNormalizer(output_policy="tts")
    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        assert normalizer("1억 2천 만 원") == "일억이천만 원"
        assert context.prec == 2 and context.Emax == 2 and context.Emin == -2
