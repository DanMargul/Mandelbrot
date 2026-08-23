# The data spine

Everything below the parity boundary reads one thing: a canonical option chain dataset in
Parquet. This document defines it, and defines the as-of query semantics that make a
backtest incapable of seeing the future.

## Why bitemporal

A single timestamp per row cannot express the difference between *when a thing was true* and
*when we could have known it*. That difference is where backtests quietly cheat:

- an exchange corrects a bad print an hour later, and the corrected value is silently used
  as though it had been available at the time
- open interest is published the following morning, and a signal reads it same-day
- a vendor backfills a gap, and the backfilled rows carry the original event timestamps
- a corporate action is applied retroactively across history

Every one of these is invisible when rows carry only one timestamp, and every one of them
makes results better than reality. So every row carries two:

| column | meaning |
|---|---|
| `event_time` | when this market state was true |
| `knowledge_time` | the earliest moment this row could have been acted on |

`knowledge_time >= event_time` always, and it is validated at ingestion. A row claiming to
have been knowable before it happened is rejected rather than corrected, because the only
thing that produces one is a bug in the ingester.

## The as-of query

A query names three things: an underlying, an `observation_time`, and a
`knowledge_horizon`.

```
candidate rows = { r : r.knowledge_time <= knowledge_horizon
                       and r.event_time <= observation_time }

result = for each contract_symbol, the candidate row maximising
         (event_time, knowledge_time, ingest_sequence)
```

In words: the most recent state of each contract that was true by the observation time and
knowable by the horizon.

`ingest_sequence` is a monotonic integer assigned at ingestion, present solely to make the
maximum unique. Without it, two rows agreeing on both timestamps would resolve by file
order, which is stable within a Parquet file but is not something three independent
implementations can be relied on to agree about. The tiebreak is part of the contract, not
an implementation detail.

`observation_time > knowledge_horizon` is rejected as a typed error. Asking for market state
from later than what you could have known is not a query, it is the bug this whole design
exists to prevent.

For a backtest the horizon equals the observation time and moves together with the clock.
For a research query reproducing what was believed on some past date, the horizon is pinned
to that date while the observation time sweeps.

## No lookahead by construction

The horizon is fixed when the reader is constructed and is immutable thereafter. There is no
method on the reader that returns rows without applying it, no flag that disables it, and no
accessor that exposes the underlying table. A backtest cannot read past its horizon because
the object it holds has no operation that would do so.

This is weaker than a compile-time guarantee in Python and stronger than a convention. In
C++ the horizon is carried in the reader's type. The claim being made is precise: no public
API returns a row past the horizon, and attempting to query past it raises rather than
returning a filtered-but-plausible answer.

## Canonical schema: `option_chain_snapshot/v1`

Parquet, one row per contract per observation.

| column | type | notes |
|---|---|---|
| `underlying_symbol` | string | `SPX`, `AAPL` |
| `contract_symbol` | string | OCC format, unique within an expiry cycle |
| `expiry_date` | date32 | |
| `strike` | double | |
| `option_type` | string | `call` or `put` |
| `contract_multiplier` | int32 | 100 for standard, otherwise adjusted |
| `is_standard_deliverable` | bool | false for adjusted contracts |
| `event_time` | timestamp[us, UTC] | |
| `knowledge_time` | timestamp[us, UTC] | |
| `ingest_sequence` | int64 | monotonic, tiebreak only |
| `underlying_price` | double | |
| `bid_price` | double | |
| `ask_price` | double | |
| `bid_size` | int64 | |
| `ask_size` | int64 | |
| `last_trade_price` | double, nullable | |
| `volume` | int64, nullable | |
| `open_interest` | int64, nullable | published next morning; set `knowledge_time` accordingly |
| `source` | string | `polygon`, `synthetic` |

### Adjusted contracts

After a split, spinoff, or special dividend, the OCC adjusts existing contracts so the
deliverable is no longer 100 shares of one thing. Such a contract still has a strike and a
price, and will happily fit a surface, and the surface will be wrong.

`is_standard_deliverable` marks them, and the as-of reader **excludes them by default**.
Including them requires passing `include_adjusted_contracts` explicitly. There is no
configuration in which they are silently mixed with standard contracts, which is the
failure mode worth designing against: it is not an error, it is a slightly wrong answer.

## Layout and manifest

```
<dataset>/
  manifest.json
  underlying=SPX/observation_date=2026-08-21/part-00000.parquet
  underlying=SPX/observation_date=2026-08-22/part-00000.parquet
```

The manifest records, per partition: relative path, row count, SHA-256 of the file bytes,
and the minimum and maximum of both timestamp columns.

The hashes exist for step 7 of `program.md`: a backtest result is pinned to a dataset by
content, so "rerun with the same data" is checkable rather than assumed. The timestamp
ranges let the as-of reader skip whole partitions whose minimum `knowledge_time` is already
past the horizon, which is what keeps the backtest inner loop from rescanning history.

## Ingestion

The Polygon client is Python only, per the parity boundary in `architecture.md`. It reads
`POLYGON_API_KEY` from the environment and is never given a key in configuration or on the
command line.

It runs in one of three modes:

- `--source polygon` against the live API
- `--source recorded` against captured responses in `spec/fixtures/recorded/`, so the
  ingestion path is testable with no key and no network
- `--source synthetic` against a seeded generator, so the whole stack can be exercised
  before any real data exists

The synthetic generator is not a placeholder to be deleted later. It produces chains with
known ground truth, which is the only way to test that a surface calibrator recovers the
parameters it was given.
