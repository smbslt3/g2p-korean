"""기본 배포물의 선택 의존성과 외부 모델 제외 계약을 검증한다."""
from pathlib import Path
import tarfile
from io import BytesIO
import zipfile

import pytest

from tools.check_artifacts import check_artifact, _PROJECT_VERSION

ROOT = Path(__file__).resolve().parents[1]


def write_artifact(path, *, extra=None, omit=None):
    metadata = ('Metadata-Version: 2.4\nName: g2p-ko\n'
                f'Version: {_PROJECT_VERSION}\nLicense-Expression: MIT\n'
                'License-File: LICENSE\nLicense-File: NOTICE\nProvides-Extra: number-reader\n'
                'Requires-Dist: kiwipiepy==0.24.1\n'
                'Requires-Dist: huggingface-hub<2,>=0.34; extra == "number-reader"\n'
                'Requires-Dist: numpy<3,>=2; extra == "number-reader"\n'
                'Requires-Dist: tokenizers<1,>=0.21; extra == "number-reader"\n'
                'Requires-Dist: onnxruntime<2,>=1.30; python_version >= "3.11" and extra == "number-reader"\n')
    files = {'g2p_ko/__init__.py': '', 'g2p_ko/py.typed': '',
             f'g2p_ko-{_PROJECT_VERSION}.dist-info/METADATA': metadata,
             f'g2p_ko-{_PROJECT_VERSION}.dist-info/licenses/LICENSE': (ROOT / 'LICENSE').read_text(encoding='utf-8'),
             f'g2p_ko-{_PROJECT_VERSION}.dist-info/licenses/NOTICE': (ROOT / 'NOTICE').read_text(encoding='utf-8')}
    files.update(extra or {})
    if omit:
        files.pop(omit)
    if path.suffix == '.whl':
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in files.items():
                archive.writestr(name, value)
    else:
        with tarfile.open(path, 'w:gz') as archive:
            for name, value in files.items():
                if name.endswith('/METADATA'):
                    name = 'PKG-INFO'
                if '/licenses/' in name:
                    name = name.rsplit('/', 1)[-1]
                content = value.encode('utf-8')
                info = tarfile.TarInfo('g2p-ko-source/' + name)
                info.size = len(content)
                archive.addfile(info, BytesIO(content))


@pytest.mark.parametrize('filename', ['sample.whl', 'sample.tar.gz'])
def test_artifact_accepts_external_number_model_dependency_contract(tmp_path, filename):
    path = tmp_path / filename
    write_artifact(path)
    assert check_artifact(path)['ok']


@pytest.mark.parametrize('name', ['g2p_ko/data/number_reading_model.json', 'g2p_ko/data/model.onnx',
                                 'data/train.tsv', 'data/model.safetensors', 'g2p_ko/__pycache__/engine.pyc'])
def test_artifact_rejects_model_data_and_cache_in_source_distribution(tmp_path, name):
    path = tmp_path / 'sample.whl'
    write_artifact(path, extra={name: '{}'})
    assert not check_artifact(path)['ok']


def test_artifact_rejects_missing_foundation_and_broken_archive(tmp_path):
    path = tmp_path / 'sample.whl'
    write_artifact(path, omit='g2p_ko/py.typed')
    assert not check_artifact(path)['ok']
    path.write_bytes(b'not a zip archive')
    assert not check_artifact(path)['ok']
