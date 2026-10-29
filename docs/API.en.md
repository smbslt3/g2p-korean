# Public G2P API contract

## String API

`G2P(max_length=10_000)` accepts strings containing digits. Its beta number stage,
`normalize_numbers(text)`, returns its input unchanged and runs automatically.
No number model is loaded or downloaded. Digits produce `unconverted_numeric`
warnings and `complete=False`; the remaining G2P stages still run without a
numeric-input exception. Direct calls to `normalize_numbers(text)` accept strings
only and preserve even Unicode normalization and whitespace. The separate
`KoreanTTSNormalizer` retains its existing number rules. G2P has no `lexicon` or
`number_reader` constructor arguments. `G2P.__call__(text, normalize=True, pause_boundaries=())` returns
surface pronunciation. The legacy `normalize` boolean is retained for compatibility;
both values run input validation, NFC, English reading, and Korean phonology.

`pause_boundaries` blocks cross-boundary phonology at the requested source positions.
Omitting boundaries retains the existing morphological defaults; it does not force
all adjacent words into a single phonological phrase.

For Hangul pronunciation units with current onset ㅈ, ㅉ, or ㅊ, the j-vowel
spellings ㅑ/ㅒ/ㅕ/ㅖ/ㅛ/ㅠ are canonicalized to ㅏ/ㅐ/ㅓ/ㅔ/ㅗ/ㅜ, including
onsets produced later by liaison. Other onsets, w-vowels, and the ㅐ/ㅔ distinction
remain separate. This is pronunciation spelling normalization, not a claim of
acoustic improvement or permission to rewrite protected literals.

Clear standalone words and acronyms in the shared reading table receive their fixed
Korean readings, case-insensitively and across NFKC-equivalent spellings. For example,
`NASA` → `나사`, `laser` → `레이저`, `coffee` → `커피`, and `TV` → `티비`.
Korean phonology also applies to these Hangul readings. Detailed pronunciation rewrites
inside `Pipeline.run()` record rule ID `english.conventional.v1`. This internal rewrite
trace is not exposed through the public `G2PResult` or diagnostic reports. The selected
table is not an exhaustive dictionary or a claim to cover official standard
pronunciations for all English.

Unknown or ambiguous English is spelled out by Korean letter names. Words inside URLs,
email addresses, paths, inline code, and joined identifiers are spelled out as well,
even when they match a table entry. Fullwidth and mathematical letters are interpreted
as their NFKC-equivalent ASCII letters. URL punctuation such as `://` and `.` stays
literal; G2P does not verbalize it as “colon,” “slash,” or “dot.” Remaining numbers are
preserved with `unconverted_numeric` and `complete=False`. G2P does not automatically
call the standalone normalizer.

Token boundaries are contiguous Latin spans: Korean attachment such as `NASA와`
or `NAVER검색` is allowed. Hashtags, joined identifiers, adjacent combining marks,
and non-Hangul script mixtures do not use conventional readings. Schemeless domains,
queries, and fenced code inside quotes or lists retain letter spelling. Latin
characters such as `é` and `ß` without an ASCII NFKC mapping remain preserved and
make the detailed result incomplete.

```python
from g2p_ko import G2P

g2p = G2P()
assert g2p("국물") == "궁물"
```

## Detailed API

`G2P.convert(text, normalize=True, pause_boundaries=())` returns an immutable `G2PResult`.

| Field | Meaning |
| --- | --- |
| `source` | Original caller input |
| `normalized_text` | Phonology input after all lexical replacements |
| `surface_pronunciation` | Result after Korean phonological rules |
| `diagnostics` | Stage reports separated by coordinate system |
| `complete` | Whether every required stage settled on a reading |

The string and detailed paths always return the same pronunciation.

```python
assert g2p(text, normalize=flag) == (
    g2p.convert(text, normalize=flag).surface_pronunciation
)
```

`G2PResult`, `G2PDiagnostics`, and `DiagnosticReport` are importable from the
top-level `g2p_ko` package and provide `to_dict()`.

## Batch API

Both single-input methods accept `pause_boundaries`, an iterable of integer code-point
offsets in NFC-normalized input, before English replacements. Pauses block sound changes
across the specified positions while preserving full analyzer and semantic context.
Omitting the argument preserves the existing connected-reading behavior.

```python
assert g2p("국물", pause_boundaries=(1,)) == "국물"
assert g2p("옷 안", pause_boundaries=(2,)) == "옫 안"
```

Offsets range from zero through the NFC input length; endpoints and duplicates are valid.
String containers, Boolean/non-integer offsets, and out-of-range positions raise
`InputValidationError`. Replacement endpoints and later offsets are mapped to the expanded
text. An offset strictly inside a length-changing replacement is rejected; for example,
offset `1` inside `AI` has no defined alignment. Batch methods retain their existing
signatures; invoke a single-input method per item when supplying pauses.

```python
pronunciations = g2p.pronounce_many(texts, normalize=True)
results = g2p.convert_many(texts, normalize=True)
```

- `pronounce_many()` returns `Iterator[str]`.
- `convert_many()` returns `Iterator[G2PResult]`.
- Both iterators preserve input order without first materializing the full input.
- Passing `str`, `bytes`, or a non-iterable as the outer `texts` value raises
  `InputValidationError` when the method is called. A string is never treated as
  an implicit one-item batch.
- A non-`bool` `normalize` value raises `InputValidationError` at method-call
  time, before the input iterator is consumed.
- Per-item string, length, and surrogate validation happens when that result is
  requested with `next()`. An exception from the source iterator propagates at
  the same point.
- Processing is sequential by item. It does not use internal parallelism or
  prefetch later items.

`KoreanTTSNormalizer.normalize_many()` and `convert_many()` use the same iterator
style but stop after normalization. `G2P.pronounce_many()` and
`G2P.convert_many()` also perform English handling and surface pronunciation, so
the two API pairs are not interchangeable.

## Diagnostic coordinates

Diagnostics from different coordinate systems are not flattened into one list.

- `result.diagnostics.normalization.source` is the coordinate source for
  normalization diagnostics. It always equals `result.source`; the report is currently empty.
- `result.diagnostics.pronunciation.source` is the text received by the
  pronunciation stage after NFC, before English expansion.
- Every `Diagnostic.source_spans` entry is a half-open `[start:end]` range over
  the `DiagnosticReport.source` on the same report, measured in Python Unicode
  code points.
- `SourceSpan.surface` is the corresponding slice of that source.

`complete=False` reports unresolved numbers, unsupported input, or failed rule
application. The string API returns the same preserved output; use `convert()`
when completion status matters.
Completion reports that no known processing condition remains unresolved; it does
not certify pronunciation accuracy for unknown words or homographs.

## Normalized-text/pronunciation alignment

Every complete result guarantees:

```python
len(result.normalized_text) == len(result.surface_pronunciation)
```

Coordinates use Python Unicode code points. Modern Hangul syllables at the same
index correspond, while whitespace, punctuation, and preserved characters remain
at the same index. This is not a UTF-8 byte-offset or grapheme-cluster contract.

The current engine preserves this structure for incomplete results as well, but
the public downstream alignment contract applies to `complete=True` results. A
future insertion or deletion rule would require an explicit alignment API and a
versioned contract change.

## Alignment to the original input

`convert_with_alignment()` returns the existing `G2PResult` and an alignment sidecar
from one conversion. Existing string APIs, `convert()`, and `G2PResult.to_dict()`
retain their formats.

```python
from g2p_ko import G2P

aligned = G2P().convert_with_alignment("AI 국물")
assert aligned.result.surface_pronunciation == "에이아이 궁물"
assert aligned.alignment.extract_target(0, 2).pronunciation == "에이아이"
assert aligned.alignment.extract_target(3, 5).pronunciation == "궁물"
assert not aligned.alignment.extract_target(0, 1).aligned
```

Source offsets use Python code points in the original input; output offsets use
code points in `surface_pronunciation`. Provenance composes NFC normalization and
English readings. A decomposed Hangul cluster or an English reading is an atomic
operation: whole-operation extraction can succeed, while a partial overlap returns
`aligned=False` with `reason="partial_operation"`.

`alignment.status` is `exact`, `coarse`, or `unavailable`, independently of
`result.complete`. Entries record output ranges, original source spans, relation,
stage/rule evidence, and precision; `alignment.to_dict()` serializes them.
`extract_target(start, end)` returns the pronunciation and output offsets on success,
or an explicit failure reason. Phonological alignment uses output syllable positions,
including the positions after resyllabification.

`pause_boundaries` still uses NFC-input offsets. These can differ from original-input
alignment offsets when normalization composes code points. This API adds alignment;
long-vowel features, IPA, and new linguistic contraction rules remain separate work.

## Selecting reading conditions at source boundaries

`convert_with_reading_conditions()` selects ordinary liaison, one-madi grouping,
or a pause at a requested boundary. `ReadingBoundary.offset` uses Python code-point
coordinates in the **original input**, unlike the existing NFC-based
`pause_boundaries` argument.

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

Nonpause requests require an ASCII-space gap between modern Hangul syllables.
Ordinary liaison suppresses competing word-level n-insertion; one-madi grouping
retains the existing grammatical and vowel eligibility rules. Neither request
opens HARD or protected boundaries. Conflicting relations, conflicting legacy
pauses, NFC atomic interiors, and ambiguous length-changing rewrite interiors
are rejected.

The result provides `aligned` and `boundary_executions` from the same conversion.
The latter separates requested relations, actual sound effects, blocked requests,
and unavailable grammatical evidence. A selected recipe is not an observation of
the speaker's prosody. Empty conditions preserve the existing aligned conversion.

## Input and instance lifetime

- Empty strings are accepted.
- The default raw-input limit is 10,000 code points and can be changed with
  `max_length`.
- `normalize` accepts only `bool`.
- Repeated and concurrent calls on one instance are deterministic.
- Python threads are not promised as a throughput optimization.
- Create one instance in each worker when using multiple processes.

Number conversion belongs to the upstream project. The separate legacy
`KoreanTTSNormalizer(number_reader=...)` integration is described in the
[external model contract](NUMBER_READING_MODEL.md).

`complete=True` means no known unresolved input or failed rule application was
reported; it is not a pronunciation accuracy score. Analyzer failures produce an
incomplete result. Pronunciation diagnostics use NFC input coordinates before
English expansion, not `normalized_text` coordinates.
