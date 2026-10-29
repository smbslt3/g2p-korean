# G2P API 사용법

## 문자열 API

`G2P(max_length=10_000)`는 숫자가 포함된 문자열도 받습니다. 베타 숫자 전처리
`normalize_numbers(text)`는 입력을 그대로 반환하며 기본 G2P가 자동 호출합니다.
외부 모델을 로드하거나 다운로드하지 않습니다. 숫자가 남으면 예외 대신
`unconverted_numeric` 경고와 `complete=False`를 반환하고 다른 G2P 단계를 계속합니다.
`normalize_numbers(text)`의 직접 호출은 NFC 변환도 하지 않으며 문자열만 받습니다.
별도 `KoreanTTSNormalizer`의 기존 숫자 규칙은 유지합니다.
`lexicon`과 `number_reader` 생성자 인자는 없습니다.
`G2P.__call__(text, normalize=True, pause_boundaries=())`는 표면 발음 문자열을 반환합니다.
`normalize`는 이전 호출 호환용 불리언이며 두 값 모두 입력 검증·NFC·영문 읽기·
한국어 음운 변환을 수행합니다. 숫자·단위 정규화는 자동 실행하지 않습니다.

한글 발음 표기는 현재 초성이 ㅈ·ㅉ·ㅊ일 때 j계 중성의 ㅑ·ㅒ·ㅕ·ㅖ·ㅛ·ㅠ를
ㅏ·ㅐ·ㅓ·ㅔ·ㅗ·ㅜ로 정규화합니다. 연음으로 뒤늦게 생긴 초성에도 적용하며
다른 초성, w계 모음과 ㅐ/ㅔ 구별은 유지합니다. 한국어 음운 단계에 들어온 한글에
적용하는 표기 규칙이며 보호 문자열을 치환하거나 음향 개선을 보장하지 않습니다.

명확한 독립 단어·약어가 공유 읽기표에 있으면 대소문자와 NFKC 대응 표기에 관계없이
정해진 한글 읽기를 적용하고, 이어서 한국어 음운 규칙을 적용합니다. 예를 들어
`NASA`는 `나사`, `laser`는 `레이저`, `coffee`는 `커피`, `TV`는 `티비`로 읽습니다.
내부 `Pipeline.run()`의 rewrite trace에는 치환 규칙 ID `english.conventional.v1`이
기록됩니다. 이 rewrite trace는 공개 `G2PResult`나 진단 report에 노출되지 않습니다.
읽기표는 선별된 명확한 항목이며 모든 영어의 표준 발음을 포괄하지 않습니다.

표에 없거나 여러 읽기가 가능해 표에서 제외한 영문은 알파벳 이름으로 읽습니다. 주소·이메일·
경로·인라인 코드와 식별자에 붙은 문자열 안에서는 등록 단어도 철자화합니다. 예를 들어
`https://NASA.example.com`의 `NASA`도 관용 읽기 대신 알파벳 이름으로 확장하며,
`://`와 `.`은 이름으로 읽지 않고 유지합니다. 전각·수학용 영문과 영문 합자는 대응 ASCII 철자로
해석합니다. 숫자와 한자·미지원 문자는 보존하며 상세 결과에 관련 진단을 남깁니다.

독립 토큰은 연속 영문 구간을 기준으로 판정합니다. `NASA와`, `NAVER검색`처럼
한글과 이어진 표기는 허용하지만 `#NASA`, `NASA_test`, 결합문자·다른 문자 체계가
붙은 식별자에는 관용 읽기를 적용하지 않습니다. 프로토콜 없는 도메인·쿼리와
인용·목록 안의 코드 울타리도 철자 읽기를 유지합니다. URL 기호와 코드 자체를
해석하거나 실행하지 않습니다. `é`, `ß` 등 ASCII 대응이 없는 Latin 문자는
그대로 보존하고 `complete=False`로 보고합니다.

```python
from g2p_ko import G2P

g2p = G2P()
assert g2p("국물") == "궁물"
```

## 명시적인 휴지 경계

`pause_boundaries`는 **NFC 입력에서 영문 읽기로 치환하기 전**의 Python code point
사이 좌표를 받습니다. `__call__()`과 `convert()`가 같은 경계를 사용합니다.
휴지를 넘는 연음·동화·경음화는 차단하지만 형태소 분석과 의미 선택에는 전체 문맥을
유지합니다. 공백과 문장부호는 그대로 보존하며, 경계를 생략하면 기존 이어 읽기를 사용합니다.
경계를 생략한 호출이 모든 인접 단어를 하나의 음운 구간으로 강제하는 것은 아닙니다.
기본 경로는 형태소·문법 경계에 따른 보수적인 적용 조건도 유지합니다.

```python
assert g2p("국물", pause_boundaries=(1,)) == "국물"
assert g2p("옷 안", pause_boundaries=(2,)) == "옫 안"
assert g2p.convert("옷 안", pause_boundaries=(2,)).surface_pronunciation == "옫 안"
```

좌표는 `0`부터 NFC 입력 길이까지의 정수이며 시작·끝과 중복 좌표를 허용합니다.
문자열 컨테이너, 불리언·실수·범위 밖 좌표는 `InputValidationError`입니다.
영문 치환 앞뒤의 경계는 치환된 출력 위치로 옮깁니다. 길이가 바뀌는 치환의 내부
좌표는 대응 위치를 확정할 수 없어 거부합니다. 예를 들어 `AI` 내부의 `1`은
허용하지 않습니다. 배치 API는 이 인자를 받지 않으므로 문장마다 경계가 다르면
단일 입력 메서드를 각각 호출합니다.

## 별도 도구: 한글 전용 TTS 정규화

아래는 별도 정규화 도구인 `KoreanTTSNormalizer`의 사용법입니다. G2P가 자동 호출하지
않으며, 기존의 풍부한 숫자·URL·기호 처리와 사용자 사전은 이 별도 도구가 담당합니다.
일부 영어 관용 읽기 자료는 두 경로가 공유하지만 G2P는 독립 항목에 한해 적용합니다.

```python
from g2p_ko import G2P, KoreanTTSNormalizer

normalizer = KoreanTTSNormalizer(output_policy="tts")
text = normalizer("인증번호 012345를 입력하세요.")
assert text == "인증번호 공 일 이 삼 사 오를 입력하세요."
pronunciation = G2P()(text, normalize=False)
```

`KoreanTTSNormalizer`의 `output_policy`로 반환 문자열의 처리 방식을 선택합니다.

| 값 | 반환 문자열의 처리 방식 |
| --- | --- |
| `"preserve"` — 기본값 | 기존 방식으로 URL 등 보호 토큰과 미확정 표기를 보존 |
| `"tts"` | 성공 시 완성형 한글 `가-힣`, ASCII 공백, `,.!?`만 반환. 미해결 입력은 `ConversionPolicyError` |

`normalize_tts(text)`와 `convert_tts(text)`는 생성자의 정책과 관계없이 해당
호출에 TTS 정책을 적용합니다. 인스턴스의 설정을 변경하지 않습니다.
`normalize_many()`와 `convert_many()`는 생성자의 정책을 따릅니다.

지원하는 장식과 인라인 마크업은 원문 좌표를 보존하며 먼저 정리하므로
`**2**시`도 `두 시`로 읽습니다. 숫자 경계나 부호의 의미가 바뀔 수 있는 장식은
임의로 삭제하지 않습니다. 이어서 음수·소수·범위·통화·단위의 의미를 읽고
출력 문장부호를 정리합니다. 콜론·세미콜론은 쉼표로 바꿉니다.
알려진 영어 관용 읽기는 유지하고, 미등록 ASCII 영문은 글자 이름으로 읽습니다.
URL·이메일은 영문자·숫자·구분기호의 이름으로 읽습니다. 한자나
의미를 확정하지 못한 표기는 조용히 삭제하지 않습니다.

`2박3일`, `42칸`, `2호선` 같은 일반 수량과 `2만 3천 400원`,
`1억 2천만 원` 같은 복합 금액을 처리합니다. 한글 배율을 가진 수량은 값 손실 없이
합산하며 큰 단위와 작은 단위의 순서가 잘못되면 미해결로 남깁니다.

`convert_tts()`와 TTS 정책의 `convert()`는 `NormalizationResult`를 반환합니다.
`complete=False`이면 `normalized_text`에 미처리 문자가 남을 수 있으므로 TTS에
전달하지 않습니다. `on_ambiguous="error"`를 별도로 선택했다면 처리 중에도 예외가
발생할 수 있습니다. 문자열 API는 `on_ambiguous="preserve"`를 선택해도 미완료
결과를 성공 문자열로 반환하지 않습니다.

빈 입력이나 장식만 있는 입력은 빈 문자열이 될 수 있습니다. `complete=True`는
지원하는 변환이 완료되었다는 뜻이며, 문맥상 발음 정확도를 보증하는 점수는 아닙니다.
정규화는 `먹었다`와 같은 표기를 유지합니다. `머걷따`와 같은 음운 변화가 필요하면
위 예처럼 G2P를 이어서 호출합니다.

## 상세 API

`G2P.convert(text, normalize=True, pause_boundaries=())`는 불변 `G2PResult`를 반환합니다.

| 필드 | 의미 |
| --- | --- |
| `source` | 호출자가 전달한 원문 |
| `normalized_text` | NFC와 영문 관용 읽기 또는 철자 읽기를 마친 음운 단계 입력 |
| `surface_pronunciation` | 한국어 음운 규칙까지 적용한 결과 |
| `diagnostics` | 좌표계별 단계 진단 report |
| `complete` | 미처리 입력이나 규칙 적용 실패 진단이 없는지 여부. 발음 정확도 점수는 아님 |

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
  항상 `result.source`와 같으며, 현재 이 report의 진단 목록은 비어 있습니다.
- `result.diagnostics.pronunciation.source`는 원문을 NFC로 바꾼 문자열입니다.
  영문 철자화 전 좌표이므로 `normalized_text`의 좌표와 다를 수 있습니다.
- 각 `Diagnostic.source_spans`는 같은 `DiagnosticReport.source`에 대한 Python
  Unicode code point 반열림 구간 `[start:end]`입니다.
- `SourceSpan.surface`는 해당 source를 같은 범위로 자른 문자열입니다.

미변환 숫자에는 `unconverted_numeric` 진단이 남습니다. 분석기 실패와 미지원
문자도 `complete=False`로 보고합니다. 문자열 API는 같은 보존 문자열을 반환하므로,
완료 여부가 중요한 호출자는 `convert()`의 상태를 확인합니다. 알려진 미처리 조건이
없다는 뜻이며 미등록 어휘·동형이의어의 발음 정확성을 증명하지는 않습니다.

## 정규화문과 표면 발음 정렬

완료된 결과는 다음을 보장합니다.

```python
len(result.normalized_text) == len(result.surface_pronunciation)
```

좌표는 Python 문자열의 Unicode code point 기준입니다. 같은 인덱스의 현대 한글
음절끼리 대응하고, 공백·구두점·보존 문자는 같은 인덱스에 유지됩니다. UTF-8 byte
offset이나 사용자 인식 grapheme cluster 기준은 아닙니다.

현재 엔진은 불완전 결과에도 같은 구조를 유지하지만, API에서 제공하는 문자 위치 대응은
`complete=True`인 결과를 대상으로 합니다. 향후 문자 삽입·삭제 규칙이 필요해지면
별도 alignment API와 버전 변경으로 다룹니다.

## 원문 좌표의 발음 정렬

`convert_with_alignment()`은 한 번의 변환에서 기존 `G2PResult`와 정렬 정보를 함께
반환합니다. 기존 `convert()`, 문자열 반환과 `G2PResult.to_dict()`의 형식은 같습니다.

```python
from g2p_ko import G2P

aligned = G2P().convert_with_alignment("AI 국물")
assert aligned.result.surface_pronunciation == "에이아이 궁물"
assert aligned.alignment.extract_target(0, 2).pronunciation == "에이아이"
assert aligned.alignment.extract_target(3, 5).pronunciation == "궁물"
assert not aligned.alignment.extract_target(0, 1).aligned
```

정렬의 source 좌표는 전달한 원문 문자열의 Python code point이고, output 좌표는
`surface_pronunciation`의 Python code point입니다. NFC 조합과 영문 치환을 실제
변환 근거로 연결합니다. 예를 들어 원문 `가`의 두 code point는 출력 `가` 하나에
대응합니다. 영문 읽기와 정준 조합은 원자적 작업 구간으로 묶어, 전체 구간 추출은
허용하고 내부 일부만 요청하면 `partial_operation` 사유로 정렬 불가를 반환합니다.

`alignment.status`는 `exact`, `coarse`, `unavailable`이며 `result.complete`와
독립적입니다. `entries`는 출력 범위, 원문 span, 관계, 단계·규칙 근거와 정밀도를
보관합니다. `alignment.to_dict()`로 직렬화할 수 있습니다. 근거가 없는 대응은
`unavailable`로 남습니다. `extract_target(start, end)`은 성공 시 발음과 출력 좌표를,
실패 시 `aligned=False`와 `reason`을 제공합니다. 음운 단계의 대응 단위는 출력
음절이며, 받침이 다음 음절로 이동하면 이동 후의 출력 음절 위치를 따라 추출합니다.

`pause_boundaries`는 기존과 같이 NFC 입력의 좌표입니다. 원문 정렬 좌표와 휴지
좌표는 NFC 조합이 있는 입력에서 서로 다를 수 있습니다. 장음·IPA·새 축약 규칙은
이 정렬 API의 기능 범위에 포함되지 않습니다.

## 원문 좌표로 읽기 조건 선택

`convert_with_reading_conditions()`는 단어 경계의 일반 연음, 한 마디 묶음 또는
휴지를 명시적으로 선택합니다. `ReadingBoundary.offset`은 **전달한 원문**의 Python
code point 사이 좌표입니다. 기존 `pause_boundaries`의 NFC 좌표와 구별합니다.

```python
from g2p_ko import G2P, ReadingBoundary

g2p = G2P()
ordinary = g2p.convert_with_reading_conditions(
    "솜 이불", reading_conditions=(ReadingBoundary(2, "ordinary_liaison"),)
)
grouped = g2p.convert_with_reading_conditions(
    "솜 이불", reading_conditions=(ReadingBoundary(2, "one_madi"),)
)
assert ordinary.aligned.result.surface_pronunciation == "소 미불"
assert grouped.aligned.result.surface_pronunciation == "솜 니불"
```

`ordinary_liaison`은 선택한 경계에서 단어 ㄴ 첨가를 억제하고 적격 받침을 이어
읽습니다. `one_madi`는 기존 문법·모음 조건을 만족하는 단어 ㄴ 첨가 경로를
선택하며, 부적격 경계에 ㄴ을 만들지 않습니다. `pause`는 그 경계의 음운 연결을
막고 분석·의미 판단에는 기존 전체 문맥을 유지합니다. 다른 경계의 기본 동작은
유지합니다.

비휴지 관계는 현대 한글 사이 ASCII 공백열에서만 지정할 수 있습니다. 같은
공백열의 여러 offset은 같은 물리 경계입니다. 상충하는 관계와 기존 휴지와의 충돌,
NFC 조합 원자 내부와 길이가 바뀌는 영문 치환 내부의 좌표는 거부합니다.
HARD·보호 경계를 열지 않으며, 형태소 근거가 부족하면 실행을 미확인으로 남깁니다.

반환값의 `aligned`는 같은 변환의 결과와 원문 정렬이고, `boundary_executions`는
요청·대응 좌표·실제 규칙 적용·장벽 또는 미확인 사유를 담습니다. 선택한 조건과
실제 소리 변화는 별개입니다. 조건은 호출자의 읽기 지시이며 원문 화자의 운율을
관측한 정보가 아닙니다. 빈 조건은 기존 정렬 변환과 같은 결과를 반환합니다.

## 지역 모음 변이

`convert_with_variants(text, normalize=True, pause_boundaries=(),
profile="standard_vowels_v1")`는 기존 변환·정렬과 선택 가능한 지역 모음 대안을
`G2PVowelVariantResult`로 반환합니다. 기본 출력은 기존 API의 선택을 그대로 사용합니다.

```python
from g2p_ko import G2P

variants = G2P().convert_with_variants("협의")
assert variants.aligned.result.surface_pronunciation == "혀븨"
assert variants.render({0: 0}) == "혀비"
assert variants.render() == variants.aligned.result.surface_pronunciation
```

`slots`의 각 항목은 이 결과 안에서 유효한 `slot_id`, 원문 `source_span`, 출력 좌표,
기본 음절, `alternatives`, 형태소 역할과 규칙 근거를 보관합니다.
`render({slot_id: alternative_index})`는 반환된 대안 인덱스만 선택합니다. 생략한 슬롯은
기본 출력으로 유지하며, 잘못된 ID·인덱스·불리언·겹치는 선택은 `ValueError`입니다.
렌더링은 변환이나 분석을 다시 실행하지 않고, 문장 전체 조합을 열거하지 않습니다.

현재 프로필은 정준 표기 입력의 표준 발음법 제5항에 따른 지역 모음 변이 범위입니다.
조사 `의/에`, 어휘 내부 비첫음절 `의/이`, 조건에 맞는 `ㅖ/ㅔ`를 원래 음절과 형태소
역할에 연결합니다. 연음으로 생긴 초성과 원래 초성을 구분하며, 강제 모음 변화의
역전이나 `예/례`의 일괄 변이를 생성하지 않습니다.

통짜·분할·병합 분석에서도 원문 전체가 정확히 대응하고 명사 계열의 어휘 구성과
후행 조사 순서가 확인되면 같은 단어 소유를 사용합니다. 검증된 접두·접미 성분을
포함할 수 있으며, 형태소 첫머리를 단어 첫음절로 간주하지 않습니다. 어휘 내부의
`의`와 조사 `의`는 서로 다른 허용 모음과 소유 범위를 갖습니다.

병합 태그라는 이유만으로 승인하지 않습니다. 태그와 형태소 목록의 불일치, 누락·겹침,
축약이나 미지원 역할 순서는 `unknown`입니다. 공백·인용 경계를 넘어 어휘를 붙이거나
부사·관형사의 단순 인접을 복합어로 간주하지 않습니다. 기본 변환의 모음이 해당 지역
규칙의 허용 범위 밖이면 올바른 보조 분석만으로 이를 역전시키지 않습니다.

원문 좌표는 NFC 조합 전 Python code point입니다. 확정한 단일 출력 음절과 원문
범위의 실제 정렬을 사용하며, 분석·역할·정렬이 미확정인 경우 `decisions`에
`unknown`과 사유를 기록합니다. `coverage_status`는 이 프로필 범위의
`scoped_supported` 또는 `partial_unknown`이며, 기존 파이프라인의 `complete`와
구별합니다.

기본 변환·정렬은 한 번 실행합니다. 모음 후보가 있으면 별도 보조 형태소 분석을 한 번
시도하고 `auxiliary_analysis_calls` 및 `analysis_provenance`에 기록합니다.
기본 파이프라인 내부 분석을 합한 총 호출 횟수를 뜻하지 않습니다.
`to_dict()`의 별도 스키마는 `g2p_local_vowel_variants.v1`입니다.
이 모음 변이 프로필은 문장 운율에 따른 ㄴ 첨가, 화자의 구어 복원, 외래어 관용 발음,
장음과 전체 발음 변이의 완전 열거를 포함하지 않습니다. 장음은 아래의 별도 API에서
등록한 어근 범위로 제공합니다.

## 선택형 장단음 정보

`convert_with_vowel_length(text, normalize=True, pause_boundaries=(),
profile="standard_vowel_length_v1")`는 기존 변환·정렬과 장단음 판정을
`G2PVowelLengthResult`로 반환합니다. 기본 한글 문자열에 장음 기호를 삽입하지 않습니다.

```python
from g2p_ko import G2P

converter = G2P()
length = converter.convert_with_vowel_length("알겠어요")
decision, = length.decisions
assert decision.value == "long"
assert decision.status == "supported"
assert decision.lemma == "알다"
assert length.aligned.result.to_dict() == converter.convert("알겠어요").to_dict()
```

현재 등록 어근은 `알다·좋다·없다·사람·마음·신다·끌다` 일곱 개입니다. 활용 표면형
목록 대신 어근의 장단 속성과 정확한 어근 범위·후행 성분을 검증합니다. 명사 사람·마음은
단독과 조사열에서 어근의 길이를 유지합니다. 용언은 실제 첫 어미를 확인하며 모음 어미
앞 단음화 규칙을 단음절 어간에만 적용합니다. `알겠어요`와 `알았겠어요`는 각각 장음과
단음이고, `끌다·좋다·없다`의 유지 예외와 확인된 ㄹ 탈락·어미 뒤 조사열을 처리합니다.
복합어·파생어·축약·계사 및 미등록 어휘의 장단은 이 범위 밖입니다.

각 `VowelLengthDecision`은 `value`(`long`, `short`, `unknown`), `status`
(`supported`, `unknown`, `unsupported`), 표제어·품사·어휘 ID와 규칙·근거·사유를
보관합니다. 분석이나 정렬이 불확실한 것을 단음으로 바꾸지 않습니다. 예를 들어 고립된
`아는·아니`가 동사 `알다`로 분석되지 않으면 그 표면형만 보고 장음을 강제하지 않습니다.
눈·밤도 같은 표기와 품사 안에서 뜻에 따라 장단이 달라, 뜻의 근거가 없으면 `unknown`입니다.

`owner_source_span`은 단어 소유 범위, `nucleus_source_span`과
`nucleus_source_atoms`는 어근 모음의 원문 근거이며 NFC 조합 전 Python code point
좌표입니다. `output_nucleus_syllable_span`은 출력 문자열의 모음 소유 음절 범위입니다.
받침이 이동했다는 근거와 모음 핵의 위치를 구분합니다. 다른 단어의 영문 확장으로
전체 정렬이 `coarse`여도 해당 모음의 정확한 지역 대응이 입증되면 판정할 수 있습니다.
모음 대응 자체가 부정확하면 `unknown`입니다.

선언된 음운 규칙의 정확한 1:1 모음 변화는 원문에 결속한 모음핵 대응을 유지합니다.
뒤에서 초성·받침·경음화만 바뀌어도 앞서 확보한 모음 근거는 보존합니다. 실제 모음이
바뀌면 해당 규칙의 전달 선언을 확인하며, 미지원 모음 변화 뒤 끝점이 원래 모음과
같아졌다는 이유만으로 근거를 복원하지 않습니다. 이 대응 개선이 미등록 어휘의
장단음을 지원 상태로 바꾸지는 않습니다.

`coverage_status`는 `scoped_supported`, `partial_unknown`, `partial_unsupported`,
`no_applicable_nuclei` 중 하나이며 기존 파이프라인의 `complete`와 별개입니다.
`to_dict()`의 스키마는 `g2p_vowel_length.v1`입니다. 규범 장단 정보이며 실제 화자가
장음을 실현했다는 뜻은 아닙니다.

직렬화의 `scope`는 `registered_nominal_roots_and_verified_predicate_inflections`입니다.
`actual_ending`은 첫 실제 어미만 기록하므로 `알겠어요`에서는 `겠`이며, 이전의 전체
어미열 `겠어요`와 구별됩니다. 명사에서는 `None`입니다. 필드 형식과 profile ID는 유지합니다.
명시적 휴지는 기존 형태·의미 문맥을 유지하며, 이 API가 별도 보호 구간·HARD 분절 정보
전체를 소비해 제외한다고 보장하지 않습니다.

기본 변환·정렬은 한 번 실행하고 필요한 보조 분석을 최대 한 번 시도합니다.
`auxiliary_analysis_calls`는 이 보조 호출만 세며, 기본 파이프라인 내부의 전체 분석
호출 수를 뜻하지 않습니다. 기존 문자열·변환·정렬·모음 변이 API의 형식은 유지합니다.

## 입력과 인스턴스 수명

- 빈 문자열을 허용합니다.
- 기본 원문 제한은 10,000 code point이며 `max_length`로 조정합니다.
- `normalize`에는 `bool`만 허용합니다.
- 동일 인스턴스의 반복 호출과 여러 스레드의 동시 호출은 결정적입니다.
- Python 스레드를 처리량 최적화 수단으로 보장하지 않습니다.
- 여러 프로세스를 사용할 때는 worker마다 인스턴스를 생성합니다.

숫자 변환은 외부 프로젝트의 앞단 책임입니다. 별도 도구인
`KoreanTTSNormalizer(number_reader=...)`의 기존 HF 연결은
[외부 모델 연결 방법](NUMBER_READING_MODEL.md)에 설명되어 있습니다.
