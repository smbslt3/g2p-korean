"""정확 소유 공통 계약과 소비자별 명시적 재사용 정책을 검사한다."""
from dataclasses import dataclass
import importlib.metadata

import pytest

from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.korean import engine
from g2p_ko.korean.lexicon import LEXICAL_STRUCTURES, LexicalStructure
from g2p_ko.korean.morphology import _valid_exact_structure_owner
from g2p_ko.korean.palatalization_policy import PalatalizationBoundary
from g2p_ko.model import AnalysisToken, Handler, OutputSegment, SourceSpan


@dataclass(frozen=True)
class _MinimalOwner:
    """공통 계약에는 특정 소비자의 재사용 필드가 필요하지 않다."""

    spelling: str
    owner_pos: frozenset[str]


def _structure(kind):
    if kind == "lexical":
        return LexicalStructure((("가나", "NNG"), ("다라", "NNG")), owner_pos=frozenset({"NNG", "NNP"}))
    if kind == "palatalization":
        return PalatalizationBoundary("가나다라", 2, "exact", frozenset({"NNG", "NNP"}))
    return _MinimalOwner("가나다라", frozenset({"NNG", "NNP"}))


@pytest.mark.parametrize("kind", ("lexical", "palatalization", "minimal"))
@pytest.mark.parametrize("rows", (
    (("가나다라", "NNG", 0, 4),),
    (("가나다라", "NNP", 0, 4),),
    (("가나", "NNG", 0, 2), ("다라", "NNG", 2, 4)),
))
def test_common_contract_accepts_exact_truthful_nominal_owners(kind, rows):
    structure = _structure(kind)
    if kind != "lexical":
        assert not hasattr(structure, "allow_owned_composition")
    assert _valid_exact_structure_owner("가나다라", 0, 4, structure, tuple(AnalysisToken(*row) for row in rows))


@pytest.mark.parametrize("kind", ("lexical", "palatalization", "minimal"))
@pytest.mark.parametrize("rows", (
    (("가나다라", "VV", 0, 4),),
    (("가나다라", "NNG+JKS", 0, 4),),
    (("가나다라", "NNG", 0, 4, (("가나", "VV"), ("다라", "NNG"))),),
    (("가나다라", "NNG", 0, 4, (("가나", "NNG"),)),),
    (("가나마라", "NNG", 0, 4),),
    (("가나", "NNG", 0, 2), ("라", "NNG", 3, 4)),
    (("가나다", "NNG", 0, 3), ("다라", "NNG", 2, 4)),
    (("가나", "NNP", 0, 2), ("다라", "NNG", 2, 4)),
    (("다라", "NNG", 2, 4), ("가나", "NNG", 0, 2)),
    (("가나", "NNG", 0, 2),),
))
def test_common_contract_rejects_forged_partial_overlapping_and_unsupported_owners(kind, rows):
    assert not _valid_exact_structure_owner("가나다라", 0, 4, _structure(kind), tuple(AnalysisToken(*row) for row in rows))


@pytest.mark.parametrize("kind", ("lexical", "palatalization", "minimal"))
def test_default_rejects_nominal_neighbors_and_exact_owner_still_accepts_particles(kind):
    structure = _structure(kind)
    for text, start, rows in (
        ("앞가나다라", 1, (("앞", "NNG", 0, 1), ("가나다라", "NNG", 1, 5))),
        ("가나다라집", 0, (("가나다라", "NNG", 0, 4), ("집", "NNG", 4, 5))),
    ):
        assert not _valid_exact_structure_owner(text, start, start + 4, structure, tuple(AnalysisToken(*row) for row in rows))
    assert _valid_exact_structure_owner("가나다라가", 0, 4, structure, (
        AnalysisToken("가나다라", "NNG", 0, 4), AnalysisToken("가", "JKS", 4, 5),
    ))


def test_lexical_metadata_is_passed_only_by_the_explicit_consumer_policy():
    structure = LEXICAL_STRUCTURES["글자"]
    rows = (AnalysisToken("표", "NNG", 0, 1), AnalysisToken("글자", "NNP", 1, 3))
    assert structure.allow_owned_composition is True
    assert not _valid_exact_structure_owner("표글자", 1, 3, structure, rows)
    assert _valid_exact_structure_owner("표글자", 1, 3, structure, rows, allow_owned_composition=True)
    assert not _valid_exact_structure_owner("표글자", 1, 3, structure, (
        AnalysisToken("표글자", "NNG", 0, 3),
    ), allow_owned_composition=True)
    assert not _valid_exact_structure_owner("표글자", 1, 3, structure, rows, allow_owned_composition=1)


@pytest.mark.parametrize("option", (1, "yes", None))
def test_lexical_reuse_schema_rejects_non_boolean_policy(option):
    with pytest.raises(ValueError):
        LexicalStructure((("가", "NNG"), ("나", "NNG")), owner_pos=frozenset({"NNG"}), allow_owned_composition=option)


def test_lexical_reuse_schema_requires_explicit_owner_and_valid_component_boundaries():
    for kwargs in (
        {"allow_owned_composition": True},
        {"owner_pos": frozenset({"VV"}), "allow_owned_composition": True},
        {"owner_pos": frozenset({"NNG"}), "tense_boundaries": (2,)},
        {"owner_pos": frozenset({"NNG"}), "tense_boundaries": (True,)},
        {"owner_pos": frozenset({"NNG"}), "tense_boundaries": (1, 1)},
    ):
        with pytest.raises(ValueError):
            LexicalStructure((("가", "NNG"), ("나", "NNG")), **kwargs)
    assert LexicalStructure((("가", "NNG"), ("나", "NNG"))).allow_owned_composition is False


@pytest.mark.parametrize("scope,owner", (("exact", frozenset()), ("exact", frozenset({"VV"})), ("prefix", frozenset({"NNG"})), ("suffix", frozenset({"NNG"}))))
def test_palatalization_schema_keeps_its_own_exact_prefix_suffix_contract(scope, owner):
    with pytest.raises(ValueError):
        PalatalizationBoundary("가나", 1, scope, owner)


@pytest.mark.parametrize("word,expected", (("글자", "글짜"), ("땅바닥", "땅빠닥")))
def test_real_pinned_kiwi_uses_declarative_lexical_boundary(word, expected):
    assert importlib.metadata.version("kiwipiepy") == "0.24.1"
    assert importlib.metadata.version("kiwipiepy_model") == "0.24.0"
    assert KiwiAnalyzer().analyze_components(word)
    segment = OutputSegment(word, (SourceSpan.from_source(word, 0, len(word)),), Handler.KOREAN, "고정분석기검사")
    result = engine.pronounce((segment,))
    assert result.text == expected
    rewrite = next(item for item in result.rewrites if item.rule_id == "ko.lexical.tensing")
    assert tuple(span.start for span in rewrite.source_spans) == (0, 1)
    assert LEXICAL_STRUCTURES[word].tense_boundaries == (1,)


def test_only_two_retained_facts_opt_into_owned_composition():
    assert {word for word, structure in LEXICAL_STRUCTURES.items() if structure.allow_owned_composition} == {"글자", "땅바닥"}
