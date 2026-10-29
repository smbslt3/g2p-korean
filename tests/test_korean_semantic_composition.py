"""명사구 핵어·보조 용언·논항 소유 관계의 의미 판정을 검증한다."""

import pytest

from g2p_ko import G2P
from g2p_ko.korean.semantic_policy import select_senses
from tests.test_korean_semantic_relations import _tokens


@pytest.mark.parametrize(("text", "expected"), [
    ("잠자리의 왼쪽 날개를 폈다.", "jamjari.insect"),
    ("잠자리의 왼쪽을 살폈다.", None),
    ("잠자리의 왼쪽과 나비의 날개를 살폈다.", None),
    ("잠자리의 왼쪽을 보고 나비의 날개를 폈다.", None),
    ("날개가 찢어진 잠자리를 관찰했다.", "jamjari.insect"),
    ("날개가 찢어진 잠자리를 폈다.", None),
    ("아이가 날개를 찢은 잠자리를 관찰했다.", None),
    ("해녀가 하는 물질의 성분을 조사했다.", None),
    ("해녀가 하는 물질은 고되다.", "muljil.diving"),
    ("해녀가 물질을 했다.", "muljil.diving"),
    ("해녀가 물질했다.", "muljil.diving"),
    ("해녀가 물질의 원자를 연구했다.", "muljil.substance"),
    ("물질의 밀도를 재었다.", "muljil.substance"),
    ("물질의 특징을 기록했다.", None),
    ("잠자리의 밀도를 측정했다.", None),
    ("강가의 모래톱을 바라보았다.", "gangga.riverbank"),
    ("강가로 나갔다.", "gangga.riverbank"),
    ("강가에서 나왔다.", "gangga.riverbank"),
])
def test_actual_analysis_preserves_supported_relations_and_nontransfer(text, expected):
    # 기본 발음이 우연히 맞는 경우와 구별하여 실제 선택 또는 보류를 검사한다.
    choices = select_senses(text, _tokens(text))
    assert len(choices) == 1
    assert choices[0].sense_id == expected


@pytest.mark.parametrize("text", [
    "해녀가 하는 물질의 성분을 조사했다.",
    "해녀가 하는 물질의 염분을 기록했다.",
])
def test_activity_relative_and_material_property_are_explicitly_conflicting(text):
    choice, = select_senses(text, _tokens(text))
    assert choice.sense_id is None
    assert choice.reason == "conflicting_evidence"
    assert {e.semantic_class for e in choice.evidence} == {"activity", "substance"}


def test_physical_content_is_a_direct_property_and_not_a_word_suffix_guess():
    text = "물질의 염분을 측정했다."
    choice, = select_senses(text, _tokens(text))
    assert choice.sense_id == "muljil.substance"
    ambiguous = "물질의 지분을 정리했다."
    choice, = select_senses(ambiguous, _tokens(ambiguous))
    assert choice.sense_id is None


def test_specific_compound_property_survives_canonical_noun_grouping():
    # 분자+량으로 나뉘어도 전체 물리량을 인식해야 한다. 분자 접두 부분만 쓰지 않는다.
    text = "해녀가 물질의 분자량을 측정했다."
    choice, = select_senses(text, _tokens(text))
    assert choice.sense_id == "muljil.substance"
    result = G2P().convert(text)
    assert result.surface_pronunciation[4:6] == "물찌"
    assert result.complete


@pytest.mark.parametrize(("text", "start", "expected"), [
    ("물질의 밀도를 재었다.", 0, "물찌"),
    ("강가의 모래톱을 바라보았다.", 0, "강까"),
    ("강가로 나갔다.", 0, "강까"),
])
def test_selected_properties_reach_plain_and_detailed_output(text, start, expected):
    converter = G2P()
    result = converter.convert(text)
    assert converter(text) == result.surface_pronunciation
    assert result.surface_pronunciation[start:start + len(expected)] == expected
    assert result.complete


def test_hard_boundary_inside_auxiliary_complex_blocks_relation():
    text = "날개가 찢어진 잠자리를 관찰했다."
    tokens = _tokens(text)
    assert select_senses(text, tokens)[0].sense_id == "jamjari.insect"
    # 어/EC와 지/VX 사이를 절단하면 관형절의 원래 논항을 넘겨서는 안 된다.
    choice, = select_senses(text, tokens, frozenset({text.index("진")}))
    assert choice.sense_id is None
