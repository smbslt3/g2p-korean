from __future__ import annotations

from pathlib import Path
import importlib.metadata
import sys

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean import engine
from g2p_ko.korean.lexicon import LEXICAL_STRUCTURES, LexicalStructure
from g2p_ko.korean.morphology import _Annotation, _expand_lexical_structures
from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan


FULL_FORMS = ("형성평가", "총괄평가", "수행평가", "진단평가")


def _segment(text: str, start: int = 0, *, before=Boundary.WORD, after=Boundary.WORD):
    span = SourceSpan(start, start + len(text), text, max(4, start + len(text)))
    return OutputSegment(
        text, (span,), Handler.KOREAN, "composition-test",
        boundary_before=before, boundary_after=after,
    )


def _fixture_tokens(text: str, full: str, mode: str):
    prefix = full[:-2]
    if mode == "split":
        tokens = [
            AnalysisToken(prefix, "NNG", 0, 2, ((prefix, "NNG"),)),
            AnalysisToken("평가", "NNG", 2, 4, (("평가", "NNG"),)),
        ]
    elif mode == "whole_nng":
        tokens = [AnalysisToken(full, "NNG", 0, 4, ((full, "NNG"),))]
    elif mode == "whole_nnp":
        tokens = [AnalysisToken(full, "NNP", 0, 4, ((full, "NNP"),))]
    elif mode == "forged_particle":
        tokens = [AnalysisToken(full, "NNG+JKS", 0, 4, ((full, "NNG+JKS"),))]
    elif mode == "forged_predicate":
        tokens = [AnalysisToken(full, "VV", 0, 4, ((full, "VV"),))]
    elif mode == "longer_whole":
        tokens = [AnalysisToken(text, "NNG", 0, len(text), ((text, "NNG"),))]
    elif mode == "longer_split":
        tokens = [
            AnalysisToken(prefix, "NNG", 0, 2, ((prefix, "NNG"),)),
            AnalysisToken("평가", "NNG", 2, 4, (("평가", "NNG"),)),
            AnalysisToken("집", "NNG", 4, 5, (("집", "NNG"),)),
        ]
    else:
        raise AssertionError(mode)
    if text.endswith("가") and len(text) == 5 and mode not in {"forged_particle"}:
        tokens.append(AnalysisToken("가", "JKS", 4, 5, (("가", "JKS"),)))
    return tuple(tokens)


def _pronounce_with_tokens(monkeypatch, text: str, full: str, mode: str, pauses=()):
    tokens = _fixture_tokens(text, full, mode)

    class FixedAnalyzer:
        def analyze_components(self, island):
            assert island == text
            return tokens

        def analyze(self, island):
            return self.analyze_components(island)

    monkeypatch.setattr(engine, "KiwiAnalyzer", FixedAnalyzer)
    return engine.pronounce((_segment(text),), pause_boundaries=pauses).text


def test_real_kiwi_versions_and_latest_split_whole_shapes():
    assert importlib.metadata.version("kiwipiepy") == "0.24.1"
    assert importlib.metadata.version("kiwipiepy_model") == "0.24.0"
    assert importlib.metadata.version("pytest") == "8.4.2"
    analyzer = KiwiAnalyzer()
    split = analyzer.analyze_components("형성평가")
    whole = analyzer.analyze_components("총괄평가")
    assert [(item.form, item.tag) for item in split] == [("형성", "NNG"), ("평가", "NNG")]
    assert [(item.form, item.tag) for item in whole] == [("총괄평가", "NNP")]
    assert {
        spelling for spelling, structure in LEXICAL_STRUCTURES.items()
        if structure.owner_pos
    } == set(FULL_FORMS) | {"글자", "땅바닥"}
    for full in FULL_FORMS:
        assert engine.pronounce((_segment(full),)).text == full[:-2] + "평까"


@pytest.mark.parametrize("full", FULL_FORMS)
@pytest.mark.parametrize("mode", ("split", "whole_nng", "whole_nnp"))
@pytest.mark.parametrize("particle", (False, True))
def test_four_exact_full_compounds_accept_declared_owner_shapes_and_particles(
    monkeypatch, full, mode, particle,
):
    text = full + ("가" if particle else "")
    result = _pronounce_with_tokens(monkeypatch, text, full, mode)
    expected = full[:-2] + "평까" + ("가" if particle else "")
    assert result == expected


@pytest.mark.parametrize("mode", ("longer_whole", "longer_split"))
def test_longer_nominal_owner_and_adjacent_nominal_fragments_are_rejected(monkeypatch, mode):
    text = "형성평가집"
    assert _pronounce_with_tokens(monkeypatch, text, "형성평가", mode) == text


@pytest.mark.parametrize("mode", ("forged_particle", "forged_predicate"))
def test_particle_and_predicate_tags_cannot_masquerade_as_nominal_owners(monkeypatch, mode):
    text = "형성평가"
    assert _pronounce_with_tokens(monkeypatch, text, "형성평가", mode) == text


def test_whitespace_quote_and_hard_boundary_do_not_form_an_owner():
    structure = LEXICAL_STRUCTURES["형성평가"]
    fixtures = (
        (
            "형성 평가",
            (AnalysisToken("형성", "NNG", 0, 2), AnalysisToken("평가", "NNG", 3, 5)),
        ),
        (
            "형성“평가”",
            (AnalysisToken("형성", "NNG", 0, 2), AnalysisToken("평가", "NNG", 3, 5)),
        ),
    )
    for text, tokens in fixtures:
        segments = (_segment(text),)
        units = engine._build_units(segments, trace=True)
        expanded, matches = _expand_lexical_structures(
            text, units, segments, _Annotation.from_tokens(tokens, text),
        )
        assert not matches
        assert tuple(expanded._tokens_starting_at.values()) == tokens

    text = "형성평가"
    segments = (
        _segment("형성", 0, after=Boundary.HARD),
        _segment("평가", 2, before=Boundary.HARD),
    )
    tokens = (
        AnalysisToken("형성", "NNG", 0, 2, (("형성", "NNG"),)),
        AnalysisToken("평가", "NNG", 2, 4, (("평가", "NNG"),)),
    )
    units = engine._build_units(segments, trace=True)
    expanded, matches = _expand_lexical_structures(
        text, units, segments, _Annotation.from_tokens(tokens, text),
    )
    assert not matches
    assert [(item.form, item.tag) for item in expanded._tokens_starting_at.values()] == [
        ("형성", "NNG"), ("평가", "NNG"),
    ]


def test_pause_keeps_the_full_owner_and_only_blocks_the_crossed_tensing():
    text = "형성평가"
    assert engine.pronounce((_segment(text),), pause_boundaries=(2,)).text == "형성평까"
    assert engine.pronounce((_segment(text),), pause_boundaries=(3,)).text == text


def test_owner_guard_is_opt_in_for_other_mixed_pos_structures():
    text = "서울역"
    units = engine._build_units((_segment(text),), trace=True)
    mixed = (
        AnalysisToken("서울", "NNP", 0, 2, (("서울", "NNP"),)),
        AnalysisToken("역", "NNG", 2, 3, (("역", "NNG"),)),
    )
    expanded, matches = _expand_lexical_structures(
        text, units, (_segment(text),), _Annotation.from_tokens(mixed, text),
    )
    assert matches
    assert [(item.form, item.tag) for item in expanded._tokens_starting_at.values()] == [
        ("서울", "NNP"), ("역", "NNG"),
    ]


def test_test_local_structure_uses_the_same_exact_owner_metadata_contract():
    text = "가나다라마"
    structure = LexicalStructure(
        (("가나", "NNG"), ("다", "NNG"), ("라마", "NNG")),
        (2,),
        owner_pos=frozenset({"NNG"}),
    )
    units = engine._build_units((_segment(text),), trace=True)
    valid = _Annotation.from_tokens(
        (AnalysisToken(text, "NNG", 0, len(text), ((text, "NNG"),)),), text,
    )
    expanded, matches = _expand_lexical_structures(
        text, units, (_segment(text),), valid, ((0, structure),),
    )
    assert matches and len(expanded._tokens_starting_at) == 3

    longer_text = "앞" + text
    longer_segment = _segment(longer_text)
    longer_units = engine._build_units((longer_segment,), trace=True)
    longer = _Annotation.from_tokens(
        (
            AnalysisToken("앞", "NNG", 0, 1, (("앞", "NNG"),)),
            AnalysisToken(text, "NNG", 1, 6, ((text, "NNG"),)),
        ),
        longer_text,
    )
    unchanged, longer_matches = _expand_lexical_structures(
        longer_text, longer_units, (longer_segment,), longer, ((1, structure),),
    )
    assert not longer_matches
    assert [(item.form, item.tag) for item in unchanged._tokens_starting_at.values()] == [
        ("앞", "NNG"), (text, "NNG"),
    ]
