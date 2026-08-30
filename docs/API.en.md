# Public G2P API contract

## String API

`G2P.__call__(text, normalize=True)` continues to return only the surface
pronunciation string. `normalize=False` skips the TTS normalizer while retaining
input validation and NFC. After optional normalization, its downstream pipeline
uses the same routing, protection, English handling, and Korean phonology core as
the detailed path, then returns only the surface-pronunciation string.

```python
from g2p_ko import G2P

g2p = G2P()
assert g2p("국물") == "궁물"
```

## Detailed API

`G2P.convert(text, normalize=True)` returns an immutable `G2PResult`.

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
  normalization diagnostics. With `normalize=True`, it equals `result.source`.
- `result.diagnostics.pronunciation.source` is the text received by the
  pronunciation stage.
- Every `Diagnostic.source_spans` entry is a half-open `[start:end]` range over
  the `DiagnosticReport.source` on the same report, measured in Python Unicode
  code points.
- `SourceSpan.surface` is the corresponding slice of that source.

`complete` is not inferred solely from the presence of warnings. A safe rule
fallback may emit a warning and still complete, while preserved unsupported
input or an undecidable phonological rule makes the result incomplete.

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

## Input and instance lifetime

- Empty strings are accepted.
- The default raw-input limit is 10,000 code points and can be changed with
  `max_length`.
- `normalize` accepts only `bool`.
- Repeated and concurrent calls on one instance are deterministic.
- Python threads are not promised as a throughput optimization.
- Create one instance in each worker when using multiple processes.
