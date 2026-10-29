# g2p-ko

한국어 문장을 표면 발음으로 변환하는 Python 라이브러리입니다.

[English](README.en.md)

## 설치

Python 3.10 이상에서 설치할 수 있습니다.

```shell
python -m pip install "git+https://github.com/smbslt3/g2p-korean.git"
```

## 기본 사용

```python
from g2p_ko import G2P

g2p = G2P()

g2p("국물")
# '궁물'
g2p("같이")
# '가치'
g2p("맛없어요")
# '마덥써요'
g2p("NASA 뉴스")
# '나사 뉴스'
```

한국어 음운 규칙과 형태소 경계를 적용합니다. 영문은 등록된 단어·약어의 한글
읽기를 적용하고, 그 밖의 영문은 알파벳 이름으로 읽습니다.

## 숫자 처리

숫자 전처리 함수 `normalize_numbers()`는 입력을 그대로 반환합니다.
기본 G2P에서도 숫자 표기를 유지하며 영문·한글 발음 변환을 계속합니다.

```python
from g2p_ko import normalize_numbers

normalize_numbers("사과 3개")
# '사과 3개'
g2p("AI 01.20 국물")
# '에이아이 01.20 궁물'
```

## 상세 결과

`convert()`로 원문, 정규화한 문장, 발음과 진단 정보를 확인할 수 있습니다.

```python
result = g2p.convert("사과 세 개와 국물")

result.normalized_text
# '사과 세 개와 국물'
result.surface_pronunciation
# '사과 세 개와 궁물'
result.complete
# True
```

숫자나 미지원 문자가 남으면 해당 문자를 보존하고 `complete=False`와 진단을 반환합니다.

## 배치 변환

```python
list(g2p.pronounce_many(["국물", "같이", "NASA 뉴스"]))
# ['궁물', '가치', '나사 뉴스']

results = list(g2p.convert_many(["국물", "같이"]))
```

원문과 발음의 위치 대응, 읽기 조건, 모음 변이·장단음, 별도 정규화 도구
`KoreanTTSNormalizer`의 사용법은 [API 문서](docs/API.md)를 참고하세요.

## 개발

```shell
git clone https://github.com/smbslt3/g2p-korean.git
cd g2p-korean
uv sync --dev --locked
uv run pytest -q
```

## 라이선스

[MIT](LICENSE) · [데이터 및 의존성 고지](NOTICE)
