"""정상 형태소를 공급하여 파생 문법 역할과 원자 한자 신원만 검증한다."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

STAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE / "src"))

from g2p_ko import G2P, ReadingBoundary
from g2p_ko.korean import engine
from g2p_ko.korean.morphology import _Annotation, _has_licensed_nominal_tail
from g2p_ko.korean.owned_lexical import owned_root_matches, OWNED_NOMINAL_ORIGIN_ROOTS
from g2p_ko.model import AnalysisToken as T, Boundary, Handler, OutputSegment, SourceSpan


def supplied(text, rows, *, relation="ordinary_liaison", pause=(), hard=None, protected=False):
    """정확한 전체 입력의 공급 분석만 소비하고 분석기 실호출을 금지한다."""
    tokens = tuple(T(*row) for row in rows)
    calls = []
    captured = []
    original = engine.pronounce

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    class Analyzer:
        def analyze(self, source):
            calls.append(source)
            start = text.index(source)
            end = start + len(source)
            return tuple(T(t.form, t.tag, t.normalized_start-start, t.normalized_end-start, t.morphemes)
                         for t in tokens if start <= t.normalized_start and t.normalized_end <= end)

    def segment(start, end, *, before=Boundary.WORD):
        return OutputSegment(text[start:end], tuple(SourceSpan.from_source(text, i, i+1) for i in range(start, end)),
                             Handler.PROTECTED if protected and start else Handler.KOREAN,
                             "파생어 집중검사", boundary_before=before)

    with patch.object(engine, "KiwiAnalyzer", Analyzer), patch(
        "g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("새 분석기 실험은 허용하지 않는다."),
    ), patch("g2p_ko.pipeline.pronounce", observed):
        if hard is None and not protected:
            conditions = [] if relation is None else [ReadingBoundary(text.index(" ")+1, relation)]
            result = G2P().convert_with_reading_conditions(text, reading_conditions=conditions, pause_boundaries=pause)
            for rewrite in captured[0].rewrites:
                assert all(text[span.start:span.end] == span.surface for span in rewrite.source_spans)
            return SimpleNamespace(aligned=result.aligned, boundary_executions=result.boundary_executions,
                                   rewrites=captured[0].rewrites), calls
        split = hard if hard is not None else protected if type(protected) is int else text.index(" ")+1
        parts = (segment(0, split), segment(split, len(text), before=Boundary.HARD if hard else Boundary.WORD))
        return engine.pronounce(parts, pause_boundaries=pause), calls


def liaison(result):
    return [rewrite for rewrite in result.rewrites if rewrite.rule_id == "ko.liaison.lexical"]


@pytest.mark.parametrize("word,parts", [
    ("어지간히", (("어지간", "XR"), ("히", "XSM"))),
    ("엄숙히", (("엄숙", "XR"), ("히", "XSM"))),
    ("어렴풋이", (("어렴풋", "XR"), ("이", "XSM"))),
    ("온전하게", (("온전", "XR"), ("하", "XSA"), ("게", "EC"))),
    ("아른거리다", (("아른", "XR"), ("거리", "XSV"), ("다", "EF"))),
    ("어른스럽다", (("어른", "NNG"), ("스럽", "XSA-I"), ("다", "EF"))),
    ("익숙하다", (("익숙", "XR"), ("하", "XSA-R"), ("다", "EF"))),
    ("어른들", (("어른", "NNG"), ("들", "XSN"))),
    ("어지간함", (("어지간", "XR"), ("함", "XSN"))),
])
@pytest.mark.parametrize("merged", [False, True])
def test_exact_derivation_drives_real_liaison_and_same_public_applicability(word, parts, merged):
    assert "".join(form for form, _ in parts) == word
    text = "옷 " + word
    if merged:
        rows = [("옷", "NNG", 0, 1), (word, "+".join(tag for _, tag in parts), 2, len(text), parts)]
    else:
        rows, cursor = [("옷", "NNG", 0, 1)], 2
        for form, tag in parts:
            rows.append((form, tag, cursor, cursor+len(form)))
            cursor += len(form)
    result, calls = supplied(text, rows)
    execution, = result.boundary_executions
    assert calls == [text]
    assert result.aligned.result.surface_pronunciation.startswith("오 " + {"어":"더", "엄":"덤", "온":"돈", "아":"다", "익":"딕"}[word[0]])
    assert (execution.applicability, execution.sound_effect) == ("eligible", "changed")
    assert "ko.liaison.lexical" in execution.rule_ids
    assert liaison(result)
    target = result.aligned.alignment.extract_target(2, len(text))
    assert target.pronunciation == result.aligned.result.surface_pronunciation[2:]


def test_default_non_y_liaison_also_uses_the_same_derived_role():
    text = "옷 어지간히"
    rows = [("옷", "NNG", 0, 1), ("어지간", "XR", 2, 5), ("히", "XSM", 5, 6)]
    result, _ = supplied(text, rows, relation=None)
    assert result.aligned.result.surface_pronunciation == "오 더지간히"
    assert liaison(result)


@pytest.mark.parametrize("rows,applicability", [
    ([("어지간히", "XR", 2, 6)], "ineligible"),
    ([("어지간", "XR", 2, 5), ("히", "UNKNOWN", 5, 6)], "unknown"),
    ([("어지간", "XR", 2, 5), ("히", "XSM-X", 5, 6)], "unknown"),
    ([("어지간", "XR", 2, 5), ("히", "XSN+XSM", 5, 6)], "unknown"),
    ([("어지간", "XR", 2, 5), ("히", "XSM", 5, 6, (("이", "XSM"),))], "unknown"),
    ([("어지간히", "XR+XSM", 2, 6, (("어지간", "XR"), ("이", "XSM")))], "unknown"),
    ([("어지간히", "XR+XSM", 2, 6, (("어지간", "XR"), ("히", "ZZ")))], "unknown"),
])
def test_unsupported_or_forged_derivation_does_not_create_eligibility(rows, applicability):
    result, _ = supplied("옷 어지간히", [("옷", "NNG", 0, 1), *rows])
    # 독립 어기가 아닌 XR과, 근거가 부족하거나 충돌한 분석을 구분한다.
    assert result.boundary_executions[0].applicability == applicability
    assert not liaison(result)


@pytest.mark.parametrize("text,rows,applicability", [
    ("옷 어지간 히", [("옷", "NNG", 0, 1), ("어지간", "XR", 2, 5), ("히", "XSM", 6, 7)], "ineligible"),
    ("옷 어지간히사람", [("옷", "NNG", 0, 1), ("어지간", "XR", 2, 5), ("히", "XSM", 5, 6), ("사람", "NNG", 6, 8)], "unknown"),
])
def test_suffix_from_another_word_or_unlicensed_attached_word_is_rejected(text, rows, applicability):
    result, _ = supplied(text, rows)
    assert result.boundary_executions[0].applicability == applicability
    assert not liaison(result)


@pytest.mark.parametrize("cut", [2, 3, 5])
def test_internal_pause_blocks_new_word_proof(cut):
    rows = [("옷", "NNG", 0, 1), ("어지간", "XR", 2, 5), ("히", "XSM", 5, 6)]
    relation = None if cut == 2 else "ordinary_liaison"
    result, _ = supplied("옷 어지간히", rows, relation=relation, pause=(cut,))
    assert not liaison(result)
    if relation:
        # 요청 pair 바깥의 내부 휴지는 단어 전체 근거를 미확정으로 만든다.
        assert result.boundary_executions[0].applicability == "unknown"


@pytest.mark.parametrize("hard,protected", [(5, False), (2, False), (None, True), (None, 5)])
def test_hard_and_protected_barriers_block_new_derivation(hard, protected):
    rows = [("옷", "NNG", 0, 1), ("어지간", "XR", 2, 5), ("히", "XSM", 5, 6)]
    result, _ = supplied("옷 어지간히", rows, relation=None, hard=hard, protected=protected)
    assert "ko.liaison.lexical" not in {r.rule_id for r in result.rewrites}


def test_verified_derived_word_uses_the_selected_liaison_recipe():
    rows = [("옷", "NNG", 0, 1), ("익숙", "XR", 2, 4), ("히", "XSM", 4, 5)]
    ordinary, _ = supplied("옷 익숙히", rows)
    grouped, _ = supplied("옷 익숙히", rows, relation="one_madi")
    assert ordinary.aligned.result.surface_pronunciation.startswith("오 딕")
    assert ordinary.boundary_executions[0].applicability == "eligible"
    assert "ko.n_insertion.word" not in ordinary.boundary_executions[0].rule_ids
    # 정확한 파생열과 호출자의 이어 읽기 선택을 함께 소비한다.
    execution = grouped.boundary_executions[0]
    assert execution.applicability == "eligible"
    assert "ko.n_insertion.word" in execution.rule_ids
    assert (execution.status, execution.reason) == ("selected", "caller_selected_recipe")
    assert execution.source_prosody_observed is False


@pytest.mark.parametrize("parts", [
    (("출제", "NNG", 0, 2),),
    (("출", "NNG", 0, 1), ("제", "NNG", 1, 2)),
    (("출제", "NNG", 0, 2, (("출", "NNG"), ("제", "NNG"))),),
])
@pytest.mark.parametrize("tail,tail_rows", [
    ("", ()), ("도", (("도", "JX", 2, 3),)),
    ("적", (("적", "XSN", 2, 3),)),
    ("적으로", (("적", "XSN", 2, 3), ("으로", "JKB", 3, 5))),
    ("들", (("들", "XSN", 2, 3),)),
    ("이다", (("이", "VCP", 2, 3), ("다", "EF", 3, 4))),
])
def test_atomic_nominal_origin_uses_general_tensing_and_existing_inheritance(parts, tail, tail_rows):
    text = "출제" + tail
    result, _ = supplied(text, [*parts, *tail_rows], relation=None)
    assert result.aligned.result.surface_pronunciation.startswith("출쩨")
    rules = {r.rule_id for r in result.rewrites}
    assert "ko.sino.tensing.26" in rules
    assert not rules & {"ko.lexical.verified", "ko.official.morpheme"}


@pytest.mark.parametrize("text,rows", [
    ("출제", [("출제", "NNP", 0, 2)]),
    ("출제", [("출제", "NNG", 0, 2, (("출제", "VV"),))]),
    ("출제", [("출", "NNG", 0, 1), ("제", "NNB", 1, 2)]),
    ("가출제", [("가", "NNG", 0, 1), ("출제", "NNG", 1, 3)]),
    ("출제님", [("출제", "NNG", 0, 2), ("님", "XSN", 2, 3)]),
    ("출제화", [("출제", "NNG", 0, 2), ("화", "XSN", 2, 3)]),
    ("출제는 이름이다", [("출제", "NNG", 0, 2), ("는", "JX", 2, 3), ("이름", "NNG", 4, 6), ("이", "VCP", 6, 7), ("다", "EF", 7, 8)]),
    ("출제는 사람이다", [("출제", "NNG", 0, 2), ("는", "JX", 2, 3), ("사람", "NNG", 4, 6), ("이", "VCP", 6, 7), ("다", "EF", 7, 8)]),
    ("그의 이름은 출제이다", [("그", "NP", 0, 1), ("의", "JKG", 1, 2), ("이름", "NNG", 3, 5), ("은", "JX", 5, 6), ("출제", "NNG", 7, 9), ("이", "VCP", 9, 10), ("다", "EF", 10, 11)]),
    ("불제", [("불제", "NNG", 0, 2)]),
])
def test_atomic_fact_cannot_promote_wrong_ownership_competing_identity_or_other_nouns(text, rows):
    result, _ = supplied(text, rows, relation=None)
    assert "ko.sino.tensing.26" not in {r.rule_id for r in result.rewrites}


def test_origin_metadata_contains_only_the_nominal_hanja_identity():
    root, = OWNED_NOMINAL_ORIGIN_ROOTS
    assert (root.spelling, root.hanja, root.owner_pos) == ("출제", "出題", frozenset({"NNG"}))
    assert root.tense_boundaries == root.expected_onsets == ()
    annotation = _Annotation.from_tokens((T("출제", "NNG", 0, 2),), "출제")
    matches = tuple(owned_root_matches("출제", annotation, nominal_tail_validator=_has_licensed_nominal_tail))
    assert [(m.start, m.end, m.root.hanja) for m in matches] == [(0, 2, "出題")]


def test_another_name_value_does_not_become_this_roots_competing_identity():
    text = "출제의 이름은 바람이다"
    rows = [("출제", "NNG", 0, 2), ("의", "JKG", 2, 3), ("이름", "NNG", 4, 6),
            ("은", "JX", 6, 7), ("바람", "NNG", 8, 10), ("이", "VCP", 10, 11), ("다", "EF", 11, 12)]
    result, _ = supplied(text, rows, relation=None)
    assert result.aligned.result.surface_pronunciation.startswith("출쩨")


@pytest.mark.parametrize("pause,hard", [((1,), None), ((), 1)])
def test_atomic_origin_does_not_cross_internal_pause_or_hard(pause, hard):
    rows = [("출", "NNG", 0, 1), ("제", "NNG", 1, 2)]
    result, _ = supplied("출제", rows, relation=None, pause=pause, hard=hard)
    rewrites = result.rewrites
    assert "ko.sino.tensing.26" not in {r.rule_id for r in rewrites}


def test_unknown_analysis_keeps_public_execution_unknown():
    class Unavailable:
        def analyze(self, source):
            raise RuntimeError("공급 분석 실패")
    with patch.object(engine, "KiwiAnalyzer", Unavailable):
        result = G2P().convert_with_reading_conditions(
            "옷 어지간히", reading_conditions=[ReadingBoundary(2, "ordinary_liaison")],
        )
    assert (result.boundary_executions[0].status, result.boundary_executions[0].applicability) == ("unknown", "unknown")
    assert not result.aligned.result.complete
