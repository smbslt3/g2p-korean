"""독립 동결 파생어 규칙 사례를 실제 분석기 없이 회귀 검사한다."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def run_case(case, strict_api_supported):
    # 기대는 외부 JSON에 고정하며 실행 결과에서 생성하지 않는다.
    from g2p_ko.model import AnalysisToken, Boundary, Handler, OutputSegment, SourceSpan
    from g2p_ko.korean.engine import _build_units
    from g2p_ko.korean.morphology import _Annotation, _apply_morphology_rules
    from g2p_ko.korean.word_roles import derived_word_role

    text = case["text"]
    tokens = tuple(AnalysisToken(item["form"], item["tag"], item["start"], item["end"],
        tuple(tuple(part) for part in item.get("morphemes", ())),
        tuple(tuple(span) for span in item.get("morpheme_spans", ()))) for item in case["tokens"])
    cuts = sorted({0, len(text), *case.get("hard_boundaries", ()),
        *case.get("protected_offsets", ()), *(i + 1 for i in case.get("protected_offsets", ()))})
    segments = []
    for start, end in zip(cuts, cuts[1:]):
        handler = Handler.PROTECTED if start in case.get("protected_offsets", ()) else Handler.KOREAN
        segments.append(OutputSegment(text[start:end], (SourceSpan.from_source(text, start, end),),
            handler, "독립 통제 입력", boundary_before=Boundary.HARD if start in case.get("hard_boundaries", ()) else Boundary.WORD))
    segments = tuple(segments)
    units = _build_units(segments, trace=True)
    annotation = _Annotation.from_tokens(tokens, text)
    strict_kwargs = {"exact_source": True} if strict_api_supported else {}
    role = derived_word_role(annotation, case["right_start"], units, segments, tuple(case["pause_boundaries"]), **strict_kwargs)
    observed = {"role": None if role is None else role.role}
    failures = []
    if observed["role"] != case["expect_role"]:
        failures.append("파생어 역할 기대 불일치")
    if role is not None and (role.start != case["right_start"] or role.end != len(text)):
        failures.append("단어 전체 증명 범위 불일치")

    if case["scope"] == "certificate_and_local_rule":
        class ControlledAnalyzer:
            def analyze(self, island):
                if island != text:
                    raise AssertionError("고정 fixture와 다른 분석 요청")
                return tokens
            analyze_components = analyze

        rewrites = []
        pair = tuple(case["boundary"])
        relations = {pair: case["reading_relation"]} if case["reading_relation"] else None
        diagnostics, _, _, _ = _apply_morphology_rules(text, units, segments, ControlledAnalyzer(), rewrites,
            trace=True, pause_boundaries=tuple(case["pause_boundaries"]), reading_relations=relations)
        word_events = [item for item in rewrites if item.rule_id == "ko.n_insertion.word"]
        observed.update(word_rule_count=len(word_events), local_right=units[pair[1]].text,
            diagnostics=[item.code for item in diagnostics],
            word_rewrites=[item.to_dict() for item in word_events])
        if observed["word_rule_count"] != case["expect_word_rule_count"]:
            failures.append("단어 ㄴ 첨가 규칙 횟수 불일치")
        if observed["local_right"] != case["expect_local_right"]:
            failures.append("국소 오른쪽 첫 음절 불일치")
        if observed["diagnostics"] != case["expect_failure_diagnostics"]:
            failures.append("분석 실패 진단 불일치")
        for event in word_events:
            if event.stage.value != "phonology" or event.handler.value != "korean":
                failures.append("규칙 보고 단계·처리기 불일치")
            if event.before != text[pair[0]:pair[1] + 1]:
                failures.append("규칙 보고 원래 국소 문자열 불일치")
            if event.after != text[pair[0]:pair[1]] + case["expect_local_right"]:
                failures.append("규칙 보고 변경 국소 문자열 불일치")
            if not event.source_spans or any(text[s.start:s.end] != s.surface for s in event.source_spans):
                failures.append("규칙 보고 원문 근거 불일치")
    from g2p_ko.korean.ending_ownership import verified_source_owners
    ownership_observed = []
    for check in case.get("ownership_checks", ()):
        owner = verified_source_owners(tokens[check["token_index"]]).get((check["offset"], check["role"]))
        value = None if owner is None else [owner.form, owner.tag]
        ownership_observed.append({"offset": check["offset"], "role": check["role"], "owner": value})
        if value != check["expect_owner"]:
            failures.append("융합 모음·과거 받침의 배타 소유 투영 불일치")
    return {"id": case["id"], "passed": not failures, "failures": failures, "observed": observed, "ownership_observed": ownership_observed}

def _assert_frozen_cases(filename, *, excluded=()):
    cases = json.loads((Path(__file__).parent / filename).read_text(encoding="utf-8"))["cases"]
    disposition = json.loads((Path(__file__).parent / 'fixtures/shared_word_grammar/Legacy_Authority_Disposition_V1.json').read_text(encoding='utf-8'))
    overrides = {row['case_id']: row['harness_only_overrides'] for row in disposition['cases']
                 if row['source_path'] == 'tests/' + filename}
    groups = {}
    with patch("g2p_ko.analyzer._get_kiwi", side_effect=AssertionError("통제 검사에서 실제 분석기를 호출할 수 없다.")):
        for original in cases:
            case = dict(original)
            if case["id"] in excluded:
                continue
            # 원시 자모 증명과 약한 어휘 범주 권한을 구분한 독립 정책 보충이다.
            case.update(overrides.get(case['id'], {}))
            row = run_case(case, True)
            assert row["passed"], (case["id"], row["failures"])
            if case["equivalence_group"]:
                comparable = {key: value for key, value in row["observed"].items() if key != "word_rewrites"}
                groups.setdefault(case["equivalence_group"], []).append(comparable)
    for group in groups.values():
        assert all(item == group[0] for item in group)


def test_shared_derived_word_role_and_n_insertion_frozen_cases():
    _assert_frozen_cases("derived_word_role_cases_v1.json")


def test_licensed_ha_contraction_frozen_cases():
    # 원본의 구성 불가능한 입력 하나는 아래 생성자 거부 검사로 분리한다.
    _assert_frozen_cases("derived_ha_contraction_cases_v1.json", excluded=("missing_morphemes_guard",))


def test_raw_spans_without_morphemes_are_rejected_before_pronunciation():
    cases = json.loads((Path(__file__).parent / "derived_ha_contraction_cases_v1.json").read_text(encoding="utf-8"))["cases"]
    case = next(item for item in cases if item["id"] == "missing_morphemes_guard")
    with pytest.raises(ValueError, match="형태소 원시 범위"):
        run_case(case, True)
