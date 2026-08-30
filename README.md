# g2p-ko

한국어 TTS 입력을 발화형으로 정규화하고 표면 발음으로 변환합니다.

[English](README.en.md)

## 기능

- 숫자·단위·날짜·시간·통화·분수·약어 정규화
  - `3kg~5kg` → `삼 킬로그램에서 오 킬로그램` / `2/5kg` → `오분의 이 킬로그램` / `6,000원` → `육천 원`
- 내장형 통계 모델로 문맥에 따라 달라지는 숫자 읽기 판단
  - 규칙으로 확정하기 어려운 숫자만 대상으로 고유어·한자어·낱자리 읽기 중 하나를 고릅니다. 규칙이 이미 확정했거나 모델의 확신이 부족하면 규칙 결과를 유지합니다.
  - `영화를 3번 봤다.` → `영화를 세 번 봤다.`
  - `3번 창구로 가세요.` → `삼 번 창구로 가세요.` (모델 판별)
  - `우편번호는 54130입니다.` → `우편번호는 오 사 일 삼 공입니다.` (모델 판별)
- 표준 발음법에 근거한 한국어 음운 규칙 적용
  - `국물` → `궁물`, `같이` → `가치`
  - 외부 발음 사전을 포함하지 않으며 일반 규칙과 공식 고시의 비모호한 정확 일치
    예를 사용합니다.
- NASA·KIA·TV 같은 관용 읽기 우선 처리
  - `NASA` → `나사`, `KIA` → `기아`, `FIFA와 TV` → `피파와 티비`
- 나머지 영어를 알파벳 이름으로 변환
  - `ABC` → `에이비씨`, `PYTHON` → `피와이티에이치오엔`, `TEST` → `티이에스티`
- 불확실하거나 지원하지 않는 입력 보존
  - `A-1` → `A-1`, `1-3개` → `1-3개`, `192.168.0.1` → `192.168.0.1`
- 사용자 사전 지원
  - `NAVER` → `네이버`, `RIDI` → `리디`, `DAANGN` → `당근`

숫자 읽기 모델은 숫자의 길이와 값, 단위, 앞뒤 Kiwi 형태소의 표면형과 품사를 살펴봅니다. AIHub [숫자가 포함된 패턴 발화 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&dataSetSn=484)를 기반으로 학습했으며, 자세한 구조와 데이터 구성은 [데이터 및 모델 고지](NOTICE)에 정리했습니다.

## 설치

Python 3.10 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```powershell
git clone https://github.com/smbslt3/g2p-korean.git
cd g2p-korean
uv sync --dev --locked
```

런타임 의존성은 PyPI의 `kiwipiepy>=0.23.2`이며, `uv.lock`은 재현 가능한 개발
환경을 위해 선택된 릴리스와 해시를 고정합니다.

## 사용

```python
from g2p_ko import G2P, KoreanTTSNormalizer

normalizer = KoreanTTSNormalizer()
g2p = G2P()

normalizer("사과 3개는 6,000원입니다.")
# >>> '사과 세 개는 육천 원입니다.'
g2p("사과 3개는 6,000원입니다.")
# >>> '사과 세 개는 육천 워님니다.'

normalizer("3kg~5kg 정도 필요합니다.")
# >>> '삼 킬로그램에서 오 킬로그램 정도 필요합니다.'
g2p("3kg~5kg 정도 필요합니다.")
# >>> '삼 킬로그래메서 오 킬로그램 정도 피료함니다.'

normalizer("NASA와 TV 뉴스를 봤다.")
# >>> '나사와 티비 뉴스를 봤다.'
g2p("NASA와 TV 뉴스를 봤다.")
# >>> '나사와 티비 뉴스를 봗따.'
```

### 상세 결과와 정렬

완료 여부나 보존 진단이 필요한 경우 `convert()`를 사용합니다.

```python
result = g2p.convert("사과 3개와 국물")

result.source
# >>> '사과 3개와 국물'
result.normalized_text
# >>> '사과 세 개와 국물'
result.surface_pronunciation
# >>> '사과 세 개와 궁물'
result.complete
# >>> True
```

완료된 결과에서는 `normalized_text`와 `surface_pronunciation`이 Python Unicode
code point 기준으로 1:1 대응합니다. 같은 인덱스의 한글 음절끼리 대응하며 공백,
구두점, 보존 문자는 같은 위치에 남습니다.

```python
assert len(result.normalized_text) == len(result.surface_pronunciation)
```

진단은 좌표계가 섞이지 않도록 단계별 report로 나뉩니다.

```python
result = g2p.convert("A-1")
result.complete
# >>> False

# 각 SourceSpan은 같은 report의 source에 대한 code point 좌표입니다.
result.diagnostics.normalization.source
result.diagnostics.normalization.diagnostics
result.diagnostics.pronunciation.source
result.diagnostics.pronunciation.diagnostics
```

자세한 계약은 [공개 G2P API](docs/API.md)를 참고하세요.

### 배치 변환

여러 입력은 문자열용 `pronounce_many()` 또는 상세 결과용 `convert_many()`로
순서대로 처리할 수 있습니다. 두 메서드는 입력을 미리 목록으로 만들지 않는 지연
iterator를 반환합니다.

```python
texts = iter(["국물", "같이", "NASA 뉴스"])
pronunciations = list(g2p.pronounce_many(texts))
# >>> ['궁물', '가치', '나사 뉴스']

results = list(g2p.convert_many(iter(["국물", "같이"])))
assert [result.surface_pronunciation for result in results] == ["궁물", "가치"]
```

문자열 하나를 `texts`로 전달하는 것은 허용하지 않습니다. `texts`와 `normalize`
옵션은 메서드를 호출할 때 검증하며, 개별 항목의 형식·길이 오류와 원본 iterator의
오류는 그 항목을 꺼내는 시점에 발생합니다. `KoreanTTSNormalizer.normalize_many()`와
`convert_many()`는 정규화만 수행하고, `G2P`의 두 메서드는 표면 발음 단계까지
수행합니다.

### 이미 정규화한 입력

`KoreanTTSNormalizer`의 출력은 `normalize=False`로 넘겨 중복 정규화를 생략할 수 있습니다. 이 경로는 입력 검증과 NFC를 유지하고, 영어 철자화와 한국어 음운 규칙만 적용합니다.

```python
normalized = normalizer("사과 3개는 6,000원입니다.")
g2p(normalized, normalize=False)
# >>> '사과 세 개는 육천 워님니다.'
```

원문에 `normalize=False`를 사용하면 숫자·단위·관용 읽기·사용자 사전 처리가 생략됩니다.

### 사용자 사전

JSON 형식의 사용자 사전을 `lexicon` 인자로 전달하면 기본 읽기를 원하는 발화형으로 바꿀 수 있습니다.

```python
import json
from pathlib import Path
from g2p_ko import G2P

g2p = G2P()
g2p("NAVER")
# >>> '에네이브이이알'

# lexicon.json은 {"원문 표기": "완결된 한국어 발화형"} 형태의 JSON 객체입니다.
# 예: {"NAVER": "네이버", "RIDI": "리디", "DAANGN": "당근"}
lexicon = json.loads(Path("lexicon.json").read_text(encoding="utf-8"))
g2p = G2P(lexicon=lexicon)
g2p("NAVER")
# >>> '네이버'
```

### 반복 호출과 병렬 처리

같은 `G2P` 또는 `KoreanTTSNormalizer` 인스턴스를 반복 호출하거나 여러 스레드에서
공유해도 호출별 결과가 섞이지 않습니다. 다만 Python 스레드는 Kiwi 처리량을 높이지
않으므로 여러 코어를 사용하려면 프로세스 worker마다 인스턴스를 하나씩 생성하세요.
G2P batch API도 이 지연·오류 계약을 지키는 순차 처리이며 내부 병렬화는 하지
않습니다.

[MIT 라이선스](LICENSE) · [데이터 출처 고지](NOTICE) ·
[숫자 읽기 모델 provenance](docs/NUMBER_READING_MODEL.md)

`g2p-ko` wheel은 MIT로 배포됩니다. 설치 시 별도로 받는 `kiwipiepy`와 관련
배포물에는 각 배포물의 라이선스 조건이 적용됩니다.
