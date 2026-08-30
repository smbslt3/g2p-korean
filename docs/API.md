# 공개 G2P API 계약

## 문자열 API

`G2P.__call__(text, normalize=True)`는 기존과 같이 표면 발음 문자열만 반환합니다.
`normalize=False`는 TTS 노멀라이저를 생략하지만 입력 검증과 NFC는 유지합니다.
선택적 정규화 뒤의 후단 Pipeline은 상세 경로와 같은 라우팅·보호·영문 처리·한국어
음운 코어를 거친 뒤 표면 발음 문자열만 반환합니다.

```python
from g2p_ko import G2P

g2p = G2P()
assert g2p("국물") == "궁물"
```

## 상세 API

`G2P.convert(text, normalize=True)`는 불변 `G2PResult`를 반환합니다.

| 필드 | 의미 |
| --- | --- |
| `source` | 호출자가 전달한 원문 |
| `normalized_text` | 모든 어휘 치환을 마친 음운 단계 입력 |
| `surface_pronunciation` | 한국어 음운 규칙까지 적용한 결과 |
| `diagnostics` | 좌표계별 단계 진단 report |
| `complete` | 모든 필수 단계가 읽기를 확정했는지 여부 |

`__call__()`과 `convert()`의 발음 결과는 항상 같습니다.

```python
assert g2p(text, normalize=flag) == (
    g2p.convert(text, normalize=flag).surface_pronunciation
)
```

`G2PResult`, `G2PDiagnostics`, `DiagnosticReport`는 최상위 `g2p_ko`에서 import할
수 있으며 모두 `to_dict()`를 제공합니다.

## 배치 API

```python
pronunciations = g2p.pronounce_many(texts, normalize=True)
results = g2p.convert_many(texts, normalize=True)
```

- `pronounce_many()`의 반환형은 `Iterator[str]`입니다.
- `convert_many()`의 반환형은 `Iterator[G2PResult]`입니다.
- 두 iterator는 입력 순서를 보존하며 입력 전체를 미리 모으지 않습니다.
- 바깥 `texts`가 `str` 또는 `bytes`이거나 iterable이 아니면 메서드 호출 시
  `InputValidationError`를 발생시킵니다. 문자열 하나는 한 항목짜리 batch로
  암묵적으로 취급하지 않습니다.
- `normalize`가 `bool`이 아니면 메서드 호출 시 `InputValidationError`를
  발생시킵니다. 이 검증은 입력 iterator를 소비하기 전에 끝납니다.
- 각 항목의 문자열 형식·길이·surrogate 검증은 해당 결과를 `next()`로 요청할 때
  수행합니다. 원본 iterator가 발생시킨 예외도 같은 시점에 그대로 전파합니다.
- 처리는 항목별 순차 실행입니다. 내부 병렬 처리나 뒤 항목 선소비를 하지 않습니다.

`KoreanTTSNormalizer.normalize_many()`와 `convert_many()`도 같은 iterator 스타일을
사용하지만 정규화 단계에서 끝납니다. `G2P.pronounce_many()`와
`G2P.convert_many()`는 영어 처리와 한국어 표면 발음까지 수행하므로 서로 대체되는
API가 아닙니다.

## 진단 좌표

진단은 서로 다른 단계의 좌표를 한 목록에 섞지 않습니다.

- `result.diagnostics.normalization.source`는 정규화 진단의 좌표 기준 문자열입니다.
  `normalize=True`에서는 `result.source`와 같습니다.
- `result.diagnostics.pronunciation.source`는 발음 단계가 받은 문자열입니다.
- 각 `Diagnostic.source_spans`는 같은 `DiagnosticReport.source`에 대한 Python
  Unicode code point 반열림 구간 `[start:end]`입니다.
- `SourceSpan.surface`는 해당 source를 같은 범위로 자른 문자열입니다.

`complete`는 단순히 경고 유무로 계산하지 않습니다. 분석기 실패 후 안전한 규칙으로
폴백한 진단은 경고를 남기면서도 완료될 수 있습니다. 반대로 보존된 미지원 입력이나
확정할 수 없는 음운 규칙이 있으면 `complete=False`입니다.

## 정규화문과 표면 발음 정렬

완료된 결과는 다음을 보장합니다.

```python
len(result.normalized_text) == len(result.surface_pronunciation)
```

좌표는 Python 문자열의 Unicode code point 기준입니다. 같은 인덱스의 현대 한글
음절끼리 대응하고, 공백·구두점·보존 문자는 같은 인덱스에 유지됩니다. UTF-8 byte
offset이나 사용자 인식 grapheme cluster 기준은 아닙니다.

현재 엔진은 불완전 결과에도 같은 구조를 유지하지만, 공개된 downstream 정렬 계약은
`complete=True`인 결과를 대상으로 합니다. 향후 문자 삽입·삭제 규칙이 필요해지면
별도 alignment API와 버전 변경으로 다룹니다.

## 입력과 인스턴스 수명

- 빈 문자열을 허용합니다.
- 기본 원문 제한은 10,000 code point이며 `max_length`로 조정합니다.
- `normalize`에는 `bool`만 허용합니다.
- 동일 인스턴스의 반복 호출과 여러 스레드의 동시 호출은 결정적입니다.
- Python 스레드를 처리량 최적화 수단으로 보장하지 않습니다.
- 여러 프로세스를 사용할 때는 worker마다 인스턴스를 생성합니다.
