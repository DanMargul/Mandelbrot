# Benchmarks

Regenerate with:

```sh
uv run --no-sync benchmarks/run.py --records 20000 100000 400000 --output docs/benchmark_results.md
```

The raw tables live in [`benchmark_results.md`](benchmark_results.md). This document is the
interpretation, which matters more than the numbers, because the headline ratios are
misleading if read without it.

## Method

Each track is run over identical generated workloads at three sizes, three repeats, fastest
run taken. A line is fitted through the three points so that fixed process and startup cost
is separated from marginal cost per option. The slope is the number worth comparing; the
intercept is mostly process spawn and interpreter startup.

The harness shells out to the track binaries rather than importing anything, for the same
reason the conformance runner does.

## Results, and what they actually say

Measured on Apple clang 21 / arm64, CPython 3.13.14, 400,000 options.

| verb | cpp_pure | python_cpp | python_pure |
|---|---:|---:|---:|
| `price-options` | 3714 ns | 4328 ns (1.17x) | 4632 ns (1.25x) |
| `invert-implied-volatility` | 4010 ns | 4519 ns (1.13x) | 23186 ns (5.78x) |

**A 1.25x spread on pricing is not a real result.** The pricing verb does very little
arithmetic per record, so the measurement is dominated by JSON. Decomposing the pure Python
pipeline at 400,000 records:

| stage | seconds | share |
|---|---:|---:|
| JSON parse | 0.31 | 18% |
| pricing arithmetic | 0.77 | 45% |
| JSON serialize | 0.63 | 37% |

Over half the wall clock is spent turning text into numbers and back. Both C++ tracks pay
that cost too, through nlohmann, which is not notably faster than CPython's C parser. The
end-to-end ratio therefore measures the JSON library far more than it measures the language.

**The 5.78x on inversion is a real result.** Inversion runs roughly thirty Newton iterations
per option, each one a full Black evaluation, so arithmetic dominates and the interpreter
overhead becomes visible. This is the honest measure of the interpreted-versus-native gap
for this workload.

**The language boundary is cheap when the work per crossing is not.** `python_cpp` sits
1.13x above `cpp_pure` on inversion. One pybind11 call per option buys thirty native
iterations, so the crossing amortizes almost completely. On pricing the same crossing costs
1.17x because there is far less work behind it. This is the argument for the batch entry
points in the bindings, and for pushing loops down into the core rather than driving them
from Python.

## Consequences for the roadmap

The JSON envelope is the right contract for fixtures and conformance, where documents are
small and human-readable diffs matter. It is the wrong transport for a backtest over a
full option chain history.

Phase 2 therefore moves the bulk data path to Parquet while keeping JSON for the
conformance fixtures. Until that lands, no performance claim about `price-options` should
be quoted from the end-to-end table; it is a JSON benchmark wearing a pricing benchmark's
label.
