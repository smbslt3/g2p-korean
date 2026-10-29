"""정상 분석에서 정의·논항 소유·병렬 분류와 출현별 경계를 검증한다."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from g2p_ko.korean.semantic_policy import SemanticToken, select_senses


_DATA = json.loads((Path(__file__).parent / "fixtures" / "korean_semantic_definitions.json").read_text(encoding="utf-8"))
_CASES = _DATA["cases"]
_HARD_CASES = [case for case in _CASES if case["id"] in _DATA["relative_hard_cut_case_ids"]]


def _tokens(case):
    return tuple(SemanticToken(**token) for token in case["tokens"])


def _shift_back(choice, offset):
    # 상대 좌표만 이동하며 근거의 종류·개수·자료형은 그대로 비교한다.
    evidence = tuple(replace(item, target_start=item.target_start - offset,
                             target_end=item.target_end - offset, anchor_start=item.anchor_start - offset,
                             anchor_end=item.anchor_end - offset) for item in choice.evidence)
    return replace(choice, start=choice.start - offset, end=choice.end - offset, evidence=evidence)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_definition_roles_and_coherent_types(case):
    choices = select_senses(case["text"], _tokens(case), frozenset(case["hard_boundaries"]))
    assert len(choices) == len(case["targets"])
    for target in case["targets"]:
        choice, = [choice for choice in choices if (choice.start, choice.end) == (target["start"], target["end"])]
        assert choice.sense_id == target["sense_id"]
        for evidence in choice.evidence:
            assert 0 <= evidence.anchor_start <= evidence.anchor_end <= len(case["text"])
            assert (evidence.target_start, evidence.target_end) == (choice.start, choice.end)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["id"])
def test_repeated_sentence_preserves_local_choices_and_evidence(case):
    tokens = _tokens(case)
    original = select_senses(case["text"], tokens, frozenset(case["hard_boundaries"]))
    offset = len(case["text"]) + 1
    duplicate_tokens = tuple(replace(token, start=token.start + offset, end=token.end + offset) for token in tokens)
    boundaries = frozenset(case["hard_boundaries"] + [value + offset for value in case["hard_boundaries"]])
    result = select_senses(case["text"] + " " + case["text"], tokens + duplicate_tokens, boundaries)
    first = tuple(choice for choice in result if choice.start < offset)
    second = tuple(_shift_back(choice, offset) for choice in result if choice.start >= offset)
    assert original == first == second


@pytest.mark.parametrize("case", _HARD_CASES, ids=lambda case: case["id"])
def test_hard_boundary_blocks_preceding_definition(case):
    target = case["targets"][0]
    choices = select_senses(case["text"], _tokens(case), frozenset({target["start"]}))
    choice, = [choice for choice in choices if (choice.start, choice.end) == (target["start"], target["end"])]
    assert choice.sense_id is None


@pytest.mark.parametrize("positive,complement,expected,signed,unresolved", [
    (True, (("집", "NNG"), ("이", "JKC")), None, True, False),
    (True, (("가격", "NNG"), ("이", "JKC")), "goga.old_house", True, False),
    (False, (("가격", "NNG"), ("이", "JKC")), None, True, False),
    (True, (("영희", "NNP"), ("가", "JKC")), "goga.old_house", False, False),
    (True, (("영희", "NNP"), ("의", "JKG"), (" ", ""), ("집", "NNG"), ("이", "JKC")), "goga.old_house", False, False),
    (True, (("대상", "NNG"), ("이", "JKC")), None, False, True),
    (True, (("집", "NNG"), ("이", "JKS")), "goga.old_house", False, False),
], ids=["same_type", "different_type", "negative_only", "named_entity", "owned_reference", "ambiguous", "new_subject"])
def test_finite_nominal_type_negative_and_reference_guards(positive, complement, expected, signed, unresolved):
    # 비공개 평가 문장을 쓰지 않고 기존 집/가격 분류만 조합한 합성 회귀다.
    pieces = [("고가", (("고가", "NNG"),)), ("는", (("는", "JX"),)), (" ", ())]
    if positive:
        pieces += [("집", (("집", "NNG"),)), ("이고", (("이", "VCP"), ("고", "EC"))), (" ", ())]
    pieces += [(form, ((form, tag),) if tag else ()) for form, tag in complement]
    pieces += [(" ", ()), ("아니다", (("아니", "VCN"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = "", []
    for surface, morphemes in pieces:
        start = len(text)
        text += surface
        if morphemes:
            tokens.append(SemanticToken(surface, "+".join(tag for _, tag in morphemes), start, len(text), morphemes))
    choice, = select_senses(text, tuple(tokens))
    assert choice.sense_id == expected
    negative = [item for item in choice.evidence if item.relation in {"negative_copular_category", "negative_copular_category_predicate"}]
    assert bool(negative) == signed
    assert any(item.relation == "unresolved_negative_type" for item in choice.evidence) == unresolved
    assert all((item.target_start, item.target_end) == (0, 2) for item in negative)


def _synthetic_surface(pieces):
    text, tokens = "", []
    for surface, morphemes in pieces:
        start = len(text)
        text += surface
        if morphemes:
            tokens.append(SemanticToken(surface, "+".join(tag for _, tag in morphemes), start, len(text), morphemes))
    return text, tuple(tokens)


@pytest.mark.parametrize("shape", ["inverse", "relative_conflict", "relative_entity", "internal_subject"])
def test_existing_inverse_and_relative_negative_shapes_use_actual_head_owner(shape):
    # 기존 범주 사실만 쓰는 합성 회귀이며 비공개 평가 원문을 복제하지 않는다.
    space = (" ", ())
    if shape == "inverse":
        pieces = [("집", (("집", "NNG"),)), ("인", (("이", "VCP"), ("ᆫ", "ETM"))), space,
                  ("고가", (("고가", "NNG"),)), ("가", (("가", "JKS"),)), space,
                  ("가격", (("가격", "NNG"),)), ("은", (("은", "JX"),)), space,
                  ("아니다", (("아니", "VCN"), ("다", "EF"))), (".", ((".", "SF"),))]
    else:
        nominal = ("영희", "NNP") if shape == "relative_entity" else ("집", "NNG")
        pieces = [("영희", (("영희", "NNP"),)), ("가", (("가", "JKS"),)), space] if shape == "internal_subject" else []
        pieces += [(nominal[0], (nominal,)), ("이" if nominal[0] == "집" else "가", (("이" if nominal[0] == "집" else "가", "JKC"),)), space,
                   ("아닌", (("아니", "VCN"), ("ᆫ", "ETM"))), space,
                   ("고가", (("고가", "NNG"),)), ("는", (("는", "JX"),)), space,
                   ("집", (("집", "NNG"),)), ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = _synthetic_surface(pieces)
    choice, = select_senses(text, tokens)
    negative = [item for item in choice.evidence if item.relation in {"negative_copular_category", "negative_copular_category_predicate"}]
    assert bool(negative) == (shape in {"inverse", "relative_conflict"})
    assert all((item.target_start, item.target_end) == (choice.start, choice.end) for item in negative)
    if shape == "relative_conflict":
        assert choice.sense_id is None and choice.reason == "conflicting_evidence"
    elif shape != "internal_subject":
        assert choice.sense_id == "goga.old_house"


@pytest.mark.parametrize("related", [True, False])
def test_judgment_relative_requires_actual_value_or_level_object(related):
    objects = ([("물품", (("물품", "NNG"),)), ("의", (("의", "JKG"),)), (" ", ()),
                ("수준", (("수준", "NNG"),)), ("과", (("과", "JC"),)), (" ", ()),
                ("가치", (("가치", "NNG"),))] if related else
               [("물품", (("물품", "NNG"),)), ("과", (("과", "JC"),)), (" ", ()), ("물건", (("물건", "NNG"),))])
    pieces = [("평가", (("평가", "NNG"),)), ("는", (("는", "JX"),)), (" ", ()),
              *objects, ("를" if related else "을", (("를" if related else "을", "JKO"),)), (" ", ()),
              ("헤아리", (("헤아리", "VV"),)), ("는", (("는", "ETM"),)), (" ", ()),
              ("판단", (("판단", "NNG"),)), ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = _synthetic_surface(pieces)
    choice, = select_senses(text, tokens)
    evidence = [item for item in choice.evidence if item.relation == "copular_category" and item.semantic_class == "assessment"]
    assert bool(evidence) == related
    if related:
        assert choice.sense_id == "pyeongga.appraisal"
        assert all((item.target_start, item.target_end) == (0, 2) for item in evidence)
    else:
        assert choice.sense_id is None


@pytest.mark.parametrize("kind", ["operation", "nominal", "missing_basis"])
def test_currency_ratio_requires_owned_value_and_actual_basis(kind):
    # 공개 자체 의미 사실에서 만든 공급 분석으로, 외화 기준과 명사 소유를 확인한다.
    space = (" ", ())
    pieces = [("평가", (("평가", "NNG"),)), ("는", (("는", "JX"),)), space,
              ("통화", (("통화", "NNG"),)), ("의", (("의", "JKG"),)), space]
    if kind == "nominal":
        pieces += [("외화", (("외화", "NNG"),)), space, ("기준", (("기준", "NNG"),)), space,
                   ("비율", (("비율", "NNG"),)), ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    else:
        pieces += [("값", (("값", "NNG"),)), ("을", (("을", "JKO"),)), space]
        if kind == "operation":
            pieces += [("외화", (("외화", "NNG"),)), ("를", (("를", "JKO"),)), space,
                       ("기준", (("기준", "NNG"),)), ("으로", (("으로", "JKB"),)), space,
                       ("한", (("하", "VV"), ("ᆫ", "ETM"))), space]
        pieces += [("비율", (("비율", "NNG"),)), ("로", (("로", "JKB"),)), space,
                   ("표시", (("표시", "NNG"),)), ("한", (("하", "XSV"), ("ᆫ", "ETM"))), space,
                   ("것", (("것", "NNB"),)), ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = _synthetic_surface(pieces)
    choice, = select_senses(text, tokens)
    relations = {item.relation for item in choice.evidence}
    if kind == "missing_basis":
        assert choice.sense_id is None
        assert not relations & {"currency_value_basis_ratio_operation", "owned_currency_basis_ratio_nominal"}
    else:
        assert choice.sense_id == "pyeongga.parity"
        expected = "currency_value_basis_ratio_operation" if kind == "operation" else "owned_currency_basis_ratio_nominal"
        assert expected in relations
        assert all((item.target_start, item.target_end) == (0, 2) for item in choice.evidence)


@pytest.mark.parametrize("kind", ["closed_meaning", "unclosed", "title"])
def test_closed_currency_description_exports_only_into_actual_meaning(kind):
    space = (" ", ())
    pieces = [("“", (("“", "SSO"),)), ("평가", (("평가", "NNG"),)), ("”", (("”", "SSC"),)),
              ("는", (("는", "JX"),)), space, ("“", (("“", "SSO"),)),
              ("통화", (("통화", "NNG"),)), ("의", (("의", "JKG"),)), space,
              ("값", (("값", "NNG"),)), ("을", (("을", "JKO"),)), space,
              ("외화", (("외화", "NNG"),)), ("를", (("를", "JKO"),)), space,
              ("기준", (("기준", "NNG"),)), ("으로", (("으로", "JKB"),)), space,
              ("한", (("하", "VV"), ("ᆫ", "ETM"))), space,
              ("비율", (("비율", "NNG"),)), ("로", (("로", "JKB"),)), space,
              ("표시", (("표시", "NNG"),)), ("한", (("하", "XSV"), ("ᆫ", "ETM"))), space,
              ("것", (("것", "NNB"),))]
    if kind != "unclosed":
        pieces.append(("”", (("”", "SSC"),)))
    head = "제목" if kind == "title" else "뜻"
    pieces += [("이라는", (("이", "VCP"), ("라는", "ETM"))), space, (head, ((head, "NNG"),)),
               ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = _synthetic_surface(pieces)
    choice, = select_senses(text, tokens)
    exported = [item for item in choice.evidence if item.relation == "closed_currency_meaning_definition"]
    assert bool(exported) == (kind == "closed_meaning")
    assert choice.sense_id == ("pyeongga.parity" if kind == "closed_meaning" else None)
    assert all((item.target_start, item.target_end) == (choice.start, choice.end) for item in exported)


@pytest.mark.parametrize("merged", [False, True])
def test_declared_nominal_source_is_complete_before_independent_relative(merged):
    nominal = [("보통가격", (("보통", "NNG"), ("가격", "NNG")))] if merged else [
        ("보통", (("보통", "NNG"),)), ("가격", (("가격", "NNG"),))]
    pieces = [("평가", (("평가", "NNG"),)), ("는", (("는", "JX"),)), (" ", ()),
              ("새로운", (("새롭", "VA"), ("은", "ETM"))), (" ", ()), *nominal,
              ("이다", (("이", "VCP"), ("다", "EF"))), (".", ((".", "SF"),))]
    text, tokens = _synthetic_surface(pieces)
    choice, = select_senses(text, tokens)
    assert choice.sense_id == "pyeongga.parity"
    assert any(item.relation == "copular_category" and item.semantic_class == "ordinary_price" for item in choice.evidence)


def test_malformed_nominal_packaging_does_not_create_confirmed_complete_source():
    from g2p_ko.korean import semantic_policy as policy

    token = SemanticToken("보통가격", "NNG+JKS", 0, 4, (("보통", "NNG"), ("가격", "NNG")))
    units = tuple(policy._morpheme_units((token,), (0,), {}, set()))
    assert not any(unit.nominal_source is not None for unit in units)
    assert token.tag == "NNG+JKS" and token.morphemes == (("보통", "NNG"), ("가격", "NNG"))
