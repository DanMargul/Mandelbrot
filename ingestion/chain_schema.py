from __future__ import annotations

from typing import Final

import pyarrow

CHAIN_SCHEMA_ID: Final[str] = "option_chain_snapshot/v1"

OPTION_CHAIN_SNAPSHOT_SCHEMA: Final[pyarrow.Schema] = pyarrow.schema(
    [
        pyarrow.field("underlying_symbol", pyarrow.string(), nullable=False),
        pyarrow.field("contract_symbol", pyarrow.string(), nullable=False),
        pyarrow.field("expiry_date", pyarrow.date32(), nullable=False),
        pyarrow.field("strike", pyarrow.float64(), nullable=False),
        pyarrow.field("option_type", pyarrow.string(), nullable=False),
        pyarrow.field("contract_multiplier", pyarrow.int32(), nullable=False),
        pyarrow.field("is_standard_deliverable", pyarrow.bool_(), nullable=False),
        pyarrow.field("event_time", pyarrow.timestamp("us", tz="UTC"), nullable=False),
        pyarrow.field("knowledge_time", pyarrow.timestamp("us", tz="UTC"), nullable=False),
        pyarrow.field("ingest_sequence", pyarrow.int64(), nullable=False),
        pyarrow.field("underlying_price", pyarrow.float64(), nullable=False),
        pyarrow.field("bid_price", pyarrow.float64(), nullable=False),
        pyarrow.field("ask_price", pyarrow.float64(), nullable=False),
        pyarrow.field("bid_size", pyarrow.int64(), nullable=False),
        pyarrow.field("ask_size", pyarrow.int64(), nullable=False),
        pyarrow.field("last_trade_price", pyarrow.float64(), nullable=True),
        pyarrow.field("volume", pyarrow.int64(), nullable=True),
        pyarrow.field("open_interest", pyarrow.int64(), nullable=True),
        pyarrow.field("source", pyarrow.string(), nullable=False),
    ],
    metadata={b"schema_id": CHAIN_SCHEMA_ID.encode()},
)
