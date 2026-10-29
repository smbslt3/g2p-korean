"""동형어의 가격·가족·수량 관계와 실제 발음 전달을 검증한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


def _tokens(text):
    return tuple(SemanticToken(t.form, t.tag, t.normalized_start, t.normalized_end, t.morphemes)
                 for t in KiwiAnalyzer().analyze_components(text))


def _manual(text, pieces):
    # 분석기 판단을 평가하지 않는 관계 검사는 직접 작성한 정상 분석으로 고정한다.
    cursor = 0
    tokens = []
    for surface, tag, *canonical in pieces:
        start = text.index(surface, cursor)
        end = start + len(surface)
        tokens.append(SemanticToken(surface, tag, start, end, canonical[0] if canonical else ()))
        cursor = end
    return tuple(tokens)


@pytest.mark.parametrize(("text", "expected"), [
    ("그림을 고가에 샀다.", ("goga.expensive_price",)),
    ("그림을 고가에서 샀다.", (None,)),
    ("그림을 고가로 팔았다.", ("goga.expensive_price",)),
    ("고가를 조사했다.", (None,)),
    ("시가를 읊었다.", ("siga.literary_poetry",)),
    ("시가를 산정했다.", ("siga.market_price",)),
    ("시가를 분석했다.", (None,)),
    ("소수로 바꾸었다.", (None,)),
    ("민법을 읽고 사법을 이야기했다.", (None,)),
    ("시가는 가격이 아니다.", (None,)),
    ("시가를 읊고 시가를 산정했다.", ("siga.literary_poetry", "siga.market_price")),
    ("그림을 고가에 “샀다”.", (None,)),
])
def test_actual_roles_and_clause_boundaries_keep_occurrences_separate(text, expected):
    choices = select_senses(text, _tokens(text))
    assert tuple(choice.sense_id for choice in choices) == expected


@pytest.mark.parametrize("word", ["고가", "사법", "소수", "시가"])
def test_supported_bare_common_noun_is_explicitly_unresolved(word):
    choice, = select_senses(word, (SemanticToken(word, "NNG", 0, len(word)),))
    assert choice.sense_id is None
    assert choice.reason == "insufficient_evidence"


@pytest.mark.parametrize(("text", "pieces"), [
    ("친정과 시가에 선물을 샀다.", [
        ("친정", "NNG"), ("과", "JC"), ("시가", "NNG"), ("에", "JKB"),
        ("선물", "NNG"), ("을", "JKO"), ("샀", "VV+EP", (("사", "VV"), ("었", "EP"))), ("다", "EF"),
    ]),
    ("시가에 선물을 샀다.", [
        ("시가", "NNG"), ("에", "JKB"), ("선물", "NNG"), ("을", "JKO"),
        ("샀", "VV+EP", (("사", "VV"), ("었", "EP"))), ("다", "EF"),
    ]),
    ("집을 시가에 팔았다.", [
        ("집", "NNG"), ("을", "JKO"), ("시가", "NNG"), ("에", "JKB"),
        ("팔", "VV"), ("았", "EP", (("었", "EP"),)), ("다", "EF"),
    ]),
])
def test_family_recipient_or_ambiguous_transaction_is_not_forced_to_price(text, pieces):
    choice, = select_senses(text, _manual(text, pieces))
    assert choice.sense_id is None


def _divisor_tokens(text, approximate=False):
    pieces = [("자연수", "NNG"), ("약수", "NNG"), ("가", "JKS")]
    if approximate:
        pieces.append(("대략", "MAG"))
    pieces += [("두", "MM"), ("개", "NNB"), ("인", "VCP+ETM", (("이", "VCP"), ("ᆫ", "ETM"))),
               ("소수", "NNG"), ("다", "VCP+EF", (("이", "VCP"), ("다", "EF")))]
    return _manual(text, pieces)


@pytest.mark.parametrize("approximate", [False, True])
def test_prime_requires_exact_natural_divisor_count(approximate):
    text = "자연수 약수가 " + ("대략 " if approximate else "") + "두 개인 소수다."
    choice, = select_senses(text, _divisor_tokens(text, approximate))
    assert choice.sense_id == (None if approximate else "sosu.prime_number")


def test_hard_boundary_cuts_divisor_count_evidence():
    text = "자연수 약수가 두 개인 소수다."
    choice, = select_senses(text, _divisor_tokens(text), frozenset({text.index("두")}))
    assert choice.sense_id is None


def test_complete_prefix_suffix_nominal_reaches_same_price_relation():
    text = "그림을 고가에 샀다."
    pieces = [("그림", "NNG"), ("을", "JKO"), ("고", "XPN"), ("가", "XSN"), ("에", "JKB"),
              ("샀", "VV+EP", (("사", "VV"), ("었", "EP"))), ("다", "EF")]
    choice, = select_senses(text, _manual(text, pieces))
    assert choice.sense_id == "goga.expensive_price"
    assert (choice.start, choice.end) == (4, 6)


@pytest.mark.parametrize(("text", "start", "expected"), [
    ("그림을 고가에 샀다.", 4, "고까"),
    ("그림을 고가로 팔았다.", 4, "고까"),
    ("시가를 산정했다.", 0, "시까"),
    ("시가를 읊고 시가를 산정했다.", 7, "시까"),
])
def test_selected_lexical_boundary_reaches_public_output(text, start, expected):
    converter = G2P()
    detailed = converter.convert(text)
    assert converter(text) == detailed.surface_pronunciation
    assert detailed.surface_pronunciation[start:start + len(expected)] == expected
    assert detailed.complete
