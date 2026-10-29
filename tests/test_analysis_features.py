"""문맥 판정에 필요한 기본형 정보와 형태소 좌표의 보존을 검사한다."""

import pytest

from g2p_ko.analysis_features import align_morphemes
from g2p_ko.analyzer import KiwiAnalyzer
from g2p_ko.model import AnalysisToken


def test_real_contracted_predicate_keeps_canonical_parts():
    tokens = KiwiAnalyzer().analyze_components("잠자리를 폈다.")
    contracted = next(token for token in tokens if token.form == "폈")
    assert contracted.morphemes == (("펴", "VV"), ("었", "EP"))
    assert contracted.tag == "VV+EP"
    assert (contracted.normalized_start, contracted.normalized_end) == (5, 6)


def test_raw_part_assignment_is_translation_invariant():
    raw = (("펴", "VV", 0, 1), ("었", "EP", 0, 1), ("다", "EF", 1, 1))
    expected = ((('펴', 'VV'), ('었', 'EP')), (('다', 'EF'),))
    assert align_morphemes(raw, ((0, 1), (1, 2))) == expected
    moved = tuple((form, tag, start + 17, length) for form, tag, start, length in raw)
    assert align_morphemes(moved, ((17, 18), (18, 19))) == expected


def test_zero_length_part_at_a_boundary_does_not_leak_to_previous_token():
    raw = (("가", "VV", 0, 1), ("이", "VCP", 1, 0), ("라고", "EC", 1, 2))
    assert align_morphemes(raw, ((0, 1), (1, 3))) == (
        (("가", "VV"),), (("이", "VCP"), ("라고", "EC")),
    )


def test_crossing_raw_part_cannot_assign_one_lemma_to_two_tokens():
    with pytest.raises(ValueError):
        align_morphemes((("펴", "VV", 0, 3),), ((0, 1), (2, 3)))


def test_missing_canonical_metadata_is_not_guessed_from_surface():
    assert align_morphemes(((None, "VV+EP", 0, 1),), ((0, 1),)) == ((),)


def test_analysis_token_metadata_is_immutable_and_preserves_duplicates():
    original = [["하", "VV"], ["하", "VV"]]
    token = AnalysisToken("하", "VV+VV", 0, 1, original)
    original[0][0] = "가"
    assert token.morphemes == (("하", "VV"), ("하", "VV"))
    assert token.to_dict()["morphemes"] == [["하", "VV"], ["하", "VV"]]


@pytest.mark.parametrize("metadata", ["펴/VV", (("펴",),), (("", "VV"),), (("펴", None),)])
def test_invalid_metadata_cannot_enter_an_analysis_token(metadata):
    with pytest.raises(ValueError):
        AnalysisToken("폈", "VV+EP", 0, 1, metadata)
