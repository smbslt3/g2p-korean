"""외부 사례를 보지 않고 고정한 두 어근의 합성·소유권 계약 검사."""

from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

STAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE / "src"))

from g2p_ko import G2P
from g2p_ko.analyzer import KiwiAnalyzer, _get_kiwi
from g2p_ko.korean import engine
from g2p_ko.korean.owned_lexical import OWNED_LEXICAL_ROOTS, owned_root_matches
from g2p_ko.korean.morphology import _Annotation, _has_licensed_nominal_tail
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan

CASES = json.loads((STAGE / "tests/fixtures/round23_owned_lexical_contract.json").read_text(encoding="utf-8"))["cases"]
OWNED_RULES = {"ko.lexical.tensing", "ko.sino.tensing.26"}


def segment(text, start=0, end=None, *, hard=False):
    end = len(text) if end is None else end
    return OutputSegment(text[start:end], (SourceSpan.from_source(text, start, end),), Handler.KOREAN,
                         "독립합성검사", boundary_before=Boundary.HARD if hard else Boundary.WORD)


def run(text, rows, *, pause=(), hard=None):
    tokens = tuple(AnalysisToken(*row) for row in rows)
    calls = []

    class Analyzer:
        def analyze(self, source):
            calls.append(source)
            if source == text:
                return tokens
            return KiwiAnalyzer().analyze_components(source)

    segments = (segment(text),) if hard is None else (segment(text, 0, hard), segment(text, hard, hard=True))
    with patch.object(engine, "KiwiAnalyzer", Analyzer):
        result = engine.pronounce(segments, pause_boundaries=pause)
        plain = engine.pronounce_text(segments, pause_boundaries=pause)
    assert plain == result.text
    for rewrite in result.rewrites:
        assert all(text[span.start:span.end] == span.surface for span in rewrite.source_spans)
    assert not {"ko.lexical.verified", "ko.official.morpheme"} & {r.rule_id for r in result.rewrites}
    return result


def affected(result):
    return [(r.rule_id, max(span.end for span in r.source_spans) - 1)
            for r in result.rewrites if r.rule_id in OWNED_RULES]


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def test_independent_frozen_supplied_contract(case):
    result = run(case["text"], case["rows"])
    expected = [] if case["rule"] is None else [(case["rule"], case["affected"])]
    assert affected(result) == expected


@pytest.mark.parametrize("text,rows", (
    ("문자 메시지", (("문자", "NNG", 0, 2, (("문자", "VV"),)), ("메시지", "NNG", 3, 6))),
    ("문자 메시지", (("문자", "NNG+JX", 0, 2), ("메시지", "NNG", 3, 6))),
    ("문자 메시지", (("문자", "NNG", 0, 2), ("메시지", "NNP", 3, 6))),
    ("일산동구", (("일산동구", "VV", 0, 4),)),
    ("일산동구", (("일산동구", "NNP", 0, 4, (("일산", "NNP"),)),)),
    ("일산동구", (("일산", "NR", 0, 2), ("동구", "NNG", 2, 4))),
    ("일산동구", (("일산", "NNP", 0, 2), ("구", "NNG", 3, 4))),
    ("일산동구", (("일산동", "NNP", 0, 3), ("동구", "NNG", 2, 4))),
    ("일산동구", (("일산동구", "NNP", 0, 3),)),
    ("일산동구", (("일신동구", "NNP", 0, 4),)),
    ("일산동구도", (("일산동구", "NNP", 0, 4), ("도", "JX", 4, 5, (("도", "NNG"),)))),
))
def test_forged_unsupported_and_homograph_analyses_have_no_owned_property(text, rows):
    assert affected(run(text, rows)) == []


@pytest.mark.parametrize("word,rows,rule", (
    ("문자 메시지", (("문자", "NNG", 0, 2), ("메시지", "NNG", 3, 6)), "ko.lexical.tensing"),
    ("일산동구", (("일산동구", "NNP", 0, 4),), "ko.sino.tensing.26"),
))
@pytest.mark.parametrize("barrier", ("pause", "hard"))
def test_internal_barriers_prevent_property_realization(word, rows, rule, barrier):
    result = run(word, rows, pause=(1,) if barrier == "pause" else (), hard=1 if barrier == "hard" else None)
    assert rule not in {r.rule_id for r in result.rewrites}


@pytest.mark.parametrize("cut", (2, 3))
def test_place_composition_cannot_borrow_identity_across_hard(cut):
    assert affected(run("일산동구", (("일산동구", "NNP", 0, 4),), hard=cut)) == []


@pytest.mark.parametrize("text,rows", (
    ("문자메시지의", (("문자", "NNG", 0, 2), ("메시지", "NNG", 2, 5), ("의", "JKG", 5, 6))),
    ("일산동구이다", (("일산동구", "NNP", 0, 4), ("이", "VCP", 4, 5), ("다", "EF", 5, 6))),
    ("일산동구인", (("일산동구", "NNP", 0, 4), ("인", "VCP+ETM", 4, 5, (("이", "VCP"), ("ᆫ", "ETM"))))),
))
def test_verified_particle_and_copula_ownership_keeps_only_internal_onset(text, rows):
    assert [position for _, position in affected(run(text, rows))] == [1]


def test_explicit_text_sense_uses_existing_generic_semantic_relations():
    text = "문자는 기호다"
    rows = [("문자", "NNG", 0, 2), ("는", "JX", 2, 3), ("기호", "NNG", 4, 6),
            ("다", "VCP+EF", 6, 7, (("이", "VCP"), ("다", "EF")))]
    assert affected(run(text, rows)) == [("ko.lexical.tensing", 1)]
    assert G2P()(text).startswith("문짜는")


@pytest.mark.parametrize("text", ("문자는 이름이다", "문자는 한문이다", "문자는 학식이다"))
def test_unverified_or_unresolved_identity_is_deferred(text):
    result = engine.pronounce((segment(text),))
    assert affected(result) == []


@pytest.mark.parametrize("text", ("문자", "문자를 보냈다", "문자를 읽었다", "문자 체계", "문자는 메시지다"))
def test_shorthand_and_text_default_are_reachable_without_verb_lists(text):
    result = engine.pronounce((segment(text),))
    assert affected(result) == [("ko.lexical.tensing", 1)]
    assert G2P()(text).startswith("문짜")


def test_default_is_policy_and_explicit_message_identity_is_selected():
    from g2p_ko.korean.semantic_policy import SemanticToken, select_senses
    recorded = []
    for text in ("문자를 보냈다", "문자는 메시지다", "문자는 한문이다", "문자는 학식이다"):
        tokens = KiwiAnalyzer().analyze_components(text)
        semantic = tuple(SemanticToken(t.form, t.tag, t.normalized_start, t.normalized_end, t.morphemes) for t in tokens)
        choices = select_senses(text, semantic)
        matches = tuple(owned_root_matches(text, _Annotation.from_tokens(tokens, text), choices,
                         nominal_tail_validator=_has_licensed_nominal_tail))
        recorded.append({"text": text, "choices": [asdict(c) for c in choices],
                         "ownership": [m.evidence_kind for m in matches]})
    assert recorded[0]["ownership"] == ["dictionary_default_policy"]
    assert recorded[1]["ownership"] == ["selected_sense"]
    assert recorded[2]["ownership"] == recorded[3]["ownership"] == []


def test_frozen_actual_provider_shapes_and_public_trace_agree():
    assert importlib.metadata.version("kiwipiepy") == "0.24.1"
    assert importlib.metadata.version("kiwipiepy_model") == "0.24.0"
    assert str(_get_kiwi().model_type) == "cong"
    source = json.loads((STAGE / "tests/fixtures/round23_owned_lexical_analysis.json").read_text(encoding="utf-8"))
    recorded = []
    for row in source["cases"]:
        text = row["text"]
        actual = KiwiAnalyzer().analyze_components(text)
        actual_rows = [asdict(token) for token in actual]
        # 추가 성분 소유 범위는 별도 검사에서 확인하며 기존 관측 필드는 엄격히 보존한다.
        for token in actual_rows:
            token.pop("morpheme_spans", None)
        assert json.loads(json.dumps(actual_rows)) == row["tokens"]
        result = engine.pronounce((segment(text),))
        assert result.text == G2P()(text)
        if text.startswith("문자 메시지") or text == "문자메시지" or text == "문자는 기호다":
            assert affected(result) == [("ko.lexical.tensing", 1)]
        elif text.startswith("일산동구"):
            assert affected(result) == [("ko.sino.tensing.26", 1)]
        recorded.append({"text": text, "tokens": row["tokens"], "actual": result.text,
                         "owned_rules": affected(result)})


def test_fact_metadata_contains_no_full_pronunciations_or_place_override():
    text_root, place_root = OWNED_LEXICAL_ROOTS
    assert text_root.tense_boundaries == (1,)
    assert text_root.expected_onsets == ((1, "ㅈ"),)
    assert place_root.hanja == "一山"
    assert place_root.tense_boundaries == ()
    assert place_root.expected_onsets == ()
    assert all(len(root.hanja) == len(root.spelling) for root in OWNED_LEXICAL_ROOTS)


def test_part_specific_origins_do_not_include_outer_suffix():
    text = "일산동구"
    annotation = _Annotation.from_tokens((AnalysisToken(text, "NNP", 0, 4),), text)
    matches = tuple(owned_root_matches(text, annotation, nominal_tail_validator=_has_licensed_nominal_tail))
    assert [(m.start, m.end, m.owner_start, m.owner_end, m.root.hanja) for m in matches] == [(0, 2, 0, 4, "一山")]
    result = run(text, [(text, "NNP", 0, 4)])
    assert affected(result) == [("ko.sino.tensing.26", 1)]
    assert result.text[2] == "동"


def test_declarative_test_local_roots_use_shared_rules_without_string_branches():
    from dataclasses import replace
    from g2p_ko.korean import owned_lexical
    root = replace(OWNED_LEXICAL_ROOTS[1], identity="합성검사", spelling="월성", hanja="月城",
                   parts=(("월", "NNG"), ("성", "NNG")))
    composition = replace(owned_lexical.OWNED_COMPOSITIONS[1], parts=(
        replace(owned_lexical.OWNED_COMPOSITIONS[1].parts[0], spelling="월성", root_identity="합성검사",
                split=(("월", frozenset({"NNG"})), ("성", frozenset({"NNG"})))),
        owned_lexical.OWNED_COMPOSITIONS[1].parts[1],
    ))
    # 실제 지명 발음 주장이 아닌 소유 범위와 일반 ㄹ+ㅅ 규칙의 합성 대조다.
    with patch.object(owned_lexical, "OWNED_LEXICAL_ROOTS", (root,)), patch.object(
        owned_lexical, "OWNED_COMPOSITIONS", (composition,),
    ):
        result = run("월성동구", [("월성동구", "NNP", 0, 4)])
    assert affected(result) == [("ko.sino.tensing.26", 1)]


@pytest.mark.parametrize("label", ("이름", "인명", "사람"))
def test_explicit_competing_identity_must_block_default_even_with_nng(label):
    # 실제 분석기가 NNP를 주는 경우만으로 의미 소유권 검증을 대신할 수 없다.
    text = "문자는 " + label + "이다"
    end = 4 + len(label)
    rows = [("문자", "NNG", 0, 2), ("는", "JX", 2, 3), (label, "NNG", 4, end),
            ("이", "VCP", end, end + 1), ("다", "EF", end + 1, end + 2)]
    assert affected(run(text, rows)) == []
