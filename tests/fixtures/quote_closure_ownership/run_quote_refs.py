"""동결된 원문 참고를 선택한 소스의 기존 의미 선택기에 연결한다."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROUND = HERE
FREEZE_SHA = '5aa12a1fc6e374ed8c4b489553c8207e9115875e50009d1ba64b02e6386cb036'
FIELDS = ('relation', 'target_start', 'target_end', 'anchor_start', 'anchor_end', 'semantic_class')
BOUNDARY_RELATIONS = {'quoted_nominal_boundary', 'quoted_containment_boundary'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def load_frozen():
    # 원래 참조 동결은 유지하고 실행에 필요한 파일만 로컬에서 읽는다.
    manifest_path = ROUND / "quote_reference_freeze_manifest.json"
    assert sha(manifest_path) == FREEZE_SHA
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {item["path"]: item["sha256"] for item in manifest["files"]}
    assert sha(ROUND / "quote_references.json") == files["quote_refs_private/references.json"]
    assert sha(ROUND / "semantic_fact_catalog.json") == manifest["contracts"]["contract/Semantic_Fact_API_Metadata_KO.json"]
    receipt = json.loads((ROUND / "support_copy_receipt.json").read_text(encoding="utf-8"))
    for item in receipt["portable_files"]:
        assert sha(ROUND / item["path"]) == item["sha256"]
    refs = json.loads((ROUND / "quote_references.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROUND / "semantic_fact_catalog.json").read_text(encoding="utf-8"))
    classes = {sense['sense_id']: set(sense['semantic_classes']) for family in catalog['기존_동형_명사_목록'] for sense in family['senses']}
    heads = {item['lemma']: set(item['noun_classes']) for item in catalog['기존_유형_핵어_자료_발췌']['항목']}
    return refs, classes, heads


def check_target(record, target, choices, classes, heads):
    """최종 선택과 원문에 귀속된 실제 반환 근거를 따로 검사한다."""
    start, end = target['start'], target['end']
    expected = target['expected_semantics']
    found = [c for c in choices if (c['start'], c['end'], c['spelling']) == (start, end, target['surface'])]
    checks = {'unique_native_choice': len(found) == 1}
    if len(found) != 1:
        return dict(checks=checks, actual_choice=None, source_authority=None)
    choice = found[0]
    mode = expected['selection']
    checks['outcome'] = ((choice['sense_id'] == expected['sense_id'] and choice['reason'] == 'selected') if mode == 'selected'
                         else (choice['sense_id'] is None and (choice['reason'] == 'conflicting_evidence' if mode == 'conflict' else choice['reason'] != 'selected')))
    evs = choice['evidence']
    coordinates = all(all(isinstance(ev[f], int) and not isinstance(ev[f], bool) for f in ('target_start', 'target_end', 'anchor_start', 'anchor_end'))
                      and (ev['target_start'], ev['target_end']) == (start, end)
                      and 0 <= ev['anchor_start'] < ev['anchor_end'] <= len(record['input']) for ev in evs)
    checks['native_evidence_coordinates'] = coordinates
    checks['native_evidence_hard_ownership'] = coordinates and all(not any(min(start, ev['anchor_start']) < h < max(end, ev['anchor_end']) for h in record['hard_boundaries']) for ev in evs)
    authority = None
    if mode in ('selected', 'conflict'):
        relevant = [ev for ev in evs if ev['relation'] not in BOUNDARY_RELATIONS]
        def owns(ev, anchor, accepted):
            return (ev['semantic_class'] in accepted and ev['anchor_start'] <= anchor['start'] < anchor['end'] <= ev['anchor_end']
                    and not any(ev['anchor_start'] <= other['start'] < other['end'] <= ev['anchor_end'] for other in record['targets'] if other['id'] != target['id']))
        anchors = expected['source_anchors']
        authority = coordinates and bool(anchors) and all(any(owns(ev, anchor, classes[expected['sense_id']] if mode == 'selected' else heads[anchor['surface']]) for ev in relevant) for anchor in anchors)
        checks['source_anchor_authority'] = authority
        unresolved = [q for q in record['expected_topology'] if q['state'] == 'unresolved']
        checks['selected_evidence_outside_unresolved_regions'] = not any(q['start'] < max(end, ev['anchor_end']) and min(start, ev['anchor_start']) < q['end'] for q in unresolved for ev in evs)
        relation = expected.get('retained_lexical_relation')
        if relation:
            checks['native_derivation_relation'] = any(ev['relation'] == relation and ev['semantic_class'] in set(expected['retained_lexical_classes'])
                                                      and ev['anchor_start'] == anchors[0]['start'] and ev['anchor_end'] == anchors[0]['end'] for ev in evs)
    return dict(checks=checks, actual_choice=choice, source_authority=authority,
                unresolved_ownership_marker_authority='최종 후보 API의 새 관계 선언 전에는 추정하지 않음',
                phone_scoring='없음; 표제어 발음 참고는 의미·출처 검사와 별도 보존')


def check_ranges(record, ranges):
    """정상 짝 도우미는 보충 관측이며 최종 소유 유보를 대신하지 않는다."""
    actual = set(ranges)
    required = {(q['start'], q['end'] - 1) for q in record['expected_topology'] if q['state'] == 'valid'}
    allowed = required | {(q['start'], q['end'] - 1) for q in record['expected_topology'] if q['state'] == 'valid_nested'}
    return required <= actual <= allowed


def synthetic_preflight():
    # 아래 문자열은 판정기 필드 검사 전용이며 사전 입력·새 의미 참고가 아니다.
    target = dict(id='t', start=0, end=2, surface='AA', expected_semantics=dict(selection='selected', sense_id='s', source_anchors=[dict(start=3, end=5, surface='BB')]))
    record = dict(input='AA BB', targets=[target], hard_boundaries=[], expected_topology=[])
    ev = dict(relation='r', target_start=0, target_end=2, anchor_start=3, anchor_end=5, semantic_class='T')
    choice = dict(start=0, end=2, spelling='AA', sense_id='s', reason='selected', evidence=[ev])
    check = lambda r=record, t=target, c=None: check_target(r, t, [choice] if c is None else c, {'s': {'T'}}, {'BB': {'T'}, 'CC': {'U'}})['checks']
    tests = {'native_positive': all(check().values()), 'duplicate_choice_rejected': not check(c=[choice, choice])['unique_native_choice'],
             'wrong_sense_rejected': not check(c=[dict(choice, sense_id='other')])['outcome'],
             'wrong_target_coordinates_rejected': not check(c=[dict(choice, evidence=[dict(ev, target_end=1)])])['native_evidence_coordinates'],
             'wrong_anchor_rejected': not check(c=[dict(choice, evidence=[dict(ev, anchor_start=0, anchor_end=2)])])['source_anchor_authority'],
             'hard_crossing_rejected': not check(r=dict(record, hard_boundaries=[2]))['native_evidence_hard_ownership']}
    unresolved = dict(target, expected_semantics=dict(target['expected_semantics'], selection='abstain', sense_id=None))
    tests['selected_cannot_satisfy_abstention'] = not check(t=unresolved)['outcome']
    tests['native_abstention'] = check(t=unresolved, c=[dict(choice, sense_id=None, reason='insufficient_evidence', evidence=[])])['outcome']
    conflict = dict(target, expected_semantics=dict(selection='conflict', sense_id=None, source_anchors=[dict(start=3, end=5, surface='BB'), dict(start=6, end=8, surface='CC')]))
    conflict_record = dict(record, input='AA BB CC', targets=[conflict])
    conflict_choice = dict(choice, sense_id=None, reason='conflicting_evidence', evidence=[ev, dict(ev, anchor_start=6, anchor_end=8, semantic_class='U')])
    tests['native_conflict_sources'] = all(check(r=conflict_record, t=conflict, c=[conflict_choice]).values())
    tests['missing_conflict_anchor_rejected'] = not check(r=conflict_record, t=conflict, c=[dict(conflict_choice, evidence=[ev])])['source_anchor_authority']
    topology = dict(expected_topology=[dict(state='valid', start=0, end=9), dict(state='valid_nested', start=1, end=8)])
    tests['supplementary_root_and_nested'] = check_ranges(topology, [(0, 8), (1, 7)])
    tests['supplementary_unowned_pair_rejected'] = not check_ranges(topology, [(0, 8), (2, 6)])
    tests['raw_tag_mutation_detected'] = dict(form='AA', tag='NNG') != dict(form='AA', tag='JKS')
    tests['original_part_order_mutation_detected'] = [('A', 'NNG'), ('B', 'XSV')] != [('B', 'XSV'), ('A', 'NNG')]
    other = dict(id='other', start=3, end=5)
    tests['other_occurrence_cannot_supply_anchor'] = not check(r=dict(record, targets=[target, other]))['source_anchor_authority']
    assert all(tests.values()), '순수 판정기 사전 점검 실패'
    return dict(status='PASS', checks=tests, project_imports=0, selector_calls=0, model_calls=0, kiwi_calls=0)


def token_snapshot(token):
    return dict(form=token.form, tag=token.tag, start=token.start, end=token.end, morphemes=[list(p) for p in token.morphemes])


def choice_snapshot(choice):
    return dict(start=choice.start, end=choice.end, spelling=choice.spelling, sense_id=choice.sense_id, reason=choice.reason,
                evidence=[{field: getattr(evidence, field) for field in FIELDS} for evidence in choice.evidence])


def source_inventory(src):
    return {str(p.relative_to(src)).replace('\\', '/'): sha(p) for p in sorted((src / 'g2p_ko').rglob('*.py'))}


def module_origins(src):
    result = {}
    for name, module in sorted(sys.modules.items()):
        if name == 'g2p_ko' or name.startswith('g2p_ko.'):
            origin = Path(module.__file__).resolve()
            assert origin.is_relative_to(src), '선택 소스 밖의 프로젝트 모듈'
            result[name] = str(origin)
    return result


def run(src, out, refs, classes, heads):
    assert not any(n == 'g2p_ko' or n.startswith('g2p_ko.') for n in sys.modules)
    before_source = source_inventory(src)
    assert before_source and (src / 'g2p_ko/korean/semantic_policy.py').is_file()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(src))
    policy = importlib.import_module('g2p_ko.korean.semantic_policy')
    origins = module_origins(src)
    results = []
    counts = dict(selector_calls=0, supplementary_quote_range_calls=0, model_constructors_by_runner=0, analysis_calls_by_runner=0)
    for record in refs['records']:
        row = dict(id=record['id'], scene_id=record['scene_id'], scope=record['scope'])
        if record['scope'] == 'abstract':
            results.append(dict(row, status='unbound', targets=[]))
            continue
        row.update(status='executed', input=record['input'], supplied_tokens=record['supplied_tokens'], hard_boundaries=record['hard_boundaries'])
        try:
            tokens = tuple(policy.SemanticToken(form=t['form'], tag=t['tag'], start=t['start'], end=t['end'], morphemes=tuple(tuple(p) for p in t['morphemes'])) for t in record['supplied_tokens'])
            before = [token_snapshot(t) for t in tokens]
            counts['selector_calls'] += 1
            native = policy.select_senses(record['input'], tokens, hard_boundaries=frozenset(record['hard_boundaries']))
            after = [token_snapshot(t) for t in tokens]
            choices = [choice_snapshot(c) for c in native]
            row.update(input_preserved=before == after == record['supplied_tokens'], native_choices=choices,
                       targets=[dict(id=t['id'], start=t['start'], end=t['end'], **check_target(record, t, choices, classes, heads)) for t in record['targets']])
        except Exception as error:
            row.update(status='error', error_type=type(error).__name__, traceback=traceback.format_exc(), targets=[])
        try:
            counts['supplementary_quote_range_calls'] += 1
            ranges = tuple(policy._balanced_quote_ranges(record['input'], frozenset(record['hard_boundaries'])))
            row.update(supplementary_valid_ranges=[list(pair) for pair in ranges], supplementary_valid_range_check=check_ranges(record, ranges))
        except Exception as error:
            row.update(supplementary_error_type=type(error).__name__, supplementary_traceback=traceback.format_exc())
        results.append(row)
        dump(out / f"{record['id']}.json", row)
    source_unchanged = before_source == source_inventory(src)
    final_origins = module_origins(src)
    report = dict(status='TERMINAL', source=str(src), source_inventory=before_source, source_unchanged=source_unchanged,
                  module_origins=final_origins, initial_module_origins=origins, counts=counts,
                  records=results, full_phone_scoring='없음', headword_phone_reference_scope='별도 참고이며 채점하지 않음',
                  unresolved_marker_authority='새 관계·이유의 선언 없이는 추정하지 않음')
    dump(out / 'actual_results.json', report)
    checks = [value for row in results for target in row.get('targets', []) for value in target['checks'].values()]
    observed = sum(len(r.get('targets', [])) for r in results)
    expected = sum(len(r['targets']) for r in refs['records'])
    safe = dict(status='TERMINAL', records=len(results), constructed_records=sum(r['scope'] == 'constructed' for r in results),
                semantic_scenes=len({r['scene_id'] for r in results}), core_glyph_variants=20, quote_pairs=10,
                target_occurrences=expected, observed_targets=observed, complete_observation=observed == expected and all(r['status'] != 'error' for r in results),
                abstract_unbound_ids=[r['id'] for r in results if r['status'] == 'unbound'], errors=sum(r['status'] == 'error' for r in results),
                all_nonnull_target_checks_true=bool(checks) and all(checks), input_preservation_all=all(r.get('input_preserved', False) for r in results if r['scope'] == 'constructed'),
                source_unchanged=source_unchanged, module_isolation=True, counts=counts, full_phone_gold_records=0)
    dump(out / 'parent_safe_summary.json', safe)
    return safe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--src', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    refs, classes, heads = load_frozen()
    if args.preflight:
        result = synthetic_preflight()
        dump(out / 'synthetic_preflight.json', result)
        print(json.dumps(dict(status=result['status'], synthetic_checks=len(result['checks']), project_imports=0)))
        return
    assert args.src is not None
    # 로컬 동결 로더가 복사된 실행 지원 파일의 해시를 확인한다.
    # 재실행이나 기존 실제 출력 덮어쓰기는 자동으로 허가하지 않는다.
    with (out / 'EXECUTION_STARTED').open('x', encoding='utf-8') as marker:
        marker.write('선택 소스 단일 실행 시작\n')
    print(json.dumps(run(args.src.resolve(), out, refs, classes, heads), ensure_ascii=True))


if __name__ == '__main__':
    main()
