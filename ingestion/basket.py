from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.implied_correlation import (  # noqa: E402
    BasketConstituent,
    basket_volatility,
)
from volarb_py.pricing import (  # noqa: E402
    BlackScholesInputs,
    OptionType,
    black_scholes_price,
)
from volarb_py.random_source import (  # noqa: E402
    PcgState,
    next_standard_normal_pair,
    seeded_source,
)

BASKET_SOURCE: Final[str] = "synthetic_basket"
CORRELATION_TRUTH_FILENAME: Final[str] = "correlation_truth.json"
CORRELATION_TRUTH_SCHEMA: Final[str] = "planted_correlation_truth/v1"

INDEX_SYMBOL: Final[str] = "IDXB"
CONSTITUENT_COUNT: Final[int] = 8
WEIGHT_DECAY: Final[float] = 0.8
FIRST_OBSERVATION: Final[date] = date(2026, 1, 5)
OBSERVATION_DAYS: Final[int] = 60
OBSERVATION_HOUR_UTC: Final[int] = 20
EXPIRY_SETTLEMENT_HOUR_UTC: Final[int] = 21
DAYS_PER_YEAR: Final[float] = 365.0
STEPS_PER_YEAR: Final[float] = 252.0
RISK_FREE_RATE: Final[float] = 0.0425
STANDARD_MULTIPLIER: Final[int] = 100
LAST_WEEKDAY: Final[int] = 5

CORRELATION_MEAN: Final[float] = 0.45
CORRELATION_REVERSION: Final[float] = 0.10
CORRELATION_SHOCK: Final[float] = 0.055
LOWEST_PLANTED_CORRELATION: Final[float] = 0.05
HIGHEST_PLANTED_CORRELATION: Final[float] = 0.95

VOLATILITY_REVERSION: Final[float] = 0.04
VOLATILITY_SHOCK: Final[float] = 0.030
SKEW_SLOPE: Final[float] = -0.30
INDEX_SKEW_EXCESS: Final[float] = -0.35
CURVATURE: Final[float] = 0.45

INDEX_INITIAL_LEVEL: Final[float] = 1000.0
CONSTITUENT_INITIAL_PRICE: Final[float] = 100.0
BASE_VOLATILITY: Final[float] = 0.26
VOLATILITY_TIERS: Final[int] = 5
VOLATILITY_TIER_STEP: Final[float] = 0.02

INDEX_HALF_SPREAD: Final[float] = 0.006
CONSTITUENT_HALF_SPREAD: Final[float] = 0.020
MINIMUM_HALF_SPREAD: Final[float] = 0.02
STRIKE_OFFSETS: Final[tuple[float, ...]] = (-0.30, -0.15, 0.0, 0.15, 0.30)
EXPIRIES: Final[tuple[date, ...]] = (date(2026, 6, 19), date(2026, 9, 18))

BASKET_SEED: Final[int] = 20260119
BASKET_SEQUENCE: Final[int] = 23
LARGE_PRICE_THRESHOLD: Final[float] = 500.0
LARGE_STRIKE_STEP: Final[float] = 5.0
SMALL_STRIKE_STEP: Final[float] = 1.0


@dataclass
class BasketState:
    source: PcgState
    spare: float | None = None

    def normal(self) -> float:
        if self.spare is not None:
            value = self.spare
            self.spare = None
            return value
        pair = next_standard_normal_pair(self.source)
        self.source = pair.state
        self.spare = pair.second
        return pair.first


@dataclass(frozen=True)
class BasketName:
    symbol: str
    weight: float
    base_volatility: float
    half_spread: float


def constituent_names() -> list[BasketName]:
    raw = [1.0 / ((rank + 1) ** WEIGHT_DECAY) for rank in range(CONSTITUENT_COUNT)]
    total = sum(raw)
    return [
        BasketName(
            symbol=f"CN{rank:02d}",
            weight=weight / total,
            base_volatility=BASE_VOLATILITY + VOLATILITY_TIER_STEP * (rank % VOLATILITY_TIERS),
            half_spread=CONSTITUENT_HALF_SPREAD,
        )
        for rank, weight in enumerate(raw)
    ]


def business_days(count: int) -> list[date]:
    days: list[date] = []
    current = FIRST_OBSERVATION
    while len(days) < count:
        if current.weekday() < LAST_WEEKDAY:
            days.append(current)
        current += timedelta(days=1)
    return days


def occ_contract_symbol(underlying: str, expiry: date, option_type: OptionType, strike: float) -> str:
    letter = "C" if option_type == "call" else "P"
    return f"{underlying}{expiry:%y%m%d}{letter}{round(strike * 1000):08d}"


def rounded_strike(price: float, offset: float) -> float:
    step = LARGE_STRIKE_STEP if price > LARGE_PRICE_THRESHOLD else SMALL_STRIKE_STEP
    return round(price * (1.0 + offset) / step) * step


def years_between(moment: datetime, expiry: date) -> float:
    settlement = datetime(expiry.year, expiry.month, expiry.day, EXPIRY_SETTLEMENT_HOUR_UTC, 0, 0, tzinfo=UTC)
    return (settlement - moment).total_seconds() / (DAYS_PER_YEAR * 24.0 * 3600.0)


def skewed_volatility(level: float, strike: float, forward: float, skew_slope: float) -> float:
    moneyness = math.log(strike / forward)
    return max(level * math.exp(skew_slope * moneyness + CURVATURE * moneyness * moneyness), 0.01)


@dataclass(frozen=True)
class QuoteRequest:
    underlying_symbol: str
    expiry: date
    option_type: OptionType
    strike: float
    moment: datetime


@dataclass(frozen=True)
class QuoteMarket:
    spot: float
    volatility_level: float
    half_spread_fraction: float
    skew_slope: float


def quoted_row(request: QuoteRequest, market: QuoteMarket, sequence: int) -> dict[str, Any]:
    years = years_between(request.moment, request.expiry)
    discount = math.exp(-RISK_FREE_RATE * years)
    forward = market.spot / discount
    volatility = skewed_volatility(market.volatility_level, request.strike, forward, market.skew_slope)
    price = black_scholes_price(
        BlackScholesInputs(forward, request.strike, years, volatility, discount, request.option_type)
    )
    half_spread = max(market.half_spread_fraction * price, MINIMUM_HALF_SPREAD)
    return {
        "underlying_symbol": request.underlying_symbol,
        "contract_symbol": occ_contract_symbol(
            request.underlying_symbol, request.expiry, request.option_type, request.strike
        ),
        "expiry_date": request.expiry,
        "strike": request.strike,
        "option_type": request.option_type,
        "contract_multiplier": STANDARD_MULTIPLIER,
        "is_standard_deliverable": True,
        "exercise_style": "european",
        "event_time": request.moment,
        "knowledge_time": request.moment,
        "ingest_sequence": sequence,
        "underlying_price": market.spot,
        "bid_price": round(max(price - half_spread, 0.01), 4),
        "ask_price": round(price + half_spread, 4),
        "bid_size": 25,
        "ask_size": 25,
        "last_trade_price": None,
        "volume": None,
        "open_interest": None,
        "source": BASKET_SOURCE,
    }


def stepped_correlation(previous: float, state: BasketState) -> float:
    moved = (
        previous * (1.0 - CORRELATION_REVERSION)
        + CORRELATION_REVERSION * CORRELATION_MEAN
        + CORRELATION_SHOCK * state.normal()
    )
    return min(max(moved, LOWEST_PLANTED_CORRELATION), HIGHEST_PLANTED_CORRELATION)


def advanced_prices(
    prices: list[float], levels: list[float], correlation: float, state: BasketState
) -> list[float]:
    step = 1.0 / STEPS_PER_YEAR
    common = state.normal()
    shared = math.sqrt(correlation)
    idiosyncratic = math.sqrt(1.0 - correlation)
    moved: list[float] = []
    for price, level in zip(prices, levels, strict=True):
        shock = shared * common + idiosyncratic * state.normal()
        drift = -0.5 * level * level * step
        moved.append(price * math.exp(drift + level * math.sqrt(step) * shock))
    return moved


def advanced_levels(levels: list[float], names: list[BasketName], state: BasketState) -> list[float]:
    moved: list[float] = []
    for level, name in zip(levels, names, strict=True):
        moved.append(
            level * (1.0 - VOLATILITY_REVERSION)
            + VOLATILITY_REVERSION * name.base_volatility
            + VOLATILITY_SHOCK * state.normal()
        )
    return moved


def index_level_of(prices: list[float], names: list[BasketName]) -> float:
    weighted = 0.0
    for price, name in zip(prices, names, strict=True):
        weighted += name.weight * price
    return INDEX_INITIAL_LEVEL * weighted / CONSTITUENT_INITIAL_PRICE


def index_volatility_of(levels: list[float], names: list[BasketName], correlation: float) -> float:
    constituents = [
        BasketConstituent(name.symbol, name.weight, level) for name, level in zip(names, levels, strict=True)
    ]
    return basket_volatility(constituents, correlation)


@dataclass(frozen=True)
class DayState:
    moment: datetime
    correlation: float
    index_level: float
    index_volatility: float
    prices: list[float]
    levels: list[float]


def day_states() -> list[DayState]:
    state = BasketState(source=seeded_source(BASKET_SEED, BASKET_SEQUENCE))
    names = constituent_names()
    prices = [CONSTITUENT_INITIAL_PRICE] * CONSTITUENT_COUNT
    levels = [name.base_volatility for name in names]
    correlation = CORRELATION_MEAN
    states: list[DayState] = []
    for day in business_days(OBSERVATION_DAYS):
        correlation = stepped_correlation(correlation, state)
        prices = advanced_prices(prices, levels, correlation, state)
        levels = advanced_levels(levels, names, state)
        states.append(
            DayState(
                moment=datetime(day.year, day.month, day.day, OBSERVATION_HOUR_UTC, 0, 0, tzinfo=UTC),
                correlation=correlation,
                index_level=index_level_of(prices, names),
                index_volatility=index_volatility_of(levels, names, correlation),
                prices=list(prices),
                levels=list(levels),
            )
        )
    return states


def strike_ladder(reference_price: float) -> list[float]:
    return [rounded_strike(reference_price, offset) for offset in STRIKE_OFFSETS]


def rows_for_underlying(
    symbol: str, ladder: list[float], market: QuoteMarket, moment: datetime, sequence: int
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    for expiry in EXPIRIES:
        for strike in ladder:
            for option_type in ("call", "put"):
                rows.append(
                    quoted_row(QuoteRequest(symbol, expiry, option_type, strike, moment), market, sequence)
                )
                sequence += 1
    return rows, sequence


def basket_rows(
    constituent_half_spread: float = CONSTITUENT_HALF_SPREAD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    names = constituent_names()
    states = day_states()
    index_ladder = strike_ladder(INDEX_INITIAL_LEVEL)
    name_ladders = {name.symbol: strike_ladder(CONSTITUENT_INITIAL_PRICE) for name in names}

    rows: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    sequence = 0
    for state in states:
        index_market = QuoteMarket(
            state.index_level,
            state.index_volatility,
            INDEX_HALF_SPREAD,
            SKEW_SLOPE + INDEX_SKEW_EXCESS,
        )
        produced, sequence = rows_for_underlying(
            INDEX_SYMBOL, index_ladder, index_market, state.moment, sequence
        )
        rows.extend(produced)
        for name, price, level in zip(names, state.prices, state.levels, strict=True):
            market = QuoteMarket(price, level, constituent_half_spread, SKEW_SLOPE)
            produced, sequence = rows_for_underlying(
                name.symbol, name_ladders[name.symbol], market, state.moment, sequence
            )
            rows.extend(produced)
        truth.append(
            {
                "observation_date": f"{state.moment:%Y-%m-%d}",
                "correlation": state.correlation,
                "index_level": state.index_level,
                "index_volatility": state.index_volatility,
                "constituent_volatility": {
                    name.symbol: level for name, level in zip(names, state.levels, strict=True)
                },
            }
        )
    return rows, truth


def write_correlation_truth(
    dataset_root: Path, truth: list[dict[str, Any]], constituent_half_spread: float
) -> None:
    payload = {
        "schema": CORRELATION_TRUTH_SCHEMA,
        "index_symbol": INDEX_SYMBOL,
        "correlation_mean": CORRELATION_MEAN,
        "correlation_reversion": CORRELATION_REVERSION,
        "risk_free_rate": RISK_FREE_RATE,
        "observation_hour_utc": OBSERVATION_HOUR_UTC,
        "expiry_settlement_hour_utc": EXPIRY_SETTLEMENT_HOUR_UTC,
        "index_skew_excess": INDEX_SKEW_EXCESS,
        "index_half_spread": INDEX_HALF_SPREAD,
        "constituent_half_spread": constituent_half_spread,
        "expiry_dates": [f"{expiry:%Y-%m-%d}" for expiry in EXPIRIES],
        "weights": {name.symbol: name.weight for name in constituent_names()},
        "observations": truth,
    }
    (dataset_root / CORRELATION_TRUTH_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
