# `spec`

The contracts all three tracks are held against.

| Path | Contents |
|---|---|
| `interfaces/` | exact function names and typed signatures, one file per module |
| `schemas/` | JSON Schema for every record type that crosses a track boundary |
| `fixtures/` | golden inputs and expected outputs |
| `tolerances.toml` | per-field numerical tolerance used by `conformance/` |

## Tolerances

Fields are matched by schema id and field name, falling back to `[defaults]`. A field
passes when the absolute difference is within `absolute`, or the relative difference is
within `relative`. Setting `exact = true` requires bitwise equality and is used for
statuses, counts and identifiers, where a near miss is not a rounding difference but a
different code path.

The tolerances are tighter than they need to be on purpose. They are set just above the
floating point noise floor for each quantity rather than at a level that feels safe, so
that a genuine algorithmic divergence fails immediately instead of hiding inside a
generous margin until it has grown.

`gamma_with_respect_to_forward` is the one relaxed entry, at `1e-11` relative. It carries a
division by `forward * volatility * sqrt(T)` and loses roughly a digit more than the others
on short-dated low-volatility inputs.

`absolute_price_error` is compared on absolute terms only, with the relative bound disabled
at `1.0`. It is a residual near machine epsilon, so its relative difference between two
correct implementations is meaningless.
