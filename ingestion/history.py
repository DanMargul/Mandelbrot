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

HISTORY_SOURCE: Final[str] = "synthetic_history"
SIGNAL_TRUTH_FILENAME: Final[str] = "signal_truth.json"
SIGNAL_TRUTH_SCHEMA: Final[str] = "planted_signal_truth/v1"

FIRST_OBSERVATION: Final[date] = date(2026, 1, 5)
OBSERVATION_HOUR_UTC: Final[int] = 20
OBSERVATION_DAYS: Final[int] = 120
DAYS_PER_YEAR: Final[float] = 365.0
EXPIRY_SETTLEMENT_HOUR_UTC: Final[int] = 21
RISK_FREE_RATE: Final[float] = 0.0425
STANDARD_MULTIPLIER: Final[int] = 100

LEVEL_REVERSION: Final[float] = 0.03
LEVEL_SHOCK: Final[float] = 0.035
SKEW_REVERSION: Final[float] = 0.02
SKEW_SHOCK: Final[float] = 0.010
RICHNESS_REVERSION: Final[float] = 0.12
RICHNESS_SHOCK: Final[float] = 0.030

HISTORY_SEED: Final[int] = 20260105
HISTORY_SEQUENCE: Final[int] = 11
LAST_WEEKDAY: Final[int] = 5
LARGE_PRICE_THRESHOLD: Final[float] = 1000.0
LARGE_STRIKE_STEP: Final[float] = 5.0
SMALL_STRIKE_STEP: Final[float] = 2.5
STRIKE_MATCH_TOLERANCE: Final[float] = 1e-9


@dataclass(frozen=True)
class HistoryUnderlying:
    symbol: str
    initial_price: float
    base_volatility: float
    price_volatility: float
    proportional_half_spread: float
    minimum_half_spread: float
    strike_offsets: tuple[float, ...]
    rich_strike_offsets: tuple[float, ...]


UNDERLYINGS: Final[tuple[HistoryUnderlying, ...]] = (
    HistoryUnderlying(
        symbol="IDXH",
        initial_price=4800.0,
        base_volatility=0.17,
        price_volatility=0.16,
        proportional_half_spread=0.010,
        minimum_half_spread=0.10,
        strike_offsets=(-0.10, -0.05, 0.0, 0.05, 0.10),
        rich_strike_offsets=(-0.05, 0.05),
    ),
    HistoryUnderlying(
        symbol="NAMEH",
        initial_price=190.0,
        base_volatility=0.29,
        price_volatility=0.30,
        proportional_half_spread=0.030,
        minimum_half_spread=0.02,
        strike_offsets=(-0.10, -0.05, 0.0, 0.05, 0.10),
        rich_strike_offsets=(0.0,),
    ),
)

EXPIRIES: Final[tuple[date, ...]] = (date(2026, 9, 18), date(2026, 12, 18))


@dataclass(frozen=True)
class QuoteRequest:
    underlying: HistoryUnderlying
    expiry: date
    option_type: OptionType
    strike: float
    moment: datetime
    spot: float
    volatility: float


@dataclass(frozen=True)
class SurfaceFactors:
    level: float
    skew: float


@dataclass
class HistoryState:
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


def fair_volatility(
    underlying: HistoryUnderlying,
    factors: SurfaceFactors,
    strike: float,
    forward: float,
    years: float,
) -> float:
    moneyness = math.log(strike / forward)
    level = underlying.base_volatility * math.exp(factors.level)
    tilt = factors.skew * moneyness + 0.55 * moneyness * moneyness
    term = 1.0 + 0.03 * math.log(max(years, 1e-6) / 0.5)
    return max(level * math.exp(tilt) * term, 0.01)


def half_spread_for(underlying: HistoryUnderlying, price: float) -> float:
    return max(underlying.proportional_half_spread * price, underlying.minimum_half_spread)


def quoted_row(request: QuoteRequest, sequence: int) -> dict[str, Any]:
    underlying = request.underlying
    years = years_between(request.moment, request.expiry)
    discount = math.exp(-RISK_FREE_RATE * years)
    forward = request.spot / discount
    price = black_scholes_price(
        BlackScholesInputs(forward, request.strike, years, request.volatility, discount, request.option_type)
    )
    half_spread = half_spread_for(underlying, max(price, underlying.minimum_half_spread))
    return {
        "underlying_symbol": underlying.symbol,
        "contract_symbol": occ_contract_symbol(
            underlying.symbol, request.expiry, request.option_type, request.strike
        ),
        "expiry_date": request.expiry,
        "strike": request.strike,
        "option_type": request.option_type,
        "contract_multiplier": STANDARD_MULTIPLIER,
        "is_standard_deliverable": True,
        "exercise_style": "european" if underlying.symbol == "IDXH" else "american",
        "event_time": request.moment,
        "knowledge_time": request.moment,
        "ingest_sequence": sequence,
        "underlying_price": request.spot,
        "bid_price": round(max(price - half_spread, 0.01), 4),
        "ask_price": round(price + half_spread, 4),
        "bid_size": 25,
        "ask_size": 25,
        "last_trade_price": None,
        "volume": None,
        "open_interest": None,
        "source": HISTORY_SOURCE,
    }


def strike_ladder(underlying: HistoryUnderlying) -> list[float]:
    return [rounded_strike(underlying.initial_price, offset) for offset in underlying.strike_offsets]


def rich_strikes(underlying: HistoryUnderlying) -> list[float]:
    return [rounded_strike(underlying.initial_price, offset) for offset in underlying.rich_strike_offsets]


def is_rich(underlying: HistoryUnderlying, strike: float) -> bool:
    return any(abs(strike - rich) < STRIKE_MATCH_TOLERANCE for rich in rich_strikes(underlying))


def history_rows(richness_amplitude: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state = HistoryState(source=seeded_source(HISTORY_SEED, HISTORY_SEQUENCE))
    days = business_days(OBSERVATION_DAYS)
    step_years = 1.0 / 252.0

    spots = {underlying.symbol: underlying.initial_price for underlying in UNDERLYINGS}
    factors = {underlying.symbol: SurfaceFactors(0.0, -0.35) for underlying in UNDERLYINGS}
    richness = {underlying.symbol: 0.0 for underlying in UNDERLYINGS}

    rows: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    sequence = 0
    for day in days:
        moment = datetime(day.year, day.month, day.day, OBSERVATION_HOUR_UTC, 0, 0, tzinfo=UTC)
        for underlying in UNDERLYINGS:
            symbol = underlying.symbol
            drift = -0.5 * underlying.price_volatility**2 * step_years
            diffusion = underlying.price_volatility * math.sqrt(step_years)
            spots[symbol] *= math.exp(drift + diffusion * state.normal())

            previous = factors[symbol]
            factors[symbol] = SurfaceFactors(
                level=previous.level * (1.0 - LEVEL_REVERSION) + LEVEL_SHOCK * state.normal(),
                skew=previous.skew * (1.0 - SKEW_REVERSION)
                + SKEW_REVERSION * (-0.35)
                + SKEW_SHOCK * state.normal(),
            )
            richness[symbol] = richness[symbol] * (1.0 - RICHNESS_REVERSION) + (
                RICHNESS_SHOCK * state.normal()
            )

            spot = spots[symbol]
            for expiry in EXPIRIES:
                years = years_between(moment, expiry)
                forward = spot * math.exp(RISK_FREE_RATE * years)
                for strike in strike_ladder(underlying):
                    fair = fair_volatility(underlying, factors[symbol], strike, forward, years)
                    rich = is_rich(underlying, strike)
                    quoted = fair * (1.0 + richness_amplitude * richness[symbol]) if rich else fair
                    for option_type in ("call", "put"):
                        rows.append(
                            quoted_row(
                                QuoteRequest(underlying, expiry, option_type, strike, moment, spot, quoted),
                                sequence,
                            )
                        )
                        sequence += 1
                    if rich:
                        truth.append(
                            {
                                "observation_date": f"{day:%Y-%m-%d}",
                                "underlying_symbol": symbol,
                                "expiry_date": f"{expiry:%Y-%m-%d}",
                                "strike": strike,
                                "fair_volatility": fair,
                                "quoted_volatility": quoted,
                                "richness": quoted / fair - 1.0,
                            }
                        )
    return rows, truth


def write_signal_truth(dataset_root: Path, truth: list[dict[str, Any]], amplitude: float) -> None:
    payload = {
        "schema": SIGNAL_TRUTH_SCHEMA,
        "richness_amplitude": amplitude,
        "richness_reversion": RICHNESS_REVERSION,
        "observations": truth,
    }
    (dataset_root / SIGNAL_TRUTH_FILENAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
