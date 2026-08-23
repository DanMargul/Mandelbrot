from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "python_pure" / "src"))

from volarb_py.pricing import BlackScholesInputs, OptionType, black_scholes_price  # noqa: E402

SYNTHETIC_SOURCE: Final[str] = "synthetic"
QUOTE_MINIMUM_SPREAD: Final[float] = 0.05
QUOTE_PROPORTIONAL_SPREAD: Final[float] = 0.02
DAYS_PER_YEAR: Final[float] = 365.0

BASE_VOLATILITY: Final[float] = 0.18
VOLATILITY_SKEW: Final[float] = -0.35
VOLATILITY_CURVATURE: Final[float] = 0.55
TERM_VOLATILITY_SLOPE: Final[float] = 0.03


@dataclass(frozen=True)
class SyntheticContract:
    underlying_symbol: str
    expiry_date: date
    strike: float
    option_type: OptionType
    contract_multiplier: int
    is_standard_deliverable: bool
    listed_from: datetime


@dataclass(frozen=True)
class SyntheticUnderlying:
    symbol: str
    reference_price: float
    expiries: tuple[date, ...]
    strike_offsets: tuple[float, ...]


OBSERVATION_TIMES: Final[tuple[datetime, ...]] = (
    datetime(2026, 8, 21, 15, 0, 0, tzinfo=UTC),
    datetime(2026, 8, 21, 16, 0, 0, tzinfo=UTC),
    datetime(2026, 8, 21, 17, 0, 0, tzinfo=UTC),
)

CORRECTION_KNOWLEDGE_TIME: Final[datetime] = datetime(2026, 8, 21, 18, 0, 0, tzinfo=UTC)
SETTLEMENT_KNOWLEDGE_TIME: Final[datetime] = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
LATE_LISTING_TIME: Final[datetime] = datetime(2026, 8, 21, 16, 30, 0, tzinfo=UTC)

UNDERLYINGS: Final[tuple[SyntheticUnderlying, ...]] = (
    SyntheticUnderlying(
        symbol="SPX",
        reference_price=4800.0,
        expiries=(date(2026, 9, 18), date(2026, 12, 18)),
        strike_offsets=(-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
    ),
    SyntheticUnderlying(
        symbol="AAPL",
        reference_price=225.0,
        expiries=(date(2026, 9, 18),),
        strike_offsets=(-0.05, 0.0, 0.05),
    ),
)


def occ_contract_symbol(underlying: str, expiry: date, option_type: OptionType, strike: float) -> str:
    thousandths = round(strike * 1000)
    letter = "C" if option_type == "call" else "P"
    return f"{underlying}{expiry:%y%m%d}{letter}{thousandths:08d}"


def synthetic_volatility(strike: float, forward: float, years_to_expiry: float) -> float:
    log_moneyness = math.log(strike / forward)
    smile = (
        BASE_VOLATILITY
        + VOLATILITY_SKEW * log_moneyness
        + VOLATILITY_CURVATURE * log_moneyness * log_moneyness
        + TERM_VOLATILITY_SLOPE * math.sqrt(years_to_expiry)
    )
    return max(smile, 0.02)


def years_between(moment: datetime, expiry: date) -> float:
    expiry_moment = datetime(expiry.year, expiry.month, expiry.day, 21, 0, 0, tzinfo=UTC)
    return max((expiry_moment - moment).total_seconds() / (DAYS_PER_YEAR * 86400.0), 1.0 / DAYS_PER_YEAR)


def underlying_price_at(underlying: SyntheticUnderlying, observation_time: datetime) -> float:
    minutes_elapsed = (observation_time - OBSERVATION_TIMES[0]).total_seconds() / 60.0
    return underlying.reference_price * (1.0 + 0.0004 * math.sin(minutes_elapsed / 37.0))


def contracts_for(underlying: SyntheticUnderlying) -> list[SyntheticContract]:
    contracts: list[SyntheticContract] = []
    for expiry in underlying.expiries:
        for offset in underlying.strike_offsets:
            strike = round(underlying.reference_price * (1.0 + offset), 2)
            option_types: tuple[OptionType, ...] = ("call", "put")
            for option_type in option_types:
                contracts.append(
                    SyntheticContract(
                        underlying_symbol=underlying.symbol,
                        expiry_date=expiry,
                        strike=strike,
                        option_type=option_type,
                        contract_multiplier=100,
                        is_standard_deliverable=True,
                        listed_from=OBSERVATION_TIMES[0],
                    )
                )
    contracts.append(
        SyntheticContract(
            underlying_symbol=underlying.symbol,
            expiry_date=underlying.expiries[0],
            strike=round(underlying.reference_price * 1.25, 2),
            option_type="call",
            contract_multiplier=125,
            is_standard_deliverable=False,
            listed_from=OBSERVATION_TIMES[0],
        )
    )
    contracts.append(
        SyntheticContract(
            underlying_symbol=underlying.symbol,
            expiry_date=underlying.expiries[0],
            strike=round(underlying.reference_price * 1.15, 2),
            option_type="call",
            contract_multiplier=100,
            is_standard_deliverable=True,
            listed_from=LATE_LISTING_TIME,
        )
    )
    return contracts


@dataclass(frozen=True)
class QuoteRevision:
    observation_time: datetime
    knowledge_time: datetime
    ingest_sequence: int
    underlying_price: float
    price_multiplier: float
    open_interest: int | None


def quote_row(contract: SyntheticContract, revision: QuoteRevision) -> dict[str, Any]:
    observation_time = revision.observation_time
    underlying_price = revision.underlying_price
    years = years_between(observation_time, contract.expiry_date)
    volatility = synthetic_volatility(contract.strike, underlying_price, years)
    fair_value = (
        black_scholes_price(
            BlackScholesInputs(
                forward=underlying_price,
                strike=contract.strike,
                years_to_expiry=years,
                volatility=volatility,
                discount_factor=1.0,
                option_type=contract.option_type,
            )
        )
        * revision.price_multiplier
    )
    half_spread = 0.5 * max(QUOTE_MINIMUM_SPREAD, QUOTE_PROPORTIONAL_SPREAD * fair_value)
    return {
        "underlying_symbol": contract.underlying_symbol,
        "contract_symbol": occ_contract_symbol(
            contract.underlying_symbol, contract.expiry_date, contract.option_type, contract.strike
        ),
        "expiry_date": contract.expiry_date,
        "strike": contract.strike,
        "option_type": contract.option_type,
        "contract_multiplier": contract.contract_multiplier,
        "is_standard_deliverable": contract.is_standard_deliverable,
        "event_time": observation_time,
        "knowledge_time": revision.knowledge_time,
        "ingest_sequence": revision.ingest_sequence,
        "underlying_price": underlying_price,
        "bid_price": round(max(fair_value - half_spread, 0.0), 4),
        "ask_price": round(fair_value + half_spread, 4),
        "bid_size": 25,
        "ask_size": 40,
        "last_trade_price": round(fair_value, 4),
        "volume": 100,
        "open_interest": revision.open_interest,
        "source": SYNTHETIC_SOURCE,
    }


def corrected_contract_symbol(underlying: SyntheticUnderlying) -> str:
    return occ_contract_symbol(
        underlying.symbol,
        underlying.expiries[0],
        "call",
        round(underlying.reference_price, 2),
    )


def synthetic_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = 0
    for underlying in UNDERLYINGS:
        correction_target = corrected_contract_symbol(underlying)
        for contract in contracts_for(underlying):
            symbol = occ_contract_symbol(
                contract.underlying_symbol, contract.expiry_date, contract.option_type, contract.strike
            )
            for observation_time in OBSERVATION_TIMES:
                if observation_time < contract.listed_from:
                    continue
                price = underlying_price_at(underlying, observation_time)
                rows.append(
                    quote_row(
                        contract,
                        QuoteRevision(observation_time, observation_time, sequence, price, 1.0, None),
                    )
                )
                sequence += 1

                is_correction_point = symbol == correction_target and observation_time == OBSERVATION_TIMES[1]
                if is_correction_point:
                    rows.append(
                        quote_row(
                            contract,
                            QuoteRevision(
                                observation_time, CORRECTION_KNOWLEDGE_TIME, sequence, price, 1.05, None
                            ),
                        )
                    )
                    sequence += 1

                if observation_time == OBSERVATION_TIMES[-1]:
                    rows.append(
                        quote_row(
                            contract,
                            QuoteRevision(
                                observation_time, SETTLEMENT_KNOWLEDGE_TIME, sequence, price, 1.0, 4321
                            ),
                        )
                    )
                    sequence += 1
    return rows
