# Wiring real data in

Everything in this repository has been measured against data it generated itself. This is what
stands between that and a real option chain, in the order it has to be dealt with.

Each item says what is wrong, how to see it for yourself, and what fixing it involves.

---

## 0. What already works, and needs nothing

Worth knowing before the list of problems, because it removes two jobs people expect to have.

**You do not need a rate feed or a dividend forecast.** `spec/interfaces/forward_curve.md`
implies the forward and the discount factor for each expiry from put-call parity on the chain
itself. Supplying an external rate was tried and measured: the standard error on the forward
moved from `4.8e-5` to `4.9e-5`, so it was rejected. `rate_curve` exists only for discounting
*across* expiries, which single-expiry relative value does not need.

**The Polygon client, the retry logic and the record/replay path all exist** and are the right
shape. `--record-to` captures raw responses so a live pull can be replayed offline forever.

**The bitemporal guarantee is real.** `event_time` and `knowledge_time` are separate columns, the
writer rejects a row knowable before it happened, and the as-of reader filters on
`knowledge_time`. Real data does not weaken this.

---

## 1. The real-data path is broken today

**This is the first thing to fix and it is not optional.**

```
uv run ingestion/run.py --source recorded --underlying SPXTEST --dataset-root /tmp/x
```

```
KeyError: 'exercise_style'
```

`spec/schemas` gained a non-nullable `exercise_style` column in commit `d7482bb`. The three
synthetic generators were updated. **`ingestion/polygon.py` was not**, so every row it produces
is missing a required column and `write_dataset` raises on the first partition.

It went unnoticed because of a gap in the tests, which is worth understanding before you patch
it: `ingestion/tests/test_ingestion.py` exercises `rows_from_snapshot_pages` against the recorded
fixture, and separately exercises `write_dataset` against **synthetic** rows. It never writes
recorded rows. The mapper is tested, the writer is tested, and the seam between them is not.

### What the fix has to decide

Adding `"exercise_style": "european"` makes the error go away and is wrong for most of the
universe. Polygon's snapshot has no exercise-style field, so the value has to be decided from the
underlying:

- **Cash-settled index options are European** — SPX, XSP, NDX, RUT, VIX.
- **Listed equity and ETF options are American** — every single name, and SPY, QQQ, IWM.

This is not cosmetic. `spec/interfaces/american.md` prices the early-exercise premium, and
`forward_curve.md` strips that premium before fitting parity. Label an American chain European
and the parity fit absorbs the premium into the forward, which shifts every implied volatility in
the slice and appears downstream as mispricing that is not there.

Practically: an explicit table of cash-settled index roots, defaulting to `american`, and a test
that writes recorded rows through `write_dataset` so this seam cannot silently break again.

---

## 2. One snapshot is one instant, and the writer deletes what was there

`snapshot_pages` calls `/v3/snapshot/options/{underlying}`, which returns the chain **as it is
now**. There is no history in it.

And `writer.py` opens with:

```python
if dataset_root.exists():
    shutil.rmtree(dataset_root)
```

So every ingest replaces the entire dataset. **Running it daily for a year gives you one day of
data, three hundred times.**

Everything downstream needs dates. `backtest/residual_run.py` wants 120 observations,
`walk_forward_run.py` splits them into folds, `score_residual` needs a series. A single snapshot
supports the surface fitting and the arbitrage checks and nothing else.

You have two routes.

**Accumulate.** Write each pull to its own directory, and add a step that reads them all and
writes one dataset. The blocker is `ingest_sequence`, which `validate_rows` requires to be unique
across the whole dataset — a merger has to renumber, not concatenate. This is the smaller change
and it starts producing usable history from the day you start running it, which means the first
120-observation dataset is four months away.

**Backfill.** Polygon sells historical options data as flat files (S3) and per-contract quote
endpoints. Neither is implemented; `polygon.py` speaks only the snapshot endpoint. This is more
work and gets you years of history immediately. If you intend to test anything on more than one
quarter, this is the route, and it should be a separate adapter rather than a flag on the
existing one — the snapshot shape and the flat-file shape have little in common.

**Note the sizing consequence.** `docs/history_run.md` measured that establishing an edge against
a ten-configuration search needed about **3,970 observations**. Accumulating forward gets there
in sixteen years.

---

## 3. What your Polygon account has to be

Check before writing any code, because the answer changes the plan:

```
curl -s "https://api.polygon.io/v3/snapshot/options/SPY?limit=5&apiKey=$POLYGON_API_KEY" | head -40
```

- A **`NOT_AUTHORIZED`** response means options data is not on your plan. The client's retry logic
  does not retry authorisation failures, correctly, so this surfaces as `PolygonError: HTTP 403`.
- Confirm your **requests per minute**. `SNAPSHOT_PAGE_LIMIT` is 250 and pagination follows
  `next_url` until exhausted. A full SPX chain is several thousand contracts, so one underlying is
  roughly twenty sequential requests. On a five-per-minute plan that is four minutes for one
  underlying — and step 9's dispersion work wants five hundred. Do that arithmetic against your
  plan before committing to a universe size.
- Confirm whether your plan returns **`last_quote`** on the snapshot. `contract_row_from_snapshot`
  returns `None` when `last_quote` is absent, so a plan without quote entitlement yields an empty
  dataset rather than an error. If a pull produces zero rows, this is the first thing to check.

The key is read from `POLYGON_API_KEY` in the environment and deliberately cannot be passed on
the command line or in config. Keep it that way.

---

## 4. Data quality, which currently has no gate at all

Every downstream module assumes quotes that already make sense. Synthetic data always did.
Real data does not, and there is nothing in between.

**Zero and missing prices.** `contract_row_from_snapshot` does
`float(quote.get("bid", 0.0))`. A contract quoted `0.00 / 0.05`, or one with an absent bid,
becomes a row with `bid_price = 0.0` that flows straight into `invert_black_implied_volatility`.

**Crossed and locked markets.** Nothing checks `bid_price <= ask_price`.

**Stale quotes.** `event_time` comes from `last_quote.last_updated`. An illiquid contract may not
have printed in days. Two consequences: it will be inverted as though current, and — because
`writer.partition_key` uses `event_time.date()` — **it lands in a previous day's partition**,
which is not what you want from a pull you thought was one day.

**Non-standard deliverables.** `is_standard_deliverable` is computed and written, and **nothing
downstream ever filters on it**. Post-split and post-merger contracts have adjusted multipliers
and deliverables that are not 100 shares of the underlying; their implied volatilities are
meaningless and they will sit in the surface fit distorting it.

**Static arbitrage.** `docs/architecture.md` lists an `arbitrage` module for "static bound
violations". It does not exist. There is no check for a price below intrinsic, a negative vertical
spread, or a butterfly with negative value — the classic signatures of a bad print, and exactly
what a relative-value strategy will otherwise pick up as its largest apparent edge.

That last one is worth stating plainly: **on real data, the first thing a residual-based strategy
finds is bad data.** A filter that runs before fitting is not defensive tidying, it is the thing
that decides whether any downstream result means anything.

---

## 5. Hard-coded rates in the strategy layer

```
backtest/residual_run.py:44:  RISK_FREE_RATE: Final[float] = 0.0425
```

used in three places to build a discount factor and a forward. That constant matches what
`ingestion/synthetic.py` planted, which is why it never mattered.

On real data it should come from `imply_forward_curve`, which is what that module is for. This is
a small change and it is easy to forget, because nothing fails — it just quietly biases every
implied volatility in the run.

`backtest/correlation_run.py` reads its rate from `correlation_truth.json`, a file only the
synthetic generator writes, so a real basket needs that path reworked too.

---

## 6. What each part of the stack needs from you

| you want to run | what it needs | present? |
|---|---|---|
| surface fitting, arbitrage scans | one clean snapshot | after §1 and §4 |
| `forward_curve`, `implied_vol`, `svi`, `essvi` | one clean snapshot per expiry | after §1 and §4 |
| `factors`, residual scoring | ~40+ observation dates, persistent contracts | after §2 |
| `backtest/residual_run.py` | 120 dates, plus §5 | after §2 and §5 |
| `walk_forward_run.py`, PBO, deflated Sharpe | 120 dates minimum, thousands to conclude | after §2 |
| `implied_correlation`, dispersion | index **and** every constituent, same dates | after §2, at universe scale |
| `risk/` gate against a venue | a `Broker` implementation that is not `PaperBroker` | not started |

The persistence point in row three is easy to miss. `docs/history_run.md` records that
re-rounding strikes daily produced 1,068 contracts, many quoted on a single day, and no residual
can be scored across time that way. Real chains add and drop strikes as spot moves, so a real
version of that problem is waiting: you will need a rule for which contracts constitute a series
worth scoring.

---

## 7. A staged order

**Stage one — make one real snapshot land.** Fix §1, add the missing seam test, run
`--source polygon --record-to` against one liquid underlying, and commit the recorded response as
a fixture. You now have a real chain that replays offline forever.

**Stage two — find out how bad it is.** Run `forward_curve` and `implied_vol` over it and count
what fails: no bid, crossed, below intrinsic, non-standard deliverable, inversion non-convergence.
This number is the §4 specification, and it should be measured rather than guessed.

**Stage three — build the filter.** The `arbitrage` module, plus deliverable and staleness gates.
Report what it rejects on every ingest, because that count is a data-quality signal in its own
right and a jump in it means something changed at the source.

**Stage four — decide accumulate versus backfill.** §2. This is the fork that determines whether
anything statistical is possible this year.

**Stage five — repoint the strategy layer.** §5, then re-run `residual_run` and
`walk_forward_run` on real dates and compare against the synthetic results. Expect them to be
worse. `docs/history_run.md` already showed the signal losing to the spread on data built to
contain it.

---

## 8. What will still be missing afterwards

**Step 6's fill model stays uncalibrated.** `execution` charges the full spread on every crossing
because that is the pessimistic assumption, and it has never been checked against a fill anybody
actually got. This is not a detail: it decided the outcome of `history_run.md` (−156,179 became
+45,098 once cost was priced properly), the go/no-go threshold there, and the entire dispersion
result (break-even at a 0.94% constituent half-spread). Real quotes do not fix it — only real
fills do, which means paper trading.

**Step 9's external validation stays open.** Recovering a correlation this repository planted is
not validation. It needs a published series to disagree with.

**Three of `runbook.md`'s four conditions stay unmet.** A quarter of paper trading, attribution on
realised paper P&L, and costs validated against observed fills. None can be produced by writing
code, and real market data does not produce them either — it is a precondition for starting the
quarter, not a substitute for it.

---

## Summary of code that has to change

| file | change |
|---|---|
| `ingestion/polygon.py` | emit `exercise_style` from a cash-settled index root table |
| `ingestion/tests/test_ingestion.py` | write recorded rows through `write_dataset` |
| `ingestion/writer.py` or a new merger | accumulate dates instead of replacing the dataset |
| new `ingestion/` adapter | flat-file backfill, if you go that route |
| new `arbitrage` module | static bound violations, before any fitting |
| `ingestion/polygon.py` | reject zero, crossed and stale quotes rather than defaulting them |
| downstream consumers | filter on `is_standard_deliverable` |
| `backtest/residual_run.py` | take the discount from `imply_forward_curve` |
| `backtest/correlation_run.py` | source the basket definition from something real |
| `docs/data.md` | says `option_chain_snapshot/v1`; the schema is `v2` |
