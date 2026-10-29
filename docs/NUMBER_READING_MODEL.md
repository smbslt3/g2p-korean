# 외부 한국어 숫자 읽기

현재 베타의 숫자 전처리 `normalize_numbers(text)`는 입력 그대로 반환하는
더미입니다. `G2P()`가 자동 호출하며 숫자 모델이나 다운로드 없이 동작합니다.
남은 숫자는 보존하고 `unconverted_numeric` 경고와 `complete=False`로 보고합니다.
`G2P()`는 숫자 모델이나 아래 정규화기를 호출하지 않습니다.
아래 내용은 별도 `KoreanTTSNormalizer`의 기존 HF 연결 기능에 관한 문서입니다.

숫자 데이터 정제·패치·학습·평가·증류·양자화와 모델 산출물은 별도
`korean-number-reader` 프로젝트에서 관리한다.
이 프로젝트의 wheel에는 숫자 분류기 계수, 문자 LM, ONNX 모델을 넣지 않는다.

형식이 확정된 시간·금액·날짜·소수·범위·단위는 기존 규칙으로 변환한다.
문맥이 필요한 정수 구간은 호출자가 지정한 `HuggingFaceNumberReader`가 판별한다.
고유어·한자어·자릿수 클래스의 선택과 허용 후보 처리는 외부 묶음이 담당한다.

```python
from g2p_ko import HuggingFaceNumberReader, KoreanTTSNormalizer, G2P

# 공개 전 로컬 준비본을 검수할 때 사용한다.
reader = HuggingFaceNumberReader.from_directory(
    "/path/to/verified-number-reader-bundle",
    cpu_threads=4,
    batch_size=16,
)
normalizer = KoreanTTSNormalizer(number_reader=reader)
g2p = G2P()
pronunciation = g2p(normalizer("사과 3개"))
```

공개 이후에는 `from_pretrained(repo_id, revision=전체_커밋_해시)`를 사용한다.
`g2p-ko[number-reader]` 선택 의존성을 설치한다. 모델과 토크나이저, 추론 코드,
입력 설정을 같은 커밋에서 함께 받고 파일 해시를 확인한 뒤 사용한다.
추론 코드는 실제로 실행되므로 검수한 저장소와 커밋을 지정한다.
외부 숫자 모델 기능은 ONNX Runtime 1.30의 조건에 따라 Python 3.11 이상에서 사용한다.
기본 규칙·G2P는 기존 Python 3.10 이상 지원을 유지한다.

`cache_dir`로 다운로드 위치를 정할 수 있다. `local_files_only=True`는 지정한 커밋의
로컬 묶음만 읽으며 네트워크를 요청하지 않는다. `manifest_sha256`을 지정하면
묶음 원장 자체도 별도로 고정할 수 있다.

기본 생성자는 네트워크에 접근하지 않고 형식 규칙만 적용한다.
이 경우 문맥에 따른 `25번`의 읽기 선택이나 구분자 없는 전화번호 판단은 적용하지 않는다.
지정한 외부 모델이 추론 중 실패하면 규칙으로 복귀하고 상세 결과에
`number_reader_failed` 진단을 한 번 남긴다. 파일 손상이나 로딩 오류는 묶음을 준비하는
시점에 예외로 보고하므로 손상 모델을 정상 모델로 오인하지 않는다.

## HF 배포 파일 구성

- `bundle_manifest.json`: API 버전, 모든 배포 파일의 크기와 SHA-256
- `reader_config.json`, `runtime_model.json`: 클래스 순서, 문맥·토큰 길이, 모델 설정
- `model.onnx`, `tokenizer/`: INT8 모델과 원 토크나이저
- `runtime/`: NumPy·tokenizers·ONNX Runtime을 사용하는 독립 추론 코드
- `DATA_SOURCES.json`, `NOTICE`, `MODEL_LICENSE.md`, `README.md`, `metrics.json`: 출처와 평가·라이선스

학습 프로젝트나 PyTorch, Transformers를 추론에 설치하지 않는다.
G2P 음운 단계는 여전히 Kiwi를 사용하므로 전체 파이프라인의 메모리는 숫자 실행기만의
메모리와 다르다. 현재 HF 저장소는 게시 전이며 로컬 묶음과 모의 다운로드를 검증했다.
