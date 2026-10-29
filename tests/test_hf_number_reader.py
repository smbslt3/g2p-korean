"""외부 숫자 읽기의 배포 무결성·오프라인·문맥 연결을 검증한다."""
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from g2p_ko import G2P, HuggingFaceNumberReader, InputValidationError, KoreanTTSNormalizer

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason='외부 숫자 모델은 Python 3.11 이상을 지원한다.')


def bundle(tmp_path, *, body=None):
    code = body or '''class NumberReader:
    def __init__(self, model_dir, **options):
        self.options = options
    def decide(self, text, start, end, **options):
        if "번호" in text:
            return "digitwise"
        return "native"
'''
    files = {'runtime/__init__.py': 'from .runtime import NumberReader\n',
             'runtime/runtime.py': code, 'model.onnx': 'synthetic model',
             'runtime_model.json': '{}', 'reader_config.json': '{}', 'tokenizer/tokenizer.json': '{}'}
    entries = {}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        entries[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
    manifest = {'schema_version': 1, 'api_version': 1, 'runtime_module': 'runtime/__init__.py', 'files': entries}
    path = tmp_path / 'bundle_manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return tmp_path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_downloaded_code_controls_numeric_context_and_g2p(tmp_path):
    directory, checksum = bundle(tmp_path)
    reader = HuggingFaceNumberReader.from_directory(directory, manifest_sha256=checksum)
    normalizer = KoreanTTSNormalizer(number_reader=reader)
    assert normalizer('1 더') == '하나 더'
    assert normalizer('번호는 25입니다.') == '번호는 이 오입니다.'
    assert G2P()(normalizer('1 더')) == G2P()('하나 더', normalize=False)
    assert reader._runtime.options == {'cpu_threads': 4, 'batch_size': 16}


@pytest.mark.parametrize('filename', ['runtime/runtime.py', 'model.onnx', 'tokenizer/tokenizer.json'])
def test_bundle_rejects_tampering_before_running_code(tmp_path, filename):
    directory, checksum = bundle(tmp_path)
    (directory / filename).write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='해시'):
        HuggingFaceNumberReader.from_directory(directory, manifest_sha256=checksum)


def test_bundle_rejects_wrong_manifest_and_unlisted_code(tmp_path):
    directory, _ = bundle(tmp_path)
    with pytest.raises(ValueError, match='원장 해시'):
        HuggingFaceNumberReader.from_directory(directory, manifest_sha256='0' * 64)
    (directory / 'runtime/extra.py').write_text('raise AssertionError()', encoding='utf-8')
    with pytest.raises(ValueError, match='원장에 없는'):
        HuggingFaceNumberReader.from_directory(directory)


@pytest.mark.parametrize('name', ['../outside.py', '/outside.py', 'C:/outside.py', 'runtime\\outside.py'])
def test_bundle_rejects_paths_outside_snapshot(tmp_path, name):
    directory, _ = bundle(tmp_path)
    path = directory / 'bundle_manifest.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['files'][name] = {'bytes': 0, 'sha256': '0' * 64}
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError, match='경로'):
        HuggingFaceNumberReader.from_directory(directory)


@pytest.mark.parametrize('revision', ['main', 'v1', 'a' * 7, None, 'g' * 40])
def test_remote_code_requires_fixed_full_revision(revision):
    with pytest.raises(InputValidationError, match='40자'):
        HuggingFaceNumberReader.from_pretrained('owner/model', revision=revision)


def test_hf_download_fetches_code_and_model_at_same_revision(tmp_path, monkeypatch):
    directory, _ = bundle(tmp_path / 'source')
    calls = []
    hub = ModuleType('huggingface_hub')
    constants = ModuleType('huggingface_hub.constants')
    constants.HF_HUB_CACHE = str(tmp_path)
    def snapshot_download(**options):
        calls.append(options)
        destination = Path(options['local_dir'])
        import shutil
        shutil.copytree(directory, destination)
        return str(destination)
    hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, 'huggingface_hub', hub)
    monkeypatch.setitem(sys.modules, 'huggingface_hub.constants', constants)
    reader = HuggingFaceNumberReader.from_pretrained('owner/model', revision='a' * 40, cache_dir=tmp_path / 'cache')
    assert calls[0]['revision'] == 'a' * 40
    assert 'runtime/*.py' in calls[0]['allow_patterns'] and 'model.onnx' in calls[0]['allow_patterns']
    offline = HuggingFaceNumberReader.from_pretrained('owner/model', revision='a' * 40,
                                                      cache_dir=tmp_path / 'cache', local_files_only=True)
    assert len(calls) == 1 and offline.new_run('1 더').decide(0, 1, unit='', site='bare', default='sino') == 'native'


def test_runtime_failure_is_reported_once_and_rules_are_preserved(tmp_path):
    directory, _ = bundle(tmp_path, body='''class NumberReader:
    def __init__(self, *args, **kwargs): pass
    def decide(self, *args, **kwargs): raise RuntimeError("failed")
''')
    reader = HuggingFaceNumberReader.from_directory(directory)
    result = KoreanTTSNormalizer(number_reader=reader).convert('25번 26번')
    assert result.complete
    assert len([d for d in result.diagnostics if d.code == 'number_reader_failed']) == 1
    assert result.normalized_text == KoreanTTSNormalizer()('25번 26번')
