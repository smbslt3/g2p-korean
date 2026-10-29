"""등록 전체 결합의 내부 유래와 분석 실패 진단을 제공 분석으로 검증한다.

합성 어휘는 일반 소비 계약 검사이며 규범 발음 정답이 아니다.
"""

from unittest.mock import patch

import pytest

from g2p_ko.korean import engine, owned_lexical as owned
from g2p_ko.korean.morphology import _Annotation, _has_licensed_nominal_tail
from g2p_ko.model import AnalysisToken as T, Handler, OutputSegment, SourceSpan


RAW_RESULTS = {}
COMMON = frozenset({"NNG"})
SUFFIX_PARTS = (("라미", "NNG"), ("소", "XSN"), ("상자", "NNG"))
COMPOUND_PARTS = (("누", "NNG"), ("다게", "NNG"), ("상자", "NNG"))


def _whole(identifier, *, tag="NNG", origin=(), active=True, word="라미소상자"):
    return dict(id=identifier, text=word, rows=((word, tag, 0, len(word), origin),),
                spelling="누다게" if word.startswith("누다게") else "라미소",
                expected_attribute=active, expected_analyzer_failed=False)


def _split(identifier, parts, *, active=True, text="라미소상자"):
    rows, cursor = [], 0
    for form, tag in parts:
        start = text.index(form, cursor)
        cursor = start + len(form)
        rows.append((form, tag, start, cursor))
    return dict(id=identifier, text=text, rows=tuple(rows),
                spelling="라미소", expected_attribute=active, expected_analyzer_failed=False)


CASES = [
    _whole("composition_whole_without_origin"),
    _whole("composition_whole_singleton_origin", origin=(("라미소상자", "NNG"),)),
    _whole("composition_correct_detailed_origin", origin=SUFFIX_PARTS),
    _whole("composition_wrong_all_nng_origin", origin=(("라미", "NNG"), ("소", "NNG"), ("상자", "NNG")), active=False),
    _whole("composition_wrong_root_component_pos", origin=(("라미", "NNP"), ("소", "XSN"), ("상자", "NNG")), active=False),
    _whole("composition_wrong_outer_owner_pos", tag="NNP", origin=SUFFIX_PARTS, active=False),
    _whole("composition_whole_root_origin", origin=(("라미소", "NNG"), ("상자", "NNG"))),
    _whole("composition_wrong_whole_root_pos", origin=(("라미소", "NNP"), ("상자", "NNG")), active=False),
    _whole("composition_correct_fused_tags", tag="NNG+XSN+NNG", origin=SUFFIX_PARTS),
    _whole("composition_wrong_fused_all_nng", tag="NNG+NNG+NNG", origin=(("라미", "NNG"), ("소", "NNG"), ("상자", "NNG")), active=False),
    _whole("composition_crossed_declared_boundary", origin=(("라미", "NNG"), ("소상자", "NNG")), active=False),
    _whole("composition_bad_origin_surface", origin=(("라미", "NNG"), ("서", "XSN"), ("상자", "NNG")), active=False),
    _split("composition_correct_split", SUFFIX_PARTS),
    _split("composition_wrong_split", (("라미", "NNG"), ("소", "NNG"), ("상자", "NNG")), active=False),
    _split("composition_whole_root_split", (("라미소", "NNG"), ("상자", "NNG"))),
    _split("separate_registered_root_keeps_own_fact", SUFFIX_PARTS, text="라미소 상자"),
    _whole("composition_unregistered_longer_whole", word="라미소상자통", active=False),
    _whole("compound_all_nng_is_declared", word="누다게상자", origin=COMPOUND_PARTS),
    _whole("compound_wrong_xsn_origin", word="누다게상자", origin=(("누", "NNG"), ("다게", "XSN"), ("상자", "NNG")), active=False),
    _split("composition_particle", ((*SUFFIX_PARTS, ("도", "JX"))), text="라미소상자도"),
]

for _word in ("가능성", "발가락", "발뒤꿈치"):
    for _mode in ("valid", "empty", "mismatch"):
        _rows = ((_word, "NNG", 0, len(_word)),) if _mode == "valid" else ()
        if _mode == "mismatch":
            _rows = (("다름", "NNG", 0, len(_word)),)
        CASES.append(dict(id="diagnostic_" + _word + "_" + _mode, text=_word, rows=_rows,
            spelling=_word, expected_attribute=_mode == "valid", expected_analyzer_failed=_mode != "valid"))
CASES.append(dict(id="diagnostic_unrelated_without_candidate", text="도레미", rows=(), spelling="도레미",
                  expected_attribute=False, expected_analyzer_failed=False))


def _metadata():
    """서로 다른 성분 품사 선언으로 같은 소비기의 일반성을 확인한다."""
    roots = []
    for identity, word, parts, source, target in (
        ("synthetic_declared_suffix_r35b", "라미소", (("라미", "NNG"), ("소", "XSN")), "ㅅ", "ㅆ"),
        ("synthetic_declared_compound_r35b", "누다게", (("누", "NNG"), ("다게", "NNG")), "ㄱ", "ㄲ"),
    ):
        roots.append(owned.OwnedLexicalRoot(identity, word, COMMON, ((word, "NNG"),), "", default_reading=True,
            internal_onsets=(owned.InternalOnsetConstraint(2, source, target, "lexical_syllable"),),
            component_analyses=(parts,)))
    compositions = tuple(owned.OwnedComposition((owned.OwnedPart(root.spelling, COMMON, root.identity),
                         owned.OwnedPart("상자", COMMON)), COMMON) for root in roots)
    return tuple(roots), compositions


def _run(case):
    text = case["text"]
    tokens = tuple(T(*row) for row in case["rows"])
    calls = []

    class Analyzer:
        def analyze(self, source):
            calls.append(source)
            assert source == text
            return tokens

    roots, compositions = _metadata()
    segment = OutputSegment(text, tuple(SourceSpan.from_source(text, i, i+1) for i in range(len(text))),
                            Handler.KOREAN, "등록 성분 유래 회귀 검사")
    with patch.object(owned, "OWNED_INTERNAL_ONSET_ROOTS", (*owned.OWNED_INTERNAL_ONSET_ROOTS, *roots)), \
         patch.object(owned, "OWNED_COMPOSITIONS", (*owned.OWNED_COMPOSITIONS, *compositions)), \
         patch.object(engine, "KiwiAnalyzer", Analyzer), \
         patch("g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("실제 Kiwi 호출 금지")):
        result = engine.pronounce((segment,))
        decisions = tuple(owned.owned_root_decisions(text, _Annotation.from_tokens(tokens, text),
            nominal_tail_validator=_has_licensed_nominal_tail))
    start = text.find(case["spelling"])
    offset = 1 if case["spelling"] in {"발가락", "발뒤꿈치"} else 2
    target = start + offset
    relevant = [r for r in result.rewrites if r.rule_id == "ko.lexical.tensing"
                and any(s.start <= target < s.end for s in r.source_spans)]
    record = dict(id=case["id"], text=text, expected_attribute=case["expected_attribute"],
        expected_analyzer_failed=case["expected_analyzer_failed"], pronunciation=result.text,
        actual_attribute=bool(relevant), calls=calls, rewrites=[r.to_dict() for r in result.rewrites],
        diagnostics=[d.to_dict() for d in result.diagnostics],
        decisions=[dict(root=d.match.root.identity, applies=d.applies, reason=d.identity_reason)
                   for d in decisions if d.match.root.spelling == case["spelling"]])
    RAW_RESULTS[case["id"]] = record
    return record, relevant


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_generic_component_provenance_and_truthful_diagnostics(case):
    record, relevant = _run(case)
    assert record["actual_attribute"] == case["expected_attribute"]
    assert any(d["code"] == "analyzer_failed" for d in record["diagnostics"]) == case["expected_analyzer_failed"]
    if not case["expected_analyzer_failed"]:
        assert any(d["applies"] for d in record["decisions"]) == case["expected_attribute"]
    for rewrite in relevant:
        # 유니코드 산술로 한 초성만 바뀌고 모음·종성은 유지됨을 확인한다.
        differences = [(a, b) for a, b in zip(rewrite.before, rewrite.after) if a != b]
        assert len(relevant) == len(differences) == 1
        left, right = (ord(char) - 0xAC00 for char in differences[0])
        assert 0 <= left < 11172 and 0 <= right < 11172
        assert left % 588 == right % 588
    for rewrite in record["rewrites"]:
        assert all(text_span["surface"] == case["text"][text_span["start"]:text_span["end"]]
                   for text_span in rewrite["source_spans"])
