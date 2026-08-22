# Command line contract

Every track exposes the same command line. The runner name differs; nothing else does.

```
<runner> <verb> --input <path> --output <path> [--config <path>]
```

| Track | Runner |
|---|---|
| `python_pure` | `uv run --project python_pure volarb-py` |
| `python_cpp` | `uv run --project python_cpp volarb-cpp` |
| `cpp_pure` | `cpp_pure/build/release/volarb-native` |

Exit status is `0` on success and `1` on any failure. Failures print a single line to
stderr in the form `error: <message>` and write no output file.

Records are processed independently. A record that cannot be processed does not abort the
run; it appears in the output with `"status"` set to a failure reason. Only a malformed
request document, an unreadable input, or an unknown verb is a run-level failure.

## Verbs

### `price-options`

Input `pricing_request/v1`, output `pricing_result/v1`. Prices European options in the
forward measure and returns the greeks defined in `docs/math.md`.

### `invert-implied-volatility`

Input `implied_volatility_request/v1`, output `implied_volatility_result/v1`. Inverts the
Black formula for volatility, returning both the volatility and the iteration count so that
conformance can detect algorithmic divergence even when the answers happen to agree.

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
