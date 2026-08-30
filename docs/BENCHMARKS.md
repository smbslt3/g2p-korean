# 성능 벤치마크

`tools/benchmark.py`는 CPU 전용 경로의 import, 인스턴스 생성, 지연 초기화,
cold workload와 warm workload를 JSON으로 기록합니다. 시간 표본과 메모리 표본은
서로 다른 호출이며, 메모리는 `tracemalloc`으로 관찰한 Python 할당만 포함합니다.
native RSS는 측정하지 않습니다.

## 측정 의미

- 각 시나리오는 부모 및 다른 시나리오와 전역 상태를 공유하지 않는 새 Python
  프로세스에서 실행합니다.
- cold의 각 반복은 시간용 프로세스와 메모리용 프로세스를 각각 새로 시작합니다.
  각 프로세스는 `factory()(text)`를 정확히 한 번 호출하므로 Kiwi와 숫자 모델의
  프로세스 전역 캐시를 이전 표본에서 물려받지 않습니다.
- cold workload는 Python 프로세스 시작과 `g2p_ko` import를 타이머에 포함하지
  않으며 운영체제 파일 캐시까지 비우지는 않습니다. `cold_import`도 인터프리터
  시작은 제외하고 패키지 import 자체만 측정합니다.
- `kiwi_morphology.activation`은 새 `G2P`의 첫 형태소 처리와 Kiwi 지연 생성을
  cold 반복으로 측정합니다. 이 시나리오의 workload에는 별도 cold 값을 만들지
  않습니다.
- warm은 입력 크기마다 인스턴스 하나를 만들고 같은 입력으로 한 번 준비한 다음,
  해당 인스턴스와 시나리오 프로세스를 모든 반복에서 재사용합니다.
- `construction`은 시나리오 프로세스에서 인스턴스 생성만 측정하며 변환은 호출하지
  않습니다. `cold_import`는 반복과 측정 단계마다 별도 프로세스를 사용합니다.

## 재현

잠금 파일과 같은 환경을 준비한 뒤 JSON 원본을 보관합니다.

```powershell
uv sync --dev --locked
uv run --no-sync python tools\benchmark.py --repeats 5 --output benchmarks\benchmark.json
```

비교할 때는 같은 Python, 운영체제, CPU, 입력 크기와 반복 수를 사용하고 JSON의
개별 `samples`도 함께 확인합니다. 다른 부하가 있는 동안 얻은 수치나 서로 다른
cold/warm 항목을 직접 비교하지 않습니다.
