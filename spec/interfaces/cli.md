# Command line contract

Every track exposes the same command line. The runner name differs; nothing else does.

```
<runner> <verb> --input <path> --output <path> [--config <path>]
```

| Track | Runner |
|---|---|
| `python_pure` | `uv run --project python_pure volarb-py` |
| `python_cpp` | `uv run --project python_cpp volarb-cpp` |
| `cpp_pure` | `build/release/cpp_pure/volarb-native` |

Exit status is `0` on success and `1` on any failure. Failures print a single line to
stderr in the form `error: <message>` and write no output file.

Records are processed independently and in order, and the output carries one record per
input record.

Where a result schema has a `status` field, a record that cannot be processed is reported
through it rather than aborting the run. That covers the conditions that legitimately arise
from real quotes: a price below intrinsic, or one outside the invertible volatility range.

Everything else is a run-level failure that writes no output: a malformed document, a
schema mismatch, an unreadable input, an unknown verb, or a record whose values violate a
precondition in `spec/schemas/` such as a negative time to expiry. Those are defects in the
caller, not market conditions, and silently carrying them into an output record would let a
bad pipeline look like a partially successful one.

## Verbs

### `price-options`

Input `pricing_request/v1`, output `pricing_result/v1`. Prices European options in the
forward measure and returns the greeks defined in `docs/math.md`.

### `invert-implied-volatility`

Input `implied_volatility_request/v1`, output `implied_volatility_result/v1`. Inverts the
Black formula for volatility on the out-of-the-money side of each strike.

The result carries the iteration count, so conformance detects algorithmic divergence even
when the answers happen to agree, and `volatility_uncertainty`, so consumers can tell a
volatility that is pinned to twelve digits from one that is barely determined by the quote.
Non-finite floats are written as JSON `null`, since `Infinity` is not valid JSON and the
tracks would otherwise disagree on the encoding rather than on the number.

## Document envelope

Every input and output document is a JSON object with two keys:

```json
{
  "schema": "pricing_request/v1",
  "records": []
}
```

The `schema` field is checked on read. A mismatch is a run-level failure. Records carry an
`id` that is unique within the document and is preserved into the output, so conformance
compares by identity rather than by position.
