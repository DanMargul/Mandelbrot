from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
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


def nanoseconds_to_datetime(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=UTC)


def contract_row_from_snapshot(
    entry: dict[str, Any], received_at: datetime, ingest_sequence: int
) -> dict[str, Any] | None:
    details = entry.get("details")
    quote = entry.get("last_quote")
    underlying = entry.get("underlying_asset")
    if not details or not quote or not underlying:
        return None

    shares_per_contract = int(details.get("shares_per_contract", STANDARD_SHARES_PER_CONTRACT))
    quote_nanoseconds = quote.get("last_updated")
    event_time = nanoseconds_to_datetime(int(quote_nanoseconds)) if quote_nanoseconds else received_at

    return {
        "underlying_symbol": str(details["underlying_ticker"]),
        "contract_symbol": str(details["ticker"]).removeprefix("O:"),
        "expiry_date": datetime.strptime(str(details["expiration_date"]), "%Y-%m-%d").date(),
        "strike": float(details["strike_price"]),
        "option_type": "call" if str(details["contract_type"]) == "call" else "put",
        "contract_multiplier": shares_per_contract,
        "is_standard_deliverable": shares_per_contract == STANDARD_SHARES_PER_CONTRACT,
        "event_time": min(event_time, received_at),
        "knowledge_time": received_at,
        "ingest_sequence": ingest_sequence,
        "underlying_price": float(underlying["price"]),
        "bid_price": float(quote.get("bid", 0.0)),
        "ask_price": float(quote.get("ask", 0.0)),
        "bid_size": int(quote.get("bid_size", 0)),
        "ask_size": int(quote.get("ask_size", 0)),
        "last_trade_price": float(entry["last_trade"]["price"]) if entry.get("last_trade") else None,
        "volume": int(entry["day"]["volume"]) if entry.get("day", {}).get("volume") is not None else None,
        "open_interest": int(entry["open_interest"]) if entry.get("open_interest") is not None else None,
        "source": POLYGON_SOURCE,
    }


def rows_from_snapshot_pages(
    pages: list[dict[str, Any]], received_at: datetime, first_sequence: int = 0
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = first_sequence
    for page in pages:
        for entry in page.get("results", []):
            row = contract_row_from_snapshot(entry, received_at, sequence)
            if row is None:
                continue
            rows.append(row)
            sequence += 1
    return rows


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
