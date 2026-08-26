from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

POLYGON_BASE_URL: Final[str] = "https://api.polygon.io"
POLYGON_API_KEY_VARIABLE: Final[str] = "POLYGON_API_KEY"
SNAPSHOT_PAGE_LIMIT: Final[int] = 250
MAXIMUM_ATTEMPTS: Final[int] = 5
INITIAL_BACKOFF_SECONDS: Final[float] = 1.0
RATE_LIMITED_STATUS: Final[int] = 429
LOWEST_SERVER_ERROR_STATUS: Final[int] = 500
STANDARD_SHARES_PER_CONTRACT: Final[int] = 100
POLYGON_SOURCE: Final[str] = "polygon"
INDEX_UNDERLYING_PREFIX: Final[str] = "I:"
EUROPEAN_STYLE: Final[str] = "european"
AMERICAN_STYLE: Final[str] = "american"

AMERICAN_INDEX_ROOTS: Final[frozenset[str]] = frozenset({"OEX"})
EUROPEAN_INDEX_ROOTS: Final[frozenset[str]] = frozenset(
    {"SPX", "SPXW", "XSP", "NDX", "NDXP", "RUT", "RUTW", "VIX", "VIXW", "DJX", "XEO"}
)

MISSING_DETAILS: Final[str] = "no contract details"
MISSING_QUOTE: Final[str] = "no quote"
MISSING_UNDERLYING_PRICE: Final[str] = "no underlying price"
INCOMPLETE_QUOTE: Final[str] = "a one sided quote"
NON_POSITIVE_ASK: Final[str] = "an ask of nothing"
CROSSED_QUOTE: Final[str] = "a crossed book"


class PolygonError(RuntimeError):
    pass


class MissingApiKeyError(PolygonError):
    pass


def api_key_from_environment() -> str:
    key = os.environ.get(POLYGON_API_KEY_VARIABLE, "").strip()
    if not key:
        raise MissingApiKeyError(
            f"{POLYGON_API_KEY_VARIABLE} is not set; use --source recorded or --source synthetic"
        )
    return key


def request_with_backoff(url: str, api_key: str) -> dict[str, Any]:
    separator = "&" if "?" in url else "?"
    authorised = f"{url}{separator}apiKey={urllib.parse.quote(api_key)}"
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(1, MAXIMUM_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(authorised, timeout=60) as response:
                payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
                return payload
        except urllib.error.HTTPError as error:
            retryable = error.code == RATE_LIMITED_STATUS or error.code >= LOWEST_SERVER_ERROR_STATUS
            if not retryable or attempt == MAXIMUM_ATTEMPTS:
                raise PolygonError(f"{url} failed with HTTP {error.code}") from error
        except urllib.error.URLError as error:
            if attempt == MAXIMUM_ATTEMPTS:
                raise PolygonError(f"{url} failed: {error.reason}") from error
        time.sleep(backoff)
        backoff *= 2.0
    raise PolygonError(f"{url} exhausted {MAXIMUM_ATTEMPTS} attempts")


def snapshot_pages(underlying_symbol: str, api_key: str) -> list[dict[str, Any]]:
    url = (
        f"{POLYGON_BASE_URL}/v3/snapshot/options/{urllib.parse.quote(underlying_symbol)}"
        f"?limit={SNAPSHOT_PAGE_LIMIT}"
    )
    pages: list[dict[str, Any]] = []
    while url:
        page = request_with_backoff(url, api_key)
        pages.append(page)
        url = page.get("next_url", "")
    return pages


def underlying_root(underlying_ticker: str) -> str:
    return underlying_ticker.removeprefix(INDEX_UNDERLYING_PREFIX)


def exercise_style_for(underlying_ticker: str) -> str:
    root = underlying_root(underlying_ticker)
    if root in AMERICAN_INDEX_ROOTS:
        return AMERICAN_STYLE
    if underlying_ticker.startswith(INDEX_UNDERLYING_PREFIX) or root in EUROPEAN_INDEX_ROOTS:
        return EUROPEAN_STYLE
    return AMERICAN_STYLE


def quote_rejection(quote: dict[str, Any]) -> str | None:
    if quote.get("bid") is None or quote.get("ask") is None:
        return INCOMPLETE_QUOTE
    if float(quote["ask"]) <= 0.0:
        return NON_POSITIVE_ASK
    if float(quote["bid"]) > float(quote["ask"]):
        return CROSSED_QUOTE
    return None


def rejection_reason(entry: dict[str, Any]) -> str | None:
    quote = entry.get("last_quote")
    underlying = entry.get("underlying_asset")
    if not entry.get("details"):
        return MISSING_DETAILS
    if not quote:
        return MISSING_QUOTE
    if not underlying or underlying.get("price") is None:
        return MISSING_UNDERLYING_PRICE
    return quote_rejection(quote)


def nanoseconds_to_datetime(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=UTC)


def contract_row_from_snapshot(
    entry: dict[str, Any], received_at: datetime, ingest_sequence: int
) -> dict[str, Any] | None:
    if rejection_reason(entry) is not None:
        return None
    details = entry["details"]
    quote = entry["last_quote"]
    underlying = entry["underlying_asset"]

    shares_per_contract = int(details.get("shares_per_contract", STANDARD_SHARES_PER_CONTRACT))
    quote_nanoseconds = quote.get("last_updated")
    event_time = nanoseconds_to_datetime(int(quote_nanoseconds)) if quote_nanoseconds else received_at

    return {
        "underlying_symbol": underlying_root(str(details["underlying_ticker"])),
        "contract_symbol": str(details["ticker"]).removeprefix("O:"),
        "expiry_date": datetime.strptime(str(details["expiration_date"]), "%Y-%m-%d").date(),
        "strike": float(details["strike_price"]),
        "option_type": "call" if str(details["contract_type"]) == "call" else "put",
        "contract_multiplier": shares_per_contract,
        "is_standard_deliverable": shares_per_contract == STANDARD_SHARES_PER_CONTRACT,
        "exercise_style": exercise_style_for(str(details["underlying_ticker"])),
        "event_time": min(event_time, received_at),
        "knowledge_time": received_at,
        "ingest_sequence": ingest_sequence,
        "underlying_price": float(underlying["price"]),
        "bid_price": float(quote["bid"]),
        "ask_price": float(quote["ask"]),
        "bid_size": int(quote.get("bid_size", 0)),
        "ask_size": int(quote.get("ask_size", 0)),
        "last_trade_price": float(entry["last_trade"]["price"]) if entry.get("last_trade") else None,
        "volume": int(entry["day"]["volume"]) if entry.get("day", {}).get("volume") is not None else None,
        "open_interest": int(entry["open_interest"]) if entry.get("open_interest") is not None else None,
        "source": POLYGON_SOURCE,
    }


@dataclass(frozen=True)
class SnapshotRows:
    rows: list[dict[str, Any]]
    rejected: dict[str, int]


def mapped_snapshot_pages(
    pages: list[dict[str, Any]], received_at: datetime, first_sequence: int = 0
) -> SnapshotRows:
    rows: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    sequence = first_sequence
    for page in pages:
        for entry in page.get("results", []):
            reason = rejection_reason(entry)
            if reason is not None:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            row = contract_row_from_snapshot(entry, received_at, sequence)
            if row is None:
                continue
            rows.append(row)
            sequence += 1
    return SnapshotRows(rows, rejected)


def rows_from_snapshot_pages(
    pages: list[dict[str, Any]], received_at: datetime, first_sequence: int = 0
) -> list[dict[str, Any]]:
    return mapped_snapshot_pages(pages, received_at, first_sequence).rows


def record_pages(destination: Path, underlying_symbol: str, pages: list[dict[str, Any]]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    payload = {"underlying_symbol": underlying_symbol, "pages": pages}
    (destination / f"{underlying_symbol}.snapshot.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def replay_pages(source_directory: Path, underlying_symbol: str) -> list[dict[str, Any]]:
    path = source_directory / f"{underlying_symbol}.snapshot.json"
    if not path.exists():
        raise PolygonError(f"no recorded snapshot at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    pages: list[dict[str, Any]] = payload["pages"]
    return pages
