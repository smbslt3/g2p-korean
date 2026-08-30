# g2p-ko

Normalizes Korean TTS input into spoken forms and converts it to surface pronunciation.

[한국어](README.md)

## Features

- Normalizes numbers, units, dates, times, currencies, fractions, and abbreviations
  - `3kg~5kg` → `삼 킬로그램에서 오 킬로그램`
  - `2/5kg` → `오분의 이 킬로그램`
  - `6,000원` → `육천 원`
- Uses a small statistical model to choose context-dependent number readings
  - It considers only numbers that deterministic rules cannot settle, choosing a native Korean, Sino-Korean, or digit-by-digit reading. It keeps the rule result when the rule is conclusive or model confidence is insufficient.
  - The same `3번` is read as `세 번` for a count and `삼 번` for an identifier.
  - `영화를 3번 봤다.` → `영화를 세 번 봤다.`
  - `3번 창구로 가세요.` → `삼 번 창구로 가세요.` (model decision)
  - `우편번호는 54130입니다.` → `우편번호는 오 사 일 삼 공입니다.` (model decision)
- Applies Korean phonological rules grounded in the Standard Pronunciation Rules
  - `국물` → `궁물`
  - `같이` → `가치`
  - It bundles no external pronunciation dictionary and uses productive rules
    plus unambiguous exact-match examples from the official notice.
- Prioritizes conventional readings such as NASA, KIA, and TV
  - `NASA` → `나사`
  - `KIA` → `기아`
  - `FIFA와 TV` → `피파와 티비`
- Spells out other English text using Korean letter names
  - `ABC` → `에이비씨`
  - `PYTHON` → `피와이티에이치오엔`
  - `TEST` → `티이에스티`
- Preserves uncertain or unsupported input
  - `A-1` → `A-1`
  - `1-3개` → `1-3개`
  - `192.168.0.1` → `192.168.0.1`
- Supports a user lexicon
  - `NAVER` → `네이버`
  - `RIDI` → `리디`
  - `DAANGN` → `당근`

The number-reading model considers the number's length and value, its unit, and the surface forms and part-of-speech tags of nearby Kiwi morphemes. It was trained on AIHub's [숫자가 포함된 패턴 발화 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&dataSetSn=484). See the [data and model notice](NOTICE) for its structure and detailed data composition.

## Installation

Python 3.10 or later and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone https://github.com/smbslt3/g2p-korean.git
cd g2p-korean
uv sync --dev --locked
```

The runtime dependency is `kiwipiepy>=0.23.2` from PyPI. `uv.lock` pins the
selected release and hashes for reproducible development environments.

## Usage

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

### Detailed results and alignment

Use `convert()` when completion status or preservation diagnostics matter.

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

For complete results, `normalized_text` and `surface_pronunciation` correspond
one-to-one by Python Unicode code point. Hangul syllables at the same index
correspond, while whitespace, punctuation, and preserved characters stay at the
same index.

```python
assert len(result.normalized_text) == len(result.surface_pronunciation)
```

Diagnostics are separated by stage so their coordinate systems never mix.

```python
result = g2p.convert("A-1")
result.complete
# >>> False

# Each SourceSpan uses the source string on the same report.
result.diagnostics.normalization.source
result.diagnostics.normalization.diagnostics
result.diagnostics.pronunciation.source
result.diagnostics.pronunciation.diagnostics
```

See the [public G2P API contract](docs/API.en.md) for the complete contract.

### Batch conversion

Use `pronounce_many()` for strings or `convert_many()` for detailed results.
Both preserve input order and return lazy iterators without first materializing
the input.

```python
texts = iter(["국물", "같이", "NASA 뉴스"])
pronunciations = list(g2p.pronounce_many(texts))
# >>> ['궁물', '가치', '나사 뉴스']

results = list(g2p.convert_many(iter(["국물", "같이"])))
assert [result.surface_pronunciation for result in results] == ["궁물", "가치"]
```

A single string is not accepted as `texts`. The outer iterable and `normalize`
option are validated when the method is called. Per-item type and length errors,
and errors raised by the source iterator, surface when that item is requested.
`KoreanTTSNormalizer.normalize_many()` and `convert_many()` stop after
normalization; the two `G2P` methods include surface pronunciation.

### Already normalized input

Pass output from `KoreanTTSNormalizer` with `normalize=False` to skip duplicate normalization. This path retains input validation and NFC, then applies only English spelling and Korean phonological rules.

```python
normalized = normalizer("사과 3개는 6,000원입니다.")
g2p(normalized, normalize=False)
# >>> '사과 세 개는 육천 워님니다.'
```

Using `normalize=False` on raw text skips number, unit, conventional-reading, and user-lexicon transformations.

### User lexicon

Pass a JSON user lexicon through `lexicon` to replace the default reading with a complete Korean spoken form.

```python
import json
from pathlib import Path
from g2p_ko import G2P

g2p = G2P()
g2p("NAVER")
# >>> '에네이브이이알'

# lexicon.json must be an object in the form
# {"source spelling": "complete Korean spoken form"}.
lexicon = json.loads(Path("lexicon.json").read_text(encoding="utf-8"))
g2p = G2P(lexicon=lexicon)
g2p("NAVER")
# >>> '네이버'
```

### Repeated and parallel calls

A `G2P` or `KoreanTTSNormalizer` instance can be reused and shared across threads
without mixing per-call state. Python threads do not improve Kiwi throughput,
so create one instance in each process worker when multiple CPU cores are needed.
The G2P batch API is sequential to retain its lazy consumption and error-timing
contract; it does not add internal parallelism.

[MIT License](LICENSE) · [Data and model notice](NOTICE) ·
[Number-reading model provenance](docs/NUMBER_READING_MODEL.md)

The `g2p-ko` wheel is distributed under MIT. Separately installed `kiwipiepy`
and related distributions remain subject to their own license terms.
