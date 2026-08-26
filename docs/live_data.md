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

## 1. The real-data path was broken, and is now fixed

**Fixed in this repository.** Recorded here because the shape of the failure is worth keeping,
and because the exercise-style table needs your review.

```
uv run ingestion/run.py --source recorded --underlying SPXTEST --dataset-root /tmp/x
KeyError: 'exercise_style'
```

`spec/schemas` gained a non-nullable `exercise_style` column in commit `d7482bb`. The three
synthetic generators were updated. **`ingestion/polygon.py` was not**, so every row it produces
is missing a required column and `write_dataset` raises on the first partition.

It went unnoticed because of a gap in the tests, which is worth understanding before you patch
it: `ingestion/tests/test_ingestion.py` exercises `rows_from_snapshot_pages` against the recorded
fixture, and separately exercises `write_dataset` against **synthetic** rows. It never writes
recorded rows. The mapper is tested, the writer is tested, and the seam between them is not.

### What the fix decides, and what you should check

Adding `"exercise_style": "european"` would make the error go away and be wrong for most of the
universe. Polygon's snapshot has no exercise-style field, so the value is decided from the
underlying:

- **Cash-settled index options are European** — SPX, XSP, NDX, RUT, VIX.
- **Listed equity and ETF options are American** — every single name, and SPY, QQQ, IWM.

This is not cosmetic. `spec/interfaces/american.md` prices the early-exercise premium, and
`forward_curve.md` strips that premium before fitting parity. Label an American chain European
and the parity fit absorbs the premium into the forward, which shifts every implied volatility in
the slice and appears downstream as mispricing that is not there.

`exercise_style_for` in `ingestion/polygon.py` now resolves it three ways, in order: an explicit
American-index exception (`OEX`, which is the trap — an index option that is American-style);
then Polygon's own `I:` index marker on `underlying_ticker`, which covers anything it labels an
index; then a fallback list of cash-settled roots for feeds that do not mark them. Anything else
is `american`, which is right for every listed equity and ETF.

**Two things for you to check.** The `I:` prefix carries most of the weight and it is asserted
from Polygon's documented shape rather than from a response this repository has seen — confirm it
against your first real pull. And `EUROPEAN_INDEX_ROOTS` is a fallback list, not an authority;
adding a root is one line, and a wrong entry there is silent.

The prefix is also stripped from `underlying_symbol`, so an `I:SPX` chain partitions under `SPX`.

`write_dataset` is now exercised against recorded rows in `ingestion/tests/test_ingestion.py`, so
this seam cannot silently break again.

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
a ten-configuration search needed about **3,990 observations**. Accumulating forward gets there
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

**Zero, missing and crossed prices are now rejected at ingest, not defaulted.** This used to do
`float(quote.get("bid", 0.0))`, so a contract with no bid became a row quoting zero. A contract is
now dropped when it has no details, no quote, no underlying price, only one side of a market, an
ask of zero, or a crossed book. A bid of zero against a positive ask is kept, because
`0.00 / 0.05` is a real market for a deep out-of-the-money contract and dropping it would discard
data rather than defects.

Every rejection is counted by reason and printed on every ingest, together with the exercise style
assigned per underlying:

```
  exercise style  SPXTEST      american        2 contracts
  rejected        no quote                     1 contracts
```

Watch that second block. A jump in it means something changed at the source, and an exercise style
you did not expect is the failure mode §1 warns about, visible immediately rather than three
modules downstream.

**Stale quotes.** `event_time` comes from `last_quote.last_updated`. An illiquid contract may not
have printed in days, and it will be inverted as though it were current — nothing between the
reader and the strategy carries a staleness horizon, though `risk/` has one for its own marks.
There is a second effect that matters only once you start accumulating: `writer.partition_key`
uses `event_time.date()`, so a single pull scatters across several date partitions, and a later
pull writes into the same ones. The reader itself copes — `_readable_partitions` takes every
partition with `minimum_event_time` at or before the query and resolves to the latest quote per
contract — so nothing goes missing. The problem is layout and collision, not correctness.

**Non-standard deliverables are already handled**, which is worth knowing so you do not build it
twice. `ChainQuery.include_adjusted_contracts` defaults to `False` and `chain_as_of` filters on
`is_standard_deliverable`, so post-split and post-merger contracts are excluded unless you ask
for them. Verify it holds for your data rather than assuming: Polygon's
`shares_per_contract` is what the flag is derived from.

**Static arbitrage.** `docs/architecture.md` lists an `arbitrage` module for "static bound
violations". It does not exist. There is no check for a price below intrinsic, a negative vertical
spread, or a butterfly with negative value — the classic signatures of a bad print, and exactly
what a relative-value strategy will otherwise pick up as its largest apparent edge.

That last one is worth stating plainly: **on real data, the first thing a residual-based strategy
finds is bad data.** A filter that runs before fitting is not defensive tidying, it is the thing
that decides whether any downstream result means anything.

---

## 5. Hard-coded rates in the strategy layer

**Fixed, and the fix found two other things.**

`backtest/residual_run.py` built its discount factor from a hard-coded `0.0425` in three places.
That constant is exactly what the generator planted, so it was right by construction and would
have been silently wrong on any real chain — nothing fails, it just biases every implied
volatility. It now takes the forward and discount factor per expiry from `imply_forward_curve`,
which is what `forward_curve.md` exists for. On the index the backtest is bit-identical, because
implied parity recovers the planted forward exactly.

**It exposed a generator defect.** `ingestion/history.py` labelled `NAMEH` `american` while
pricing it with Black-Scholes. `synthetic.py` does this correctly — European to Black-Scholes,
American to the Richardson lattice — and `history.py` did not. The forward curve then tried to
strip an early-exercise premium that was not in the data. The prices are European, so the label
was corrected; genuine American contracts live in `synthetic_chain`.

**And it exposed a cost you will hit.** Stripping American premia took the same backtest from
four seconds to **5m43s**, about `2.9` seconds per observation date for a *forty-contract* chain,
in the Python track. Every listed single name is American. A real universe is thousands of
contracts across hundreds of names, and this sits on the inner loop of every backtest. Two things
follow: budget for it, and note that `forward_curve` is below the parity boundary and tri-
implemented, while `backtest/` is Python-only and therefore calls the slow track. That is the
first place the boundary costs something rather than buying something.

One rate remains. `backtest/correlation_run.py` reads its rate from `correlation_truth.json`, a
file only the synthetic generator writes, so a real basket needs that path reworked. It is not
fixed because there is nothing real to point it at yet.

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
+47,668 once cost was priced properly), the go/no-go threshold there, and the entire dispersion
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

### Done in this repository

| file | change |
|---|---|
| `ingestion/polygon.py` | emit `exercise_style`; strip the `I:` prefix from `underlying_symbol` |
| `ingestion/polygon.py` | reject zero, one-sided and crossed quotes rather than defaulting them |
| `ingestion/run.py` | report rejections by reason and exercise style by underlying, every ingest |
| `ingestion/tests/test_ingestion.py` | write recorded rows through `write_dataset` |
| `ingestion/history.py` | stop labelling Black-Scholes prices `american` |
| `backtest/residual_run.py` | take the forward and discount from `imply_forward_curve` |
| `docs/data.md` | said `option_chain_snapshot/v1`; the schema is `v2` |

### Still yours

| file | change | why it was not done here |
|---|---|---|
| `ingestion/writer.py` or a new merger | accumulate dates instead of replacing the dataset | §2 is a fork, and picking it for you would foreclose the other route |
| new `ingestion/` adapter | flat-file backfill | same fork |
| new `arbitrage` module | static bound violations, before any fitting | a module to build, not a defect to repair; §7 stage two should specify it from measurement |
| strategy and backtest layers | a staleness horizon on quotes | needs a policy number that only real data can justify |
| `backtest/correlation_run.py` | source the basket definition from something real | nothing real to point it at yet |
| `EUROPEAN_INDEX_ROOTS` | review against the universe you actually trade | it is a fallback list, not an authority |
