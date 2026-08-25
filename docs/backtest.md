# The backtest event loop

Three threads were waiting on this: step 5's attribution over many dates, step 6's fill
calibration, and the seam `research.md` left open when it said nothing yet writes a per-trial
return series to a store the registry can point at.

**Above the parity boundary: Python only.** The loop is orchestration over components that are
already tri-implemented and conformance tested — the as-of reader, the fill model, the pricer.
Reimplementing the sequencing in C++ would produce no comparison worth reading, which is the
criterion in `architecture.md`.

## The loop holds one reader per step, and that is the whole guarantee

`AsOfChainReader` is constructed **with** a knowledge horizon and refuses any observation time
past it. That protects a single query. It does not, on its own, protect a loop: a reader opened
once at the end of the run and asked for each step in turn would answer every one of them,
because the observation-time filter and the knowledge horizon are separate things. The
observation time would move and the horizon would not.

So the engine opens a reader per step, at that step's horizon, and the lookahead guarantee is
inherited rather than reimplemented. A test asserts the horizons the engine actually asked for,
in order, so the property is checked rather than described.

### What getting it wrong is worth

The synthetic dataset carries late corrections: 60 of its rows have an event time of 17:00 on
the 21st and a knowledge time of noon on the 22nd. At the 17:00 step, **every one of the 37 SPX
contracts has a revised quote that had not arrived yet.**

Running the same short-straddle strategy both ways:

| | gross | cost | net |
|---|---|---|---|
| a reader per step | `1,062.70` | `26,820.80` | `-25,758.10` |
| one reader opened late | `-5,201.60` | `26,820.80` | `-32,022.40` |

The difference is `6,264`, which is `24%` of the honest result — and it is worth noticing
which way it went. **Lookahead did not flatter the backtest, it made it worse.** The revisions
happened to move against the position. That is the more dangerous case of the two, because a
result that looks disappointing does not invite anybody to go looking for the bug.

The lesson is not "lookahead inflates returns". It is that lookahead is an uncontrolled error
of arbitrary sign, and the only defence is structural.

## Accounting

At each step, in this order:

1. mark the book **as it stands** at this step's mids, giving the holding profit since the
   previous step
2. ask the strategy for a target book
3. trade towards it at the touch, paying the full spread through `execution`
4. mark again, and carry those marks forward

Marking happens before trading so that a new position's profit is never counted in the step
that opened it. Marks are at mid; transactions cross the spread. Those are different
assumptions on purpose, and both are stated rather than blended into one "price".

A position whose contract is not quoted at a step is **carried at its last mark**, and the
count of such marks is reported per step. A position in a contract that has never been quoted
raises, because there is no honest price for it and a silent zero would show up as profit.

## What the pessimistic cost model does to a small book

On the three-step run above, a short straddle in eight contracts:

```
gross profit        1,062.70
transaction cost   26,820.80
net profit        -25,758.10
```

**The cost of opening the position is twenty-five times the gross profit of holding it.** That
is one round of crossing on eight legs, priced by the model in `execution.md`, against three
hours of market movement. It is a fixture rather than history and the number should not be read
as a result, but the shape of it is the argument for the go/no-go the program schedules after
step 6.

## The seam is closed

`backtest/run.py` performs the sequence the registry was built for:

1. compute the pins and `register_trial` **before** the run starts
2. run the backtest
3. write the return series to a content-addressed store
4. `record_outcome` carrying the series digest

The store files each series under the SHA-256 of its own canonical payload, and reading one
back re-derives the digest and refuses a file that does not hash to the name it is filed under.
So the chain runs both ways: the registry entry names a digest, and the series names the trial
and the dataset it came from.

That is what `research.md` said was missing. What it does **not** yet close is calibration of
the fill model against observed fills, which still needs paper trading, exactly as step 6's
bootstrap problem predicts.

## What this is not

Three observation times on one day is enough to prove a mechanism and nowhere near enough to
produce a result. There is no signal here, no hedging, and no portfolio construction; the
strategy in `run.py` exists to exercise the loop. Attribution over out-of-sample dates, which
is step 5's remaining clause, needs a dataset with dates in it.
