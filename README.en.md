# g2p-ko

A Python library for converting Korean text to surface pronunciation.

[한국어](README.md)

## Installation

Requires Python 3.10 or later.

```shell
python -m pip install "git+https://github.com/smbslt3/g2p-korean.git"
```

## Basic usage

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

Applies Korean phonological rules and morpheme boundaries. Registered English
words and acronyms use their Korean readings; other English uses Korean letter names.

## Number handling

`normalize_numbers()` returns its input unchanged. Default G2P also preserves
numeric notation while continuing English and Korean pronunciation conversion.

```python
from g2p_ko import normalize_numbers

normalize_numbers("사과 3개")
# '사과 3개'
g2p("AI 01.20 국물")
# '에이아이 01.20 궁물'
```

## Detailed results

Use `convert()` to inspect the source, normalized text, pronunciation, and diagnostics.

```python
result = g2p.convert("사과 세 개와 국물")

result.normalized_text
# '사과 세 개와 국물'
result.surface_pronunciation
# '사과 세 개와 궁물'
result.complete
# True
```

Remaining digits and unsupported characters are preserved with diagnostics and `complete=False`.

## Batch conversion

```python
list(g2p.pronounce_many(["국물", "같이", "NASA 뉴스"]))
# ['궁물', '가치', '나사 뉴스']

results = list(g2p.convert_many(["국물", "같이"]))
```

See the [API documentation](docs/API.en.md) for source-to-pronunciation alignment,
reading conditions, vowel variants and length, and the separate
`KoreanTTSNormalizer` tool.

## Development

```shell
git clone https://github.com/smbslt3/g2p-korean.git
cd g2p-korean
uv sync --dev --locked
uv run pytest -q
```

## License

[MIT](LICENSE) · [Data and dependency notices](NOTICE)
