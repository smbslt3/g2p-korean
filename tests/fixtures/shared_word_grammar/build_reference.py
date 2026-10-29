"""프로젝트를 가져오거나 실행하지 않고 독립 기대값 자료를 고정한다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = []


def add(case_id, parts, status, category=None, *, host=None, tail=None, surface_status=None,
        note="", variants=("split", "fused"), surface=None, spans=None,
        mutation=None, equivalence=True, n_target=None):
    """명시 문법 계약과 입력 근거를 실행 전 기록한다."""
    CASES.append({
        "id": case_id,
        "parts": parts,
        "surface": surface if surface is not None else "".join(form for form, _ in parts),
        "spans": spans,
        "variants": list(variants),
        "mutation": mutation,
        "equivalence": equivalence,
        "expected": {
            "lexical_status": status,
            "final_category": category,
            "assert_category": status == "eligible",
            "host": host,
            "tail": tail,
            "surface_status": surface_status if surface_status is not None else ("verified" if status == "eligible" else None),
            "n_target": (status == "eligible") if n_target is None else n_target,
        },
        "note_ko": note,
    })


add("lexical_noun", [("여백", "NNG")], "eligible", "noun",
    note="단순 독립 명사의 보존 대조군이다.")
add("lexical_modifier", [("이", "MM")], "eligible", "modifier", host="modifier", n_target=False,
    note="어휘 연음과 단어 ㄴ 첨가의 기존 범주 정책은 다르다.")
add("lexical_conjunction", [("그리고", "MAJ")], "eligible", "adverb", host="adverbial", n_target=False)
add("lexical_numeral", [("일", "NR")], "eligible", "noun", host="nominal", n_target=False)
add("prefix_numeral", [("제", "XPN"), ("일", "NR")], "eligible", n_target=False,
    note="접두사의 존재만으로 기존 ㄴ 첨가 seed 범위를 넓히지 않는다.")
add("prefix_noun", [("온", "XPN"), ("몸", "NNG")], "eligible",
    note="접두 파생의 독립 어휘 적격성은 성립하지만 명사 품사 승계는 단정하지 않는다.")
add("prefix_other_noun", [("외", "XPN"), ("숙모", "NNG")], "eligible",
    note="모음 시작의 다른 접두 파생 구성이다.")
add("prefix_liaison_noun", [("알", "XPN"), ("몸", "NNG")], "eligible",
    note="실질적 독립 어기와 접두사만 있는 구성이다.")
add("prefix_adverb", [("맨", "XPN"), ("먼저", "MAG")], "eligible",
    note="접두 파생을 명사 어기에만 제한하지 않는다.")
add("prefix_repeat", [("극", "XPN"), ("초", "XPN"), ("단파", "NNG")], "eligible",
    variants=("split", "fused", "mixed"),
    note="연속 접두사 뒤의 한 독립 어기를 확인한다. 명사 인접을 사용하지 않는다.")
add("derived_noun", [("음악", "NNG"), ("성", "XSN")], "eligible", "noun")
add("plural_nominal", [("이름", "NNG"), ("들", "XSN")], "eligible", "noun",
    note="새 명사 범주는 이전 명사의 예외 신원 보존 증거가 아니다.")
add("root_derived_noun", [("희소", "XR"), ("성", "XSN")], "eligible", "noun",
    note="접미 파생이 실제 범주를 부여한 어근은 접두사만 붙인 어근과 다르다.")
add("derived_noun_particle", [("음악", "NNG"), ("성", "XSN"), ("도", "JX")],
    "eligible", "noun", host="nominal", tail="particle")
add("derived_verb_finite", [("공부", "NNG"), ("하", "XSV"), ("다", "EF")],
    "eligible", "verb", host="finite", tail="finite")
add("derived_adjective_prefinal", [("건강", "NNG"), ("하", "XSA"), ("겠", "EP"), ("다", "EF")],
    "eligible", "adjective", host="finite", tail="finite")
add("derived_verb_prefinals", [("공부", "NNG"), ("하", "XSV"), ("시", "EP"), ("겠", "EP"), ("다", "EF")],
    "eligible", "verb", host="finite", tail="finite", variants=("split", "fused", "mixed"))
add("derived_verb_conjunctive", [("공부", "NNG"), ("하", "XSV"), ("고", "EC")],
    "eligible", "verb", host="conjunctive", tail="conjunctive")
add("derived_verb_adnominal", [("공부", "NNG"), ("하", "XSV"), ("는", "ETM")],
    "eligible", "verb", host="adnominal", tail="adnominal")
add("derived_verb_nominalized", [("공부", "NNG"), ("하", "XSV"), ("기", "ETN")],
    "eligible", "verb", host="nominalized", tail="nominalized",
    note="ETN은 문법적 명사화이며 사전상 품사를 명사로 바꾸지 않는다.")
add("nominalized_case", [("연구", "NNG"), ("하", "XSV"), ("기", "ETN"), ("를", "JKO")],
    "eligible", "verb", host="nominalized", tail="particle")
add("nominalized_aux_stack", [("건강", "NNG"), ("하", "XSA"), ("기", "ETN"), ("만", "JX"), ("도", "JX")],
    "eligible", "adjective", host="nominalized", tail="particle")
add("derived_adverb", [("조용", "XR"), ("히", "XSM")], "eligible", "adverb")
add("adverb_aux_particle", [("조용", "XR"), ("히", "XSM"), ("도", "JX")],
    "eligible", "adverb", host="adverbial", tail="particle")
add("connective_aux_particle", [("공부", "NNG"), ("하", "XSV"), ("고", "EC"), ("도", "JX")],
    "eligible", "verb", host="conjunctive", tail="particle")
add("bare_predicate_legacy", [("보", "VV")], "eligible", "verb", host="predicate", tail="open_inflection")
add("prefinal_predicate_legacy", [("보", "VV"), ("겠", "EP")],
    "eligible", "verb", host="predicate", tail="prefinal")
add("root_derived_adjective", [("시원", "XR"), ("스럽", "XSA"), ("다", "EF")],
    "eligible", "adjective", host="finite", tail="finite")
add("explicit_causative", [("씻", "VV"), ("이", "XSV"), ("다", "EF")],
    "eligible", "verb", host="finite", tail="finite")
add("copula_finite", [("음악", "NNG"), ("성", "XSN"), ("이", "VCP"), ("다", "EF")],
    "eligible", "noun", host="finite", tail="finite")
add("copula_prefinal", [("음악", "NNG"), ("성", "XSN"), ("이", "VCP"), ("었", "EP"), ("다", "EF")],
    "eligible", "noun", host="finite", tail="finite")
add("copula_nominalized_particle", [("음악", "NNG"), ("성", "XSN"), ("이", "VCP"), ("기", "ETN"), ("만", "JX")],
    "eligible", "noun", host="nominalized", tail="particle")
add("copula_conjunctive", [("음악", "NNG"), ("성", "XSN"), ("이", "VCP"), ("면", "EC")],
    "eligible", "noun", host="conjunctive", tail="conjunctive")
add("nominalized_copula", [("공부", "NNG"), ("하", "XSV"), ("기", "ETN"), ("이", "VCP"), ("다", "EF")],
    "eligible", "verb", host="final", tail="copula_final")
add("auxiliary_after_contraction", [("공부", "NNG"), ("하", "XSV"), ("어", "EC"), ("보", "VX"), ("다", "EF")],
    "eligible", "verb", host="final", tail="auxiliary_final", surface="공부해보다",
    spans=[(0, 2), (2, 3), (2, 3), (3, 4), (4, 5)], variants=("fused", "shared_tail"),
    note="EC 뒤의 명시된 보조용언은 새 활용 어간을 시작하며 앞 축약의 유래를 보존한다.")
add("contracted_derivation", [("공부", "NNG"), ("하", "XSV"), ("어", "EC")],
    "eligible", "verb", host="conjunctive", tail="conjunctive", surface="공부해",
    spans=[(0, 2), (2, 3), (2, 3)], variants=("fused", "shared_tail"),
    note="기존 유한 표면 증명과 공동 음절 유래를 그대로 재사용한다.")
add("contracted_regular", [("보", "VV"), ("아", "EC")],
    "eligible", "verb", host="conjunctive", tail="conjunctive", surface="봐",
    spans=[(0, 1), (0, 1)], variants=("fused",),
    note="단순 용언의 허용된 규칙 축약 대조군이다.")

add("bare_prefix", [("헛", "XPN")], "excluded")
add("bare_root", [("아늑", "XR")], "excluded")
add("prefixed_root", [("헛", "XPN"), ("시원", "XR")], "excluded",
    note="접두사는 비독립 어근에 독립 품사를 새로 부여하지 않는다.")
add("bare_suffix", [("스럽", "XSA")], "excluded")
add("bare_ending", [("고", "EC")], "excluded")
add("bare_particle", [("만", "JX")], "excluded")
add("unsupported_independent_class", [("어머", "IC")], "excluded",
    note="기존 N/V/M 적격 범위를 새로 넓히지 않는다.")
add("noun_ending", [("음악", "NNG"), ("다", "EF")], "excluded")
add("verb_case_without_nominalization", [("공부", "NNG"), ("하", "XSV"), ("를", "JKO")], "excluded")
add("adjective_case_without_nominalization", [("건강", "NNG"), ("하", "XSA"), ("의", "JKG")], "excluded")
add("two_terminal_endings", [("공부", "NNG"), ("하", "XSV"), ("다", "EF"), ("다", "EF")], "unresolved",
    note="복합 어미·재분석 구조가 증명되지 않았다. 단순한 E 반복으로 허가하지 않는다.")
add("nominalizer_after_finite", [("공부", "NNG"), ("하", "XSV"), ("다", "EF"), ("기", "ETN")], "unresolved")
add("prefinal_without_terminal", [("공부", "NNG"), ("하", "XSV"), ("시", "EP"), ("겠", "EP")],
    "eligible", "verb", host="predicate", tail="prefinal",
    note="기존 파생 활용의 열린 선어말 상태를 보존하되 완료 종결형과 구별한다.")
add("adnominal_case_without_host", [("공부", "NNG"), ("하", "XSV"), ("는", "ETM"), ("이", "JKS")], "excluded")
add("conjunctive_case_without_host", [("공부", "NNG"), ("하", "XSV"), ("고", "EC"), ("가", "JKS")], "excluded")
add("ending_after_particle", [("음악", "NNG"), ("성", "XSN"), ("도", "JX"), ("다", "EF")], "excluded")
add("derivation_after_terminal", [("공부", "NNG"), ("하", "XSV"), ("다", "EF"), ("성", "XSN")], "excluded")
add("invalid_suffix_input", [("새", "MM"), ("하", "XSV"), ("다", "EF")], "excluded")
add("nominal_derivation_then_ending", [("공부", "NNG"), ("하", "XSV"), ("음", "XSN"), ("다", "EF")], "excluded")
add("noncausative_verb_suffix", [("먹", "VV"), ("하", "XSV"), ("다", "EF")], "excluded")

add("adjacent_nouns_recipient", [("음악", "NNG"), ("교육", "NNG")], "eligible", "noun", host="nominal",
    note="정확히 소유한 명사열의 기존 어휘 수신 적격성만 보존한다. 합성 구조는 주장하지 않는다.")
add("adjacent_nouns_with_suffix", [("음악", "NNG"), ("교육", "NNG"), ("적", "XSN")], "unresolved")
add("unknown_tag", [("온", "XPN"), ("몸", "ZZZ")], "unresolved")
add("prefix_outer_copula", [("알", "XPN"), ("몸", "NNG"), ("이", "VCP"), ("다", "EF")],
    "eligible", host="final", tail="copula_final",
    note="단일 독립 어기 바깥의 유일한 계사 결합으로 숙주를 증명한다. 어휘 품사 승계는 주장하지 않는다.")
add("unknown_prefix_suffix_input", [("알", "XPN"), ("몸", "NNG"), ("성", "XSN")], "unresolved",
    note="접두 이후 범주와 접미사 입력 범위를 평면 순서만으로 확정하지 않는다.")
add("prefix_outer_aux_particle", [("알", "XPN"), ("몸", "NNG"), ("도", "JX")],
    "eligible", host="lexical_unknown", tail="particles")
add("prefix_outer_case", [("알", "XPN"), ("몸", "NNG"), ("을", "JKO")],
    "eligible", host="nominal", tail="particles")
add("prefix_outer_finite", [("되", "XPN"), ("살", "VV"), ("다", "EF")],
    "eligible", host="final", tail="final")
add("prefix_outer_prefinal_finite", [("드", "XPN"), ("높", "VA"), ("겠", "EP"), ("다", "EF")],
    "eligible", host="final", tail="final")
add("prefix_outer_nominalized_case", [("되", "XPN"), ("살", "VV"), ("기", "ETN"), ("를", "JKO")],
    "eligible", host="nominalized", tail="particles")
add("prefix_outer_conjunctive", [("드", "XPN"), ("높", "VA"), ("게", "EC")],
    "eligible", host="connective", tail="connective")
add("prefix_outer_adnominal", [("드", "XPN"), ("높", "VA"), ("은", "ETM")],
    "eligible", host="adnominal", tail="adnominal")
add("prefix_outer_auxiliary", [("되", "XPN"), ("살", "VV"), ("아", "EC"), ("보", "VX"), ("다", "EF")],
    "eligible", "verb", host="final", tail="auxiliary_final",
    note="새 보조용언의 정확한 범주는 앞 접두 구성의 품사 미확정과 별개다.")
add("prefix_ambiguous_noun_chain_copula", [("초", "XPN"), ("고속", "NNG"), ("열차", "NNG"), ("이", "VCP"), ("다", "EF")], "unresolved")
add("prefix_inner_derivation_copula", [("알", "XPN"), ("몸", "NNG"), ("성", "XSN"), ("이", "VCP"), ("다", "EF")], "unresolved")
add("unstructured_second_predicate", [("공부", "NNG"), ("하", "XSV"), ("고", "EC"), ("먹", "VV"), ("다", "EF")], "unresolved")
add("unsupported_irregular_surface", [("돕", "VV-I"), ("아", "EC")], "eligible", "verb",
    surface="도와", spans=[(0, 1), (1, 2)], variants=("fused",),
    host="connective", tail="connective", surface_status="unavailable",
    note="충돌 없는 기존 단순 용언의 제한된 어휘 적격성만 보존한다. 미지원 불규칙의 자모 유래를 새로 만들지 않는다.")
add("unsupported_copula_surface", [("음악", "NNG"), ("성", "XSN"), ("이", "VCP"), ("었", "EP"), ("다", "EF")],
    "unresolved", surface="음악성였다", spans=[(0, 2), (2, 3), (3, 4), (3, 4), (4, 5)], variants=("fused",))
add("unexplained_surface_mismatch", [("공부", "NNG"), ("하", "XSV"), ("어", "EC")],
    "unresolved", surface="공부쐐", spans=[(0, 2), (2, 3), (2, 3)], variants=("fused",))
add("missing_morphemes", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("fused",), mutation="missing_morphemes")
add("tag_parts_conflict", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("fused",), mutation="tag_parts_conflict")
add("canonical_identity_conflict", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("fused",), mutation="canonical_identity_conflict")
add("missing_token_ownership", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("split",), mutation="missing_first_token")
add("overlap_token_ownership", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("fused",), mutation="overlap_token")
add("raw_span_identity_conflict", [("온", "XPN"), ("몸", "NNG")], "unresolved",
    variants=("fused",), mutation="reversed_spans")
add("zero_marker_legacy", [("하", "VV"), ("ㅁ", "ETN")], "eligible", "verb",
    host="nominalized", tail="nominalized", surface="함", spans=[(0, 1), (0, 0)],
    variants=("fused",), surface_status="unavailable",
    note="기존 영폭 어미 표지는 강한 자모 소유 증명이 아니지만 모순으로 바꾸지 않는다.")
add("zero_marker_derived", [("공부", "NNG"), ("하", "XSV"), ("ㅁ", "ETN")], "unresolved",
    surface="공부함", spans=[(0, 2), (2, 3), (2, 2)], variants=("fused",), surface_status="unavailable")

# 문법 의미 별칭을 최종 계약의 유한 상태 어휘로 고정한다.
for row in CASES:
    expected = row["expected"]
    expected["host"] = {"finite": "final", "conjunctive": "connective"}.get(expected["host"], expected["host"])
    expected["tail"] = {"finite": "final", "conjunctive": "connective", "particle": "particles"}.get(expected["tail"], expected["tail"])
    if row["id"].startswith("copula_") and expected["tail"]:
        expected["tail"] = "copula_" + expected["tail"]

PUBLIC = [
    {"id": "gap_prefix_ordinary", "reference": "prefix_liaison_noun", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_prefix_fused", "reference": "prefix_liaison_noun", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "variant": "fused", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_derived_nominalized", "reference": "nominalized_case", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_copula", "reference": "copula_prefinal", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_excluded_root", "reference": "bare_root", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "ineligible", "sound_effect": "unchanged"}},
    {"id": "gap_excluded_bad_tail", "reference": "noun_ending", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "ineligible", "sound_effect": "unchanged"}},
    {"id": "gap_unknown_tag", "reference": "unknown_tag", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "unknown", "applicability": "unknown"}},
    {"id": "gap_missing_parts", "reference": "missing_morphemes", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "unknown", "applicability": "unknown"}},
    {"id": "gap_owned_noun_recipient", "reference": "adjacent_nouns_recipient", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_unsupported_copula", "reference": "unsupported_copula_surface", "left": "밖", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "unknown", "applicability": "unknown"}},
    {"id": "gap_one_madi_prefix", "parts": [("양", "XPN"), ("어머니", "NNG")], "left": "밖", "left_tag": "NNG", "relation": "one_madi", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.n_insertion.word"}},
    {"id": "gap_one_madi_non_y", "reference": "prefix_noun", "left": "밖", "left_tag": "NNG", "relation": "one_madi", "expected": {"status": "selected", "applicability": "ineligible", "sound_effect": "changed"}},
    {"id": "gap_one_madi_numeral_donor", "parts": [("양", "XPN"), ("어머니", "NNG")], "left": "십", "left_tag": "NR", "relation": "one_madi", "expected": {"status": "selected", "applicability": "ineligible", "sound_effect": "unchanged"}},
    {"id": "gap_pause", "parts": [("양", "XPN"), ("어머니", "NNG")], "left": "밖", "left_tag": "NNG", "relation": "pause", "expected": {"status": "selected", "applicability": "not_required", "sound_effect": "barrier"}},
    {"id": "gap_modifier_ordinary", "reference": "lexical_modifier", "left": "밤", "left_tag": "NNG", "relation": "ordinary_liaison", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical"}},
    {"id": "gap_modifier_one_madi", "reference": "lexical_modifier", "left": "밤", "left_tag": "NNG", "relation": "one_madi", "expected": {"status": "selected", "applicability": "ineligible", "sound_effect": "unchanged"}},
    {"id": "gap_identity_particle_split", "parts": [("이름", "NNG"), ("도", "JX")], "left": "작품", "left_tag": "NNG", "relation": "one_madi", "variant": "split", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical", "forbidden_rule": "ko.n_insertion.word"}},
    {"id": "gap_identity_particle_fused", "parts": [("이름", "NNG"), ("도", "JX")], "left": "작품", "left_tag": "NNG", "relation": "one_madi", "variant": "fused", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.liaison.lexical", "forbidden_rule": "ko.n_insertion.word"}},
    {"id": "gap_new_nominal_identity_split", "reference": "plural_nominal", "left": "작품", "left_tag": "NNG", "relation": "one_madi", "variant": "split", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.n_insertion.word"}},
    {"id": "gap_new_nominal_identity_fused", "reference": "plural_nominal", "left": "작품", "left_tag": "NNG", "relation": "one_madi", "variant": "fused", "expected": {"status": "selected", "applicability": "eligible", "sound_effect": "changed", "rule": "ko.n_insertion.word"}},
]

# 소리 효과가 공여 받침의 대표음화만으로 달라지는 혼동을 피한다.
for row in PUBLIC:
    if row["left"] == "밖":
        row["left"] = "밤"

FIXTURE = {
    "schema": "r41_independent_references.v1",
    "source_blind": True,
    "basis_ko": "자체 src/API와 깨끗한 R39 접두 계약 및 R41 문법 의미 계약만 읽었다. 기존 시험·정답·평가 출력·후보 코드를 보거나 실행하지 않았다.",
    "scope_ko": "문법 적격성과 정확 품사·문법 호스트·표면 증명·규칙별 조건은 별개다. 인위적 부정 형태소열은 단어의 규범 판정이 아니라 완전 소비·형식 상태 제한을 검증한다.",
    "certificate_cases": CASES,
    "public_gap_cases": PUBLIC,
    "barriers": ["protected", "hard", "pause"],
    "constructor_rejections": [
        {"id": "negative_start", "form": "몸", "tag": "NNG", "start": -1, "end": 1},
        {"id": "empty_range", "form": "몸", "tag": "NNG", "start": 1, "end": 1},
        {"id": "raw_span_count", "form": "온몸", "tag": "XPN+NNG", "start": 0, "end": 2, "morphemes": [("온", "XPN"), ("몸", "NNG")], "spans": [(0, 1)]},
        {"id": "raw_span_outside", "form": "몸", "tag": "NNG", "start": 0, "end": 1, "morphemes": [("몸", "NNG")], "spans": [(0, 2)]},
        {"id": "raw_span_bool", "form": "몸", "tag": "NNG", "start": 0, "end": 1, "morphemes": [("몸", "NNG")], "spans": [(False, 1)]},
    ],
    "public_api_rejections": [
        {"source": "밖알몸", "offset": 1, "relation": "ordinary_liaison"},
        {"source": "밖알몸", "offset": 1, "relation": "one_madi"},
        {"source": "밖\t알몸", "offset": 1, "relation": "ordinary_liaison"},
        {"source": "밖\n알몸", "offset": 1, "relation": "one_madi"},
    ],
    "kiwi_observation_inputs": ["밖 알몸", "밖 양어머니", "공부하기를", "음악성이었다", "극초단파"],
    "kiwi_observation_policy_ko": "실제 Kiwi 토큰과 공개 API 실행은 선택 관찰 자료다. 관찰 결과로 독립 기대값을 고치거나 분석기 버전에 무관한 정답을 주장하지 않는다.",
}


if __name__ == "__main__":
    path = HERE / "frozen_cases.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"certificate_cases": len(CASES), "public_gap_cases": len(PUBLIC), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
