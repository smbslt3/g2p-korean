"""별도 보존 참고를 원래 동결 판정기의 기존 run에 연결한다."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
import importlib.util
import json
from pathlib import Path
import traceback

HERE=Path(__file__).resolve().parent
ROUND = HERE
spec=importlib.util.spec_from_file_location('original_frozen_quote_checker',ROUND/'run_quote_refs.py')
checker=importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)
ADDENDUM_SHA='b6db68d523aeb569b90c62a144716ad0c429fdced51206c3b9e045e02151e51f'


def load():
    _, classes, heads = checker.load_frozen()
    manifest = ROUND / "spine_reference_freeze_manifest.json"
    assert checker.sha(manifest) == ADDENDUM_SHA
    binding = json.loads(manifest.read_text(encoding="utf-8"))
    files = {item["path"]: item["sha256"] for item in binding["files"]}
    assert checker.sha(ROUND / "spine_references.json") == files["spine_refs_private/references.json"]
    refs = json.loads((ROUND / "spine_references.json").read_text(encoding="utf-8"))
    assert len(refs["records"]) == 3 and sum(len(r["targets"]) for r in refs["records"]) == 4
    return refs, classes, heads


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--src',type=Path); parser.add_argument('--out',type=Path,required=True); parser.add_argument('--preflight',action='store_true'); args=parser.parse_args()
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    refs,classes,heads=load()
    if args.preflight:
        pure=checker.synthetic_preflight()
        result=dict(status=pure['status'],reused_checker_synthetic_checks=len(pure['checks']),addendum_records=3,target_occurrences=4,project_imports=0,source_calls=0)
        checker.dump(out/'pure_preflight.json',result); print(json.dumps(result)); return
    assert args.src
    # 로컬 동결 로더가 복사된 실행 지원 파일의 해시를 확인한다.
    with (out/'EXECUTION_STARTED').open('x',encoding='utf-8') as marker: marker.write('별도 보존 참고 단일 실행 시작\n')
    try:
        with (out/'runtime_stdout.log').open('w',encoding='utf-8') as stdout,(out/'runtime_stderr.log').open('w',encoding='utf-8') as stderr,redirect_stdout(stdout),redirect_stderr(stderr):
            safe=checker.run(args.src.resolve(),out,refs,classes,heads)
        native=json.loads((out/'actual_results.json').read_text(encoding='utf-8'))
        premise=[]
        for row in native['records']:
            first=next((t for t in row.get('targets',[]) if t['id']=='t1'),None)
            evs=first['actual_choice']['evidence'] if first and first['actual_choice'] else []
            relations={e['relation'] for e in evs}
            premise.append(dict(id=row['id'],native_typed_head='explicit_typed_function_head' in relations,
                                native_quote_boundary='quoted_nominal_boundary' in relations,
                                native_unresolved_owner='unresolved_quote_ownership' in relations,
                                component_evidence_count=sum(e['relation']=='quoted_nominal_component' for e in evs)))
        safe.update(core_glyph_variants=0,quote_pairs=1,semantic_scenes=3,addendum_records=3,original41_included=False,
                    native_spine_applicability=premise,native_spine_premise_observed=sum(p['native_typed_head'] and p['native_quote_boundary'] for p in premise),
                    full_sentence_phone_scoring=False,headword_phone_scoring=False)
        checker.dump(out/'parent_safe_summary.json',safe)
        print(json.dumps(safe,ensure_ascii=True))
    except Exception as error:
        checker.dump(out/'fatal_private.json',dict(error_type=type(error).__name__,traceback=traceback.format_exc()))
        print(json.dumps(dict(status='FATAL',error_type=type(error).__name__))); raise SystemExit(1)


if __name__=='__main__': main()
