"""출력 전 선언한 명시 읽기 조건의 구조와 최소 음운 분기를 확인한다."""
from pathlib import Path
import json
import unicodedata

import pytest

from g2p_ko import Boundary, G2P, Handler, InputValidationError, OutputSegment, ReadingBoundary, SourceSpan
from g2p_ko.korean import engine as korean_engine
from g2p_ko.reading_conditions import _MappedReadingBoundary

TRACK = Path(__file__).resolve().parent / "fixtures/round24_reading_conditions"
CASES = json.loads((TRACK / "predeclared_cases_v1.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("relation", ["ordinary_liaison", "one_madi", "pause"])
def test_predeclared_rule_family(case, relation):
    output = G2P().convert_with_reading_conditions(
        case["source"], reading_conditions=(ReadingBoundary(case["offset"], relation),),
    )
    assert output.aligned.result.surface_pronunciation == case[relation]
    execution, = output.boundary_executions
    assert execution.relation == relation
    assert execution.status == "selected"
    assert not execution.source_prosody_observed
    assert len(output.aligned.result.normalized_text) == len(output.aligned.result.surface_pronunciation)
    assert output.to_dict()["aligned"]["result"] == output.aligned.result.to_dict()


@pytest.mark.parametrize("case", CASES[:2], ids=lambda case: case["id"])
def test_same_normal_morphology_has_a_real_condition_contrast(case):
    converter = G2P()
    ordinary = converter.convert_with_reading_conditions(case["source"], reading_conditions=[ReadingBoundary(2, "ordinary_liaison")])
    grouped = converter.convert_with_reading_conditions(case["source"], reading_conditions=[ReadingBoundary(2, "one_madi")])
    assert ordinary.aligned.result.surface_pronunciation != grouped.aligned.result.surface_pronunciation
    assert "ko.liaison.lexical" in ordinary.boundary_executions[0].rule_ids
    assert "ko.n_insertion.word" in grouped.boundary_executions[0].rule_ids
    assert ordinary.boundary_executions[0].applicability == grouped.boundary_executions[0].applicability == "eligible"


def test_default_compatibility_against_separate_accepted_runtime_snapshot():
    baseline = json.loads((TRACK / "baseline_defaults.json").read_text(encoding="utf-8"))
    converter = G2P()
    for record in baseline:
        text = record["source"]
        aligned = converter.convert_with_alignment(text)
        assert converter(text) == record["result"]["surface_pronunciation"]
        assert converter.convert(text).to_dict() == record["result"]
        assert aligned.result.to_dict() == record["result"]
        assert aligned.alignment.to_dict() == record["alignment"]
        empty = converter.convert_with_reading_conditions(text)
        assert empty.aligned.result.to_dict() == record["result"]
        assert empty.aligned.alignment.to_dict() == record["alignment"]
        assert empty.boundary_executions == ()


def test_nfd_raw_edges_alignment_and_atomic_interior_rejection():
    source = unicodedata.normalize("NFD", "곰 인형")
    offset = len(unicodedata.normalize("NFD", "곰 "))
    output = G2P().convert_with_reading_conditions(source, reading_conditions=[ReadingBoundary(offset, "ordinary_liaison")])
    entry, = output.boundary_executions
    assert (entry.source_offset, entry.nfc_offset, entry.output_offset) == (offset, 2, 2)
    assert output.aligned.result.source == source
    assert output.aligned.result.surface_pronunciation == "고 민형"
    assert output.aligned.alignment.extract_target(offset, len(source)).pronunciation == "민형"
    with pytest.raises(InputValidationError):
        G2P().convert_with_reading_conditions(source, reading_conditions=[ReadingBoundary(1, "pause")])


def test_english_expansion_maps_exact_later_boundary_and_preserves_raw_alignment():
    source = "AI 곰 인형"
    offset = source.index("인")
    output = G2P().convert_with_reading_conditions(source, reading_conditions=[ReadingBoundary(offset, "ordinary_liaison")])
    entry, = output.boundary_executions
    assert (entry.source_offset, entry.nfc_offset, entry.output_offset) == (5, 5, 7)
    assert output.aligned.result.surface_pronunciation == "에이아이 고 민형"
    assert output.aligned.alignment.extract_target(5, 7).pronunciation == "민형"
    with pytest.raises(InputValidationError):
        G2P().convert_with_reading_conditions(source, reading_conditions=[ReadingBoundary(1, "pause")])


@pytest.mark.parametrize("relations", [
    [ReadingBoundary(1, "ordinary_liaison"), ReadingBoundary(3, "one_madi")],
    [ReadingBoundary(1, "pause"), ReadingBoundary(4, "ordinary_liaison")],
])
def test_aliases_in_one_space_run_conflict_before_analysis(monkeypatch, relations):
    def forbidden(*args, **kwargs):
        raise AssertionError("충돌 검증 전에 분석하면 안 됩니다.")
    monkeypatch.setattr(korean_engine.KiwiAnalyzer, "analyze_components", forbidden)
    with pytest.raises(InputValidationError):
        G2P().convert_with_reading_conditions("곰   인형", reading_conditions=relations)


def test_legacy_pause_conflict_and_same_relation_aliases():
    converter = G2P()
    with pytest.raises(InputValidationError):
        converter.convert_with_reading_conditions("곰   인형", reading_conditions=[ReadingBoundary(4, "ordinary_liaison")], pause_boundaries=[2])
    result = converter.convert_with_reading_conditions("곰   인형", reading_conditions=[ReadingBoundary(1, "ordinary_liaison"), ReadingBoundary(4, "ordinary_liaison")])
    assert result.aligned.result.surface_pronunciation == "고   민형"
    assert len(result.boundary_executions) == 2


@pytest.mark.parametrize("text,offset", [("곰인형", 1), ("곰, 인형", 3), ("곰\n인형", 2), ("곰 인형", 0)])
def test_nonpause_relations_do_not_invent_word_gaps(text, offset):
    with pytest.raises(InputValidationError):
        G2P().convert_with_reading_conditions(text, reading_conditions=[ReadingBoundary(offset, "one_madi")])


@pytest.mark.parametrize("handler,hard,reason", [
    (Handler.KOREAN, True, "hard_boundary"),
    (Handler.PROTECTED, False, "protected_or_non_korean"),
])
@pytest.mark.parametrize("relation", ["ordinary_liaison", "one_madi", "pause"])
def test_existing_hard_and_protection_always_win(handler, hard, reason, relation):
    source = "곰 인형"
    segments = (
        OutputSegment("곰", (SourceSpan.from_source(source, 0, 1),), handler, "test", boundary_after=Boundary.HARD if hard else Boundary.WORD),
        OutputSegment(" 인형", tuple(SourceSpan.from_source(source, i, i + 1) for i in range(1, 4)), Handler.KOREAN, "test"),
    )
    output = korean_engine.pronounce(segments, reading_conditions=(_MappedReadingBoundary(2, 2, 2, relation),))
    assert output.text == source
    execution, = output.condition_executions
    assert (execution.status, execution.reason) == ("blocked", reason)


def test_unknown_analysis_is_not_claimed_as_enforced(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("검증용 분석 실패")
    monkeypatch.setattr(korean_engine.KiwiAnalyzer, "analyze_components", unavailable)
    output = G2P().convert_with_reading_conditions("곰 인형", reading_conditions=[ReadingBoundary(2, "ordinary_liaison")])
    assert output.boundary_executions[0].status == "unknown"
    assert output.boundary_executions[0].applicability == "unknown"
    assert not output.aligned.result.complete


def test_selected_boundary_keeps_whole_analyzer_context(monkeypatch):
    seen = []
    original = korean_engine.KiwiAnalyzer.analyze_components
    def observed(self, source):
        seen.append(source)
        return original(self, source)
    monkeypatch.setattr(korean_engine.KiwiAnalyzer, "analyze_components", observed)
    source = "큰 곰 인형"
    G2P().convert_with_reading_conditions(source, reading_conditions=[ReadingBoundary(source.index("인"), "ordinary_liaison")])
    assert seen == [source]


def test_pause_accepts_exact_endpoints_and_intraword_control():
    converter = G2P()
    output = converter.convert_with_reading_conditions("국물", reading_conditions=[ReadingBoundary(0, "pause"), ReadingBoundary(1, "pause"), ReadingBoundary(2, "pause")])
    assert output.aligned.result.surface_pronunciation == "국물"
    assert all(entry.status == "selected" for entry in output.boundary_executions)
    assert output.boundary_executions[1].output_pair == (0, 1)


@pytest.mark.parametrize("requests", [None, "ordinary_liaison", [2], [ReadingBoundary(-1, "pause")], [ReadingBoundary(99, "pause")]])
def test_request_validation(requests):
    with pytest.raises(InputValidationError):
        G2P().convert_with_reading_conditions("곰 인형", reading_conditions=requests)


@pytest.mark.parametrize("offset,relation", [(True, "pause"), (1.0, "pause"), ("1", "pause"), (1, "no_pause"), (1, None)])
def test_boundary_validation(offset, relation):
    with pytest.raises(InputValidationError):
        ReadingBoundary(offset, relation)
