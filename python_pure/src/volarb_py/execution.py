from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

OrderSide = Literal["buy", "sell"]
FillStatus = Literal["filled", "partially_filled", "unfilled"]

MINIMUM_NET_VEGA: Final[float] = 1e-12
ROUND_TRIP_CROSSINGS: Final[float] = 2.0


class InvalidQuoteError(ValueError):
    pass


class InvalidOrderError(ValueError):
    pass


@dataclass(frozen=True)
class Quote:
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int


@dataclass(frozen=True)
class PackageLeg:
    quote: Quote
    side: OrderSide
    quantity: int
    contract_multiplier: int
    vega_with_respect_to_volatility: float


@dataclass(frozen=True)
class LegFill:
    requested_quantity: int
    filled_quantity: int
    touch_price: float
    mid_price: float
    half_spread: float
    cost_against_mid: float
    status: FillStatus


@dataclass(frozen=True)
class PackageFill:
    leg_fills: list[LegFill]
    requested_quantity: int
    filled_quantity: int
    total_cost_against_mid: float
    net_vega: float
    net_vega_is_negligible: bool
    round_trip_cost_in_volatility_points: float
    status: FillStatus


def validate_quote(quote: Quote) -> None:
    if quote.bid_price < 0.0:
        raise InvalidQuoteError(f"bid_price must not be negative, got {quote.bid_price}")
    if quote.ask_price < 0.0:
        raise InvalidQuoteError(f"ask_price must not be negative, got {quote.ask_price}")
    if quote.ask_price < quote.bid_price:
        raise InvalidQuoteError(
            f"a crossed book is not a tradeable quote: bid {quote.bid_price} above ask {quote.ask_price}"
        )
    if quote.bid_size < 0 or quote.ask_size < 0:
        raise InvalidQuoteError(
            f"quoted sizes must not be negative, got {quote.bid_size} and {quote.ask_size}"
        )


def mid_price(quote: Quote) -> float:
    return 0.5 * (quote.bid_price + quote.ask_price)


def half_spread(quote: Quote) -> float:
    return 0.5 * (quote.ask_price - quote.bid_price)


def touch_price(quote: Quote, side: OrderSide) -> float:
    return quote.ask_price if side == "buy" else quote.bid_price


def available_size(quote: Quote, side: OrderSide) -> int:
    return quote.ask_size if side == "buy" else quote.bid_size


def signed_direction(side: OrderSide) -> float:
    return 1.0 if side == "buy" else -1.0


def status_for(requested: int, filled: int) -> FillStatus:
    if filled == 0:
        return "unfilled"
    if filled < requested:
        return "partially_filled"
    return "filled"


def fill_at_touch(quote: Quote, side: OrderSide, quantity: int, contract_multiplier: int) -> LegFill:
    validate_quote(quote)
    if quantity <= 0:
        raise InvalidOrderError(f"quantity must be positive, got {quantity}")
    if contract_multiplier <= 0:
        raise InvalidOrderError(f"contract_multiplier must be positive, got {contract_multiplier}")

    filled = min(quantity, available_size(quote, side))
    spread = half_spread(quote)
    return LegFill(
        requested_quantity=quantity,
        filled_quantity=filled,
        touch_price=touch_price(quote, side),
        mid_price=mid_price(quote),
        half_spread=spread,
        cost_against_mid=filled * contract_multiplier * spread,
        status=status_for(quantity, filled),
    )


def fill_package(legs: list[PackageLeg]) -> PackageFill:
    if not legs:
        raise InvalidOrderError("a package needs at least one leg")

    fills = [fill_at_touch(leg.quote, leg.side, leg.quantity, leg.contract_multiplier) for leg in legs]
    requested = sum(leg.quantity for leg in legs)
    filled = sum(fill.filled_quantity for fill in fills)
    cost = sum(fill.cost_against_mid for fill in fills)
    net_vega = sum(
        signed_direction(leg.side)
        * fill.filled_quantity
        * leg.contract_multiplier
        * leg.vega_with_respect_to_volatility
        for leg, fill in zip(legs, fills, strict=True)
    )

    magnitude = abs(net_vega)
    negligible = magnitude < MINIMUM_NET_VEGA
    return PackageFill(
        leg_fills=fills,
        requested_quantity=requested,
        filled_quantity=filled,
        total_cost_against_mid=cost,
        net_vega=net_vega,
        net_vega_is_negligible=negligible,
        round_trip_cost_in_volatility_points=ROUND_TRIP_CROSSINGS * cost / max(magnitude, MINIMUM_NET_VEGA),
        status=status_for(requested, filled),
    )
