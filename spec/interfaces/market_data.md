# `market_data`

Below the parity boundary. Three implementations, conformance tested.

Ingestion is *above* the boundary and is not specified here; see `docs/data.md`. This file
covers only the reader, which is on the backtest inner loop.

## Types

```
KnowledgeHorizon:
    as_of: Timestamp

ChainQuery:
    underlying_symbol: str
    observation_time: Timestamp
    knowledge_horizon: Timestamp
    include_adjusted_contracts: bool

ContractQuote:
    contract_symbol: str
    expiry_date: Date
    strike: float
    option_type: OptionType
    contract_multiplier: int
    is_standard_deliverable: bool
    event_time: Timestamp
    knowledge_time: Timestamp
    ingest_sequence: int
    underlying_price: float
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int
```

## Functions

```
open_chain_dataset(dataset_root: Path, horizon: KnowledgeHorizon) -> AsOfChainReader
AsOfChainReader.chain_as_of(query: ChainQuery) -> list[ContractQuote]
```

`open_chain_dataset` is the only constructor. The horizon is bound there and is immutable
afterwards. The reader exposes no operation that returns a row past it, no flag that
disables the filter, and no accessor for the underlying table.

## Resolution semantics

Defined in full in `docs/data.md`. Restated here because all three tracks must implement it
identically:

```
candidates = rows where knowledge_time <= horizon and event_time <= observation_time
result     = per contract_symbol, the candidate maximising
             (event_time, knowledge_time, ingest_sequence)
```

`ingest_sequence` is in the ordering key solely to make the maximum unique. Two rows tied on
both timestamps would otherwise resolve by physical file order, and three independent
implementations cannot be relied on to agree about that. The tiebreak is contract, not
implementation detail.

Results are returned sorted by `(expiry_date, strike, option_type, contract_symbol)`.
Sorting is part of the contract because conformance compares documents, and an unsorted
result would make two correct implementations look different.

## Errors

| condition | outcome |
|---|---|
| `observation_time > knowledge_horizon` | typed error, never a filtered result |
| `knowledge_time < event_time` in the data | typed error at read, the ingester is broken |
| dataset root missing or manifest unreadable | typed error |
| underlying absent from the dataset | empty result, not an error |

The first is the one that matters. A query whose observation time is past its horizon is
the exact bug this module exists to prevent, and answering it with a plausible filtered
result would hide it.

## Adjusted contracts

Excluded unless `include_adjusted_contracts` is set. See `docs/data.md`; the failure mode
being designed against is not an error but a slightly wrong answer.

## Verb

`read-chain-as-of`, input `chain_query/v1`, output `chain_snapshot/v1`.

One input record is one query. Output record ids are `"{query_id}|{contract_symbol}"`, so a
document may carry several queries while every record id stays unique and conformance can
keep comparing by identity.

## Invariants under test

- a query at a horizon before a row's `knowledge_time` never returns that row
- raising only the horizon can add rows and can replace a row with a newer revision; it can
  never remove a contract that was already present
- advancing only the observation time can replace a row with a newer revision; it can never
  return a row whose `event_time` is past the observation time
- a corrected print is invisible below its `knowledge_time` and authoritative above it
- adjusted contracts are absent by default and present when requested
- the result is sorted, and the sort is total
