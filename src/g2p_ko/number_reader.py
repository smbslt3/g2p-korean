"""Hugging Face의 고정된 모델·추론 코드 묶음을 숫자 판별기로 연결한다."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
from threading import Lock

from .errors import BackendUnavailableError, InputValidationError

_MODULE_LOCK = Lock()
_MODULES = {}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _verify_bundle(directory, expected_sha256=None):
    """코드를 실행하기 전에 묶음의 계약과 모든 배포 파일 해시를 확인한다."""
    manifest_path = directory / 'bundle_manifest.json'
    checksum = _sha256(manifest_path)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError('숫자 모델 묶음의 원장 해시가 다릅니다.')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != 1 or manifest.get('api_version') != 1
            or manifest.get('runtime_module') != 'runtime/__init__.py'):
        raise ValueError('지원하지 않는 숫자 읽기 배포 계약입니다.')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('숫자 모델 묶음의 파일 목록이 없습니다.')
    required = {'runtime/__init__.py', 'runtime/runtime.py', 'reader_config.json',
                'runtime_model.json', 'model.onnx', 'tokenizer/tokenizer.json'}
    if not required <= files.keys():
        raise ValueError('숫자 모델 묶음에 필수 파일이 없습니다.')
    for name, entry in files.items():
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or '\\' in name or ':' in name
                or relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name):
            raise ValueError('배포 파일 경로가 묶음 밖을 가리킵니다.')
        path = directory.joinpath(*relative.parts)
        if (not path.is_file() or path.stat().st_size != entry.get('bytes')
                or _sha256(path) != entry.get('sha256')):
            raise ValueError(f'숫자 모델 배포 파일의 크기 또는 해시가 다릅니다: {name}')
    actual_code = {path.relative_to(directory).as_posix() for path in (directory / 'runtime').rglob('*.py')}
    if not actual_code <= files.keys():
        raise ValueError('원장에 없는 추론 코드가 있습니다.')
    return manifest, checksum


class HuggingFaceNumberReader:
    """학습 저장소를 설치하지 않고 HF에서 받은 코드로 숫자 문맥을 판별한다."""

    def __init__(self, runtime):
        if not callable(getattr(runtime, 'decide', None)):
            raise InputValidationError('숫자 읽기 실행기는 decide 메서드를 제공해야 합니다.')
        self._runtime = runtime

    @classmethod
    def from_directory(cls, model_dir, *, manifest_sha256=None, cpu_threads=4, batch_size=16):
        """검수된 로컬 배포 묶음을 불러오며 네트워크에는 접근하지 않는다."""
        if sys.version_info < (3, 11):
            raise BackendUnavailableError('외부 숫자 모델의 ONNX Runtime은 Python 3.11 이상이 필요합니다.')
        directory = Path(model_dir).resolve()
        _, checksum = _verify_bundle(directory, manifest_sha256)
        # 서로 다른 모델 묶음의 같은 모듈 이름이 충돌하지 않도록 격리한다.
        name = '_g2p_number_bundle_' + checksum
        with _MODULE_LOCK:
            module = _MODULES.get(name)
            if module is None:
                spec = importlib.util.spec_from_file_location(
                    name, directory / 'runtime/__init__.py',
                    submodule_search_locations=[str(directory / 'runtime')])
                if spec is None or spec.loader is None:
                    raise BackendUnavailableError('숫자 모델의 추론 코드를 불러올 수 없습니다.')
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    for key in tuple(sys.modules):
                        if key == name or key.startswith(name + '.'):
                            sys.modules.pop(key, None)
                    raise
                _MODULES[name] = module
        return cls(module.NumberReader(directory, cpu_threads=cpu_threads, batch_size=batch_size))

    @classmethod
    def from_pretrained(cls, repo_id, *, revision, cache_dir=None, local_files_only=False,
                        manifest_sha256=None, cpu_threads=4, batch_size=16):
        """지정한 HF 커밋의 모델과 추론 코드를 함께 내려받는다."""
        if not isinstance(revision, str) or re.fullmatch(r'[0-9a-f]{40}', revision) is None:
            raise InputValidationError('추론 코드와 모델을 고정하는 전체 HF 커밋 해시 40자가 필요합니다.')
        if not isinstance(repo_id, str) or re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo_id) is None:
            raise InputValidationError('HF 저장소는 소유자/이름 형식이어야 합니다.')
        if sys.version_info < (3, 11):
            raise BackendUnavailableError('외부 숫자 모델의 ONNX Runtime은 Python 3.11 이상이 필요합니다.')
        try:
            from huggingface_hub import snapshot_download
            from huggingface_hub.constants import HF_HUB_CACHE
        except ImportError as error:
            raise BackendUnavailableError('HF 숫자 모델 사용에는 g2p-ko[number-reader] 설치가 필요합니다.') from error
        # 로컬 묶음은 일반 파일로 받아 토크나이저와 ONNX의 상대 경로를 유지한다.
        cache_root = Path(cache_dir) if cache_dir is not None else Path(HF_HUB_CACHE) / 'g2p_number_bundles'
        identity = hashlib.sha256(repo_id.encode('utf-8')).hexdigest()[:16]
        directory = cache_root / identity / revision
        if local_files_only:
            return cls.from_directory(directory, manifest_sha256=manifest_sha256,
                                      cpu_threads=cpu_threads, batch_size=batch_size)
        snapshot_download(repo_id=repo_id, revision=revision, repo_type='model',
                          local_dir=directory, allow_patterns=[
                              'bundle_manifest.json', 'reader_config.json', 'runtime_model.json',
                              'model.onnx', 'runtime/*.py', 'tokenizer/*', 'README.md',
                              'NOTICE', 'LICENSE', 'MODEL_LICENSE.md', 'DATA_SOURCES.json', 'metrics.json'])
        return cls.from_directory(directory, manifest_sha256=manifest_sha256,
                                  cpu_threads=cpu_threads, batch_size=batch_size)

    def new_run(self, text):
        return NumberReadingRun(self._runtime, text)


class NumberReadingRun:
    """문장별 실패 상태를 분리하고 규칙 기본값과 같은 선택은 생략한다."""
    def __init__(self, runtime, text):
        self._runtime = runtime
        self._text = text
        self._failure = None
        self._reported = False

    def decide(self, start, end, *, unit, site, default, context_end=None):
        if self._failure is not None:
            return None
        try:
            selected = self._runtime.decide(self._text, start, end, unit=unit, site=site,
                                            default=default, context_end=context_end)
            if selected not in {None, 'native', 'sino', 'digitwise'}:
                raise ValueError('숫자 실행기가 유효하지 않은 클래스를 반환했습니다.')
            return None if selected == default else selected
        except Exception as error:
            self._failure = ('number_reader_failed', f'외부 숫자 읽기에 실패하여 규칙을 사용합니다: {error}')
            return None

    def take_failure(self):
        if self._reported or self._failure is None:
            return None
        self._reported = True
        return self._failure
