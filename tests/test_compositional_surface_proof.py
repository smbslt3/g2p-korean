"""생산적 축약의 독립 동결 기대를 실제 분석기 없이 검증한다."""

import importlib
import json
from pathlib import Path
from unittest.mock import patch

from _surface_proof_reference import Score, evaluate_case, run_gap, run_joined


def _modules():
    names = {
        'model': 'g2p_ko.model', 'shared': 'g2p_ko.korean._shared',
        'hangul': 'g2p_ko.korean.hangul', 'roles': 'g2p_ko.korean.word_roles',
        'ownership': 'g2p_ko.korean.ending_ownership',
        'formal': 'g2p_ko.korean.formal_attachment',
        'surface_proof': 'g2p_ko.korean.surface_proof',
        'phonology': 'g2p_ko.korean.engine',
    }
    return {key: importlib.import_module(value) for key, value in names.items()}


def _cases():
    return json.loads(Path(__file__).with_name('compositional_surface_proof_cases_v1.json').read_text(encoding='utf-8'))['cases']


def test_compositional_proof_origins_owners_and_roles():
    modules, cases = _modules(), _cases()
    assert len(cases) == 193
    disposition = json.loads((Path(__file__).parent / 'fixtures/shared_word_grammar/Legacy_Authority_Disposition_V1.json').read_text(encoding='utf-8'))
    overrides = {row['case_id']: row['harness_only_overrides'] for row in disposition['cases']
                 if row['source_path'] == 'tests/compositional_surface_proof_cases_v1.json'}
    score = Score()
    with patch('g2p_ko.analyzer._get_kiwi', side_effect=AssertionError('통제 검사에서 실제 분석기를 호출할 수 없다.')):
        for original in cases:
            case = dict(original)
            # 원본 골드는 보존하고, 출처가 충돌한 단어 역할만 별도 정책으로 판정한다.
            case.update(overrides.get(case['id'], {}))
            # 원형·유래 기대와 공백용 API에 대한 범위 불일치를 구분한다.
            case.pop('formal', None)
            result = evaluate_case(case, modules, score)
            failures = [item for item in result['checks'] if not item['passed']]
            assert not failures, (case['id'], failures)
    assert score.metrics['atom_origin_sets'] == {'passed': 896, 'total': 896}
    assert score.metrics['constructor_input_rejection'] == {'passed': 5, 'total': 5}


def test_joined_formal_transitions_keep_original_source_aligned_gold():
    modules = _modules()
    cases = [case for case in _cases() if case.get('formal', {}).get('expect_sound_effect') == 'changed']
    assert len(cases) == 26
    metrics = {}
    with patch('g2p_ko.analyzer._get_kiwi', side_effect=AssertionError('통제 검사에서 실제 분석기를 호출할 수 없다.')):
        for case in cases:
            result = run_joined(case, modules, metrics)
            assert all(item['passed'] for item in result['checks']), result


def test_certified_formal_chain_at_declared_gap_and_retained_guards():
    modules = _modules()
    cases = json.loads(Path(__file__).with_name('formal_chain_gap_cases_v1.json').read_text(encoding='utf-8'))['cases']
    assert len(cases) == 6
    metrics = {}
    with patch('g2p_ko.analyzer._get_kiwi', side_effect=AssertionError('통제 검사에서 실제 분석기를 호출할 수 없다.')):
        for case in cases:
            result = run_gap(case, modules, metrics)
            assert all(item['passed'] for item in result['checks']), result
