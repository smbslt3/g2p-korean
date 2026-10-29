"""독립 동결한 문법·소유·공개 경계 계약을 별도 프로세스에서 검증한다."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys


def test_frozen_shared_word_grammar_and_public_boundary_contract(tmp_path):
    root = Path(__file__).resolve().parents[1]
    reference = tmp_path / 'reference'
    shutil.copytree(Path(__file__).parent / 'fixtures/shared_word_grammar', reference)
    runner = reference / 'run_frozen_v2.py'
    output = reference / 'grammar_observation.json'
    process = subprocess.run(
        [sys.executable, '-I', '-X', 'utf8', '-B', str(runner),
         '--src', str(root / 'src'), '--out', str(output)],
        cwd=root, capture_output=True, text=True, encoding='utf-8', check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['strict_api_present'] is True
    spec = importlib.util.spec_from_file_location(
        'shared_word_grammar_policy_score', reference / 'score_post03_supplement_v1.py',
    )
    scoring = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scoring)
    supplement = json.loads((reference / 'post03_lexical_class_adjudication_v1.json').read_text(encoding='utf-8'))
    score = scoring.score_result(result, supplement)
    assert score['ok'], score
    assert score['original_raw_counts'] == {
        key: result[key] for key in ('total', 'passed', 'failed', 'by_kind')
    }
    assert score['adjudicated_counts']['by_kind']['certificate']['passed'] == 158
    assert score['adjudicated_counts']['by_kind']['packaging_equivalence']['passed'] == 72
    assert score['adjudicated_counts']['by_kind']['public_gap']['passed'] == 20
