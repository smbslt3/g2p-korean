"""정규화와 선택적 G2P 사이의 엄격한 TTS 문자열 계약을 검증한다."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from g2p_ko import ConversionPolicyError, G2P, InputValidationError, SourceSpan
from g2p_ko.normalizer import KoreanTTSNormalizer


@pytest.fixture(scope="module")
def tts() -> KoreanTTSNormalizer:
    return KoreanTTSNormalizer(output_policy="tts")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("국물 닫는 닫고.", "국물 닫는 닫고."),
        ("안녕\n\t  세상!", "안녕 세상!"),
        (" ‘안녕’ (친구)； 정말？ ", "안녕 친구, 정말?"),
        ("**국물** <b>닫는</b> 😀", "국물 닫는"),
        ("# 5% 안내\n- 국물", "오 퍼센트 안내 국물"),
        ("#공지 5% 안내", "공지 오 퍼센트 안내"),
        ("**-3.5%**부터 2~3개월", "마이너스 삼 점 오 퍼센트부터 이에서 삼 개월"),
        ("**3**개", "세 개"),
        ("**2**시에 만나요.", "두 시에 만나요."),
        ("사과 **4**개와 배 5개", "사과 네 개와 배 다섯 개"),
        ("<b>3</b>개", "세 개"),
        ("3🙂명", "세 명"),
        ("3🙂 개", "세 개"),
        ("(3)개와 ‘2’시에", "세 개와 두 시에"),
        ("인증번호 **012345**를 입력하세요.", "인증번호 공 일 이 삼 사 오를 입력하세요."),
        ("*4*명", "네 명"),
        ("<strong>2</strong>시", "두 시"),
        ("(2~3)개월", "이에서 삼 개월"),
        ("국물(닫는)‘문’", "국물 닫는 문"),
        ("OpenAI abc와 XYZ", "오픈에이아이 에이비씨와 엑스와이지"),
        ("NASA와 AI", "나사와 에이아이"),
        ("tv Tv nasa Nasa", "티비 티비 나사 나사"),
        ("인증번호 012345를 입력하세요.", "인증번호 공 일 이 삼 사 오를 입력하세요."),
        ("우편번호는 01234입니다.", "우편번호는 공 일 이 삼 사입니다."),
        ("인증 번호 012345", "인증 번호 공 일 이 삼 사 오"),
        ("우편 번호는 01234입니다.", "우편 번호는 공 일 이 삼 사입니다."),
        ("제12조 제3항을 확인하세요.", "제 십이 조 제 삼 항을 확인하세요."),
        ("제3절부터 제4편까지", "제 삼 절부터 제 사 편까지"),
        ("1. 첫 항목\n2. 다음 항목", "일. 첫 항목 이. 다음 항목"),
    ],
)
def test_successful_tts_string_contract_and_orthography(
    tts: KoreanTTSNormalizer, source: str, expected: str,
) -> None:
    result = tts.convert(source)

    assert result.complete
    assert result.normalized_text == expected == tts(source) == tts.normalize_tts(source)
    assert re.fullmatch(r"[가-힣 ,.!?]*", result.normalized_text)
    assert tts(result.normalized_text) == result.normalized_text
    assert "단는" not in result.normalized_text
    assert "닫꼬" not in result.normalized_text


def test_url_structure_preserves_leading_zero_case_and_query(tts: KoreanTTSNormalizer) -> None:
    source = "https://example.com/V01?q=A2#B에서 확인하세요."
    result = tts.convert_tts(source)

    assert result.complete
    assert "슬래시 대문자 브이 공 일" in result.normalized_text
    assert "물음표 큐 등호 대문자 에이 이 해시 대문자 비에서" in result.normalized_text
    rewrite = next(r for r in result.rewrites if r.rule_id == "normalizer.tts.url.v1")
    assert rewrite.before == "https://example.com/V01?q=A2#B"
    assert rewrite.source_spans == (SourceSpan.from_source(source, 0, len(rewrite.before)),)
    assert re.fullmatch(r"[가-힣 ,.!?]*", result.normalized_text)


def test_email_structure_keeps_tag_digits_and_delimiters(tts: KoreanTTSNormalizer) -> None:
    result = tts.convert_tts("team+01@example.com으로 보내세요.")

    assert result.complete
    assert "플러스 공 일 골뱅이" in result.normalized_text
    assert "점 씨 오 엠으로" in result.normalized_text
    assert any(r.rule_id == "normalizer.tts.email.v1" for r in result.rewrites)


@pytest.mark.parametrize(
    "source",
    ["漢字", "Москва", "العربية", "かな", "éclair", "①", "가\x85나",
     "12,34", "0012개", "제001호", "인증번호 -0123", "우편번호 012.34",
     "1-3개", "2 ✖ 3", "https://example.com/漢字1"],
)
def test_unresolved_meaning_never_returns_a_successful_tts_string(
    tts: KoreanTTSNormalizer, source: str,
) -> None:
    result = tts.convert_tts(source)

    assert not result.complete
    assert result.diagnostics
    for diagnostic in result.diagnostics:
        for span in diagnostic.source_spans:
            assert span.surface == source[span.start:span.end]
    with pytest.raises(ConversionPolicyError):
        tts(source)
    with pytest.raises(ConversionPolicyError):
        KoreanTTSNormalizer().normalize_tts(source)


def test_explicit_tts_methods_do_not_mutate_legacy_policy() -> None:
    normalizer = KoreanTTSNormalizer()
    source = "https://example.com/v1.2?q=3\n  (안내)"

    legacy_before = normalizer.convert(source)
    strict = normalizer.convert_tts(source)
    legacy_after = normalizer.convert(source)

    assert legacy_before == legacy_after
    assert legacy_before.normalized_text == source
    assert strict.complete and strict.normalized_text != source
    assert normalizer.normalize_tts(source) == strict.normalized_text


def test_nfd_decoration_and_numeric_rewrites_keep_original_coordinates(tts: KoreanTTSNormalizer) -> None:
    source = "\u1100\u1161\t😀 **5%**"
    result = tts.convert_tts(source)

    assert result.normalized_text == "가 오 퍼센트"
    decoration = next(r for r in result.rewrites if r.before == "😀")
    assert decoration.source_spans == (SourceSpan.from_source(source, 3, 4),)
    percentage = next(r for r in result.rewrites if r.rule_id == "normalizer.percentage.v1")
    assert percentage.source_spans[0].surface == "5%"
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == source[span.start:span.end]


def test_preserve_ambiguity_option_does_not_suppress_tts_failure() -> None:
    normalizer = KoreanTTSNormalizer(on_ambiguous="preserve", output_policy="tts")
    result = normalizer.convert("漢字")

    assert not result.complete
    assert any(d.code == "unsupported_tts_output" for d in result.diagnostics)
    with pytest.raises(ConversionPolicyError):
        normalizer("漢字")


@pytest.mark.parametrize("source", [
    "**2*3**", "2**3**", "**2**3", "**2**.3", "<b x='12'>3</b>",
    "<b>12,34</b>", "1<b>2</b>", "<b>3</b>.5%", "-<b>3</b>",
    "5😀%", "- 3", "#123", "5#공지%",
    "3**4**", "3<b></b>4", "3🙂.4", "1'234", "1(234)",
    "1’234", "3[4]", "5(%)", "-(3)",
])
def test_decorative_cleanup_cannot_silently_reinterpret_numbers(
    tts: KoreanTTSNormalizer, source: str,
) -> None:
    result = tts.convert_tts(source)

    assert not result.complete
    with pytest.raises(ConversionPolicyError):
        tts.normalize_tts(source)


@pytest.mark.parametrize("policy", ["preserve", "warn", "error"])
@pytest.mark.parametrize("source", ["漢字", "12,34", "~", "😀1😀2"])
def test_ambiguous_policy_composes_with_strict_output(policy: str, source: str) -> None:
    normalizer = KoreanTTSNormalizer(on_ambiguous=policy, output_policy="tts")

    assert normalizer("**5%** 할인") == "오 퍼센트 할인"
    if policy == "error":
        with pytest.raises(ConversionPolicyError):
            normalizer.convert_tts(source)
    else:
        result = normalizer.convert_tts(source)
        assert not result.complete
        assert result.diagnostics
    with pytest.raises(ConversionPolicyError):
        normalizer(source)


def test_shared_instance_keeps_per_call_output_policy_and_provenance() -> None:
    normalizer = KoreanTTSNormalizer()
    sources = ["인증번호 012345를 입력하세요.", "제12조를 확인하세요.", "OpenAI와 3개",
               "😀 **5%** 할인", "https://example.com/V01?q=A2", "국물 닫는 닫고.",
               "사과 **4**개와 3🙂명", "<b>2</b>시에 만나요."]
    requests = [(strict, source) for strict in (False, True) for source in sources] * 4

    def convert(request: tuple[bool, str]):
        strict, source = request
        return normalizer.convert_tts(source) if strict else normalizer.convert(source)

    expected = [convert(request) for request in requests]
    with ThreadPoolExecutor(max_workers=4) as executor:
        actual = list(executor.map(convert, requests))

    assert actual == expected
    for result in actual:
        for record in (*result.rewrites, *result.diagnostics):
            for span in record.source_spans:
                assert span.surface == result.source[span.start:span.end]


def test_decorated_numeric_unit_keeps_all_original_coordinates(tts: KoreanTTSNormalizer) -> None:
    source = "\u1100\u1161 사과 **4**개와 <b>2</b>시, 3🙂명"
    result = tts.convert_tts(source)

    assert result.complete and result.normalized_text == "가 사과 네 개와 두 시, 세 명"
    numeric = [r for r in result.rewrites if r.handler.value == "numeric"]
    assert any(r.before == "4개와" and r.source_spans[0].surface == "4**개와" for r in numeric)
    assert any(r.before == "3 명" and r.source_spans[0].surface == "3🙂명" for r in numeric)
    assert sum(r.rule_id == "normalizer.tts.decoration.v1" for r in result.rewrites) == 5
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]
    assert tts(result.normalized_text) == result.normalized_text


@pytest.mark.parametrize("policy", ["preserve", "warn", "error"])
def test_blocked_numeric_punctuation_cannot_be_reported_as_complete(policy: str) -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", on_ambiguous=policy)
    if policy == "error":
        with pytest.raises(ConversionPolicyError):
            normalizer.convert_tts("1'234")
    else:
        result = normalizer.convert_tts("1'234")
        assert not result.complete
        assert any(d.code == "unsafe_numeric_decoration" and d.source_spans[0].surface == "'"
                   for d in result.diagnostics)
    with pytest.raises(ConversionPolicyError):
        normalizer("1'234")


def test_user_lexicon_precedes_unknown_english_spelling() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"OpenAI": "오픈에이아이"})

    assert normalizer("OpenAI에서 5개") == "오픈에이아이에서 다섯 개"


def test_projection_keeps_lexicon_priority_and_optional_g2p_contract() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"TV": "티브이", "OpenAI": "오픈에이아이"})
    source = "**OpenAI**와 <b>TV</b>의 국물, 사과 **3**개"
    result = normalizer.convert_tts(source)

    assert result.complete and result.normalized_text == "오픈에이아이와 티브이의 국물, 사과 세 개"
    pronunciation = G2P().convert(result.normalized_text, normalize=False)
    assert pronunciation.complete
    assert re.fullmatch(r"[가-힣 ,.!?]*", pronunciation.surface_pronunciation)
    assert "궁물" in pronunciation.surface_pronunciation
    assert result.normalized_text == pronunciation.normalized_text
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]


@pytest.mark.parametrize(("lexicon", "source", "expected"), [
    ({"🙂": "웃음"}, "안녕 🙂", "안녕 웃음"),
    ({"★": "별표"}, "별 ★", "별 별표"),
    ({"**3**": "삼"}, "**3**개", "삼개"),
    ({"<b>3</b>": "삼"}, "<b>3</b>개", "삼개"),
])
def test_explicit_decoration_lexicon_precedes_projection(
    lexicon: dict[str, str], source: str, expected: str,
) -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon=lexicon)
    result = normalizer.convert_tts(source)

    assert result.complete and result.normalized_text == expected == normalizer(source)
    assert not any(rewrite.rule_id == "normalizer.tts.decoration.v1" for rewrite in result.rewrites)
    assert normalizer(expected) == expected
    for rewrite in result.rewrites:
        for span in rewrite.source_spans:
            assert span.surface == source[span.start:span.end]


def test_lexicon_decoration_guard_keeps_nfd_and_projected_coordinates() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"**가**": "까", "🙂": "웃음", "OpenAI": "오픈에이아이"})
    source = "\u1100\u1161 **\u1100\u1161** 🙂, 사과 **3**개와 OpenAI"
    result = normalizer.convert_tts(source)

    assert result.complete and result.normalized_text == "가 까 웃음, 사과 세 개와 오픈에이아이"
    assert any(r.before == "**가**" and r.source_spans[0].surface == "**\u1100\u1161**" for r in result.rewrites)
    assert any(r.before == "3개와" and r.source_spans[0].surface == "3**개와" for r in result.rewrites)
    assert all(r.before != "🙂" for r in result.rewrites if r.rule_id == "normalizer.tts.decoration.v1")
    for record in (*result.rewrites, *result.diagnostics):
        for span in record.source_spans:
            assert span.surface == source[span.start:span.end]


def test_projection_lexicon_guard_does_not_override_protected_url_policy() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", lexicon={"★": "별표", "https://example.com/A1": "주소"})
    result = normalizer.convert_tts("★ https://example.com/A1")

    assert result.complete and result.normalized_text.startswith("별표 ")
    assert "슬래시 대문자 에이 일" in result.normalized_text
    assert any(r.rule_id == "normalizer.tts.url.v1" for r in result.rewrites)


def test_tts_output_length_limit_also_covers_structural_expansion() -> None:
    normalizer = KoreanTTSNormalizer(output_policy="tts", max_output_length=8)

    with pytest.raises(InputValidationError, match="최대 길이"):
        normalizer("a@example.com")


@pytest.mark.parametrize("policy", [None, True, "unknown"])
def test_output_policy_is_validated(policy: object) -> None:
    with pytest.raises(InputValidationError, match="output_policy"):
        KoreanTTSNormalizer(output_policy=policy)  # type: ignore[arg-type]
