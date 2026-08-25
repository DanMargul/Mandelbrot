#include "volarb/execution.hpp"

#include <algorithm>
#include <cmath>

namespace volarb {

namespace {

double signed_direction(OrderSide side) {
    return side == OrderSide::Buy ? 1.0 : -1.0;
}

FillStatus status_for(long long requested, long long filled) {
    if (filled == 0) {
        return FillStatus::Unfilled;
    }
    if (filled < requested) {
        return FillStatus::PartiallyFilled;
    }
    return FillStatus::Filled;
}

}

OrderSide order_side_from_name(const std::string& name) {
    if (name == "buy") {
        return OrderSide::Buy;
    }
    if (name == "sell") {
        return OrderSide::Sell;
    }
    throw InvalidOrderError("side must be 'buy' or 'sell', got " + name);
}

std::string name_of_order_side(OrderSide side) {
    return side == OrderSide::Buy ? "buy" : "sell";
}

std::string name_of_fill_status(FillStatus status) {
    switch (status) {
    case FillStatus::Filled:
        return "filled";
    case FillStatus::PartiallyFilled:
        return "partially_filled";
    case FillStatus::Unfilled:
        return "unfilled";
    }
    return "unfilled";
}

void validate_quote(const Quote& quote) {
    if (quote.bid_price < 0.0) {
        throw InvalidQuoteError("bid_price must not be negative, got " + std::to_string(quote.bid_price));
    }
    if (quote.ask_price < 0.0) {
        throw InvalidQuoteError("ask_price must not be negative, got " + std::to_string(quote.ask_price));
    }
    if (quote.ask_price < quote.bid_price) {
        throw InvalidQuoteError("a crossed book is not a tradeable quote: bid " +
                                std::to_string(quote.bid_price) + " above ask " +
                                std::to_string(quote.ask_price));
    }
    if (quote.bid_size < 0 || quote.ask_size < 0) {
        throw InvalidQuoteError("quoted sizes must not be negative, got " +
                                std::to_string(quote.bid_size) + " and " + std::to_string(quote.ask_size));
    }
}

double mid_price(const Quote& quote) {
    return 0.5 * (quote.bid_price + quote.ask_price);
}

double half_spread(const Quote& quote) {
    return 0.5 * (quote.ask_price - quote.bid_price);
}

double touch_price(const Quote& quote, OrderSide side) {
    return side == OrderSide::Buy ? quote.ask_price : quote.bid_price;
}

long long available_size(const Quote& quote, OrderSide side) {
    return side == OrderSide::Buy ? quote.ask_size : quote.bid_size;
}

LegFill fill_at_touch(const Quote& quote, OrderSide side, long long quantity, int contract_multiplier) {
    validate_quote(quote);
    if (quantity <= 0) {
        throw InvalidOrderError("quantity must be positive, got " + std::to_string(quantity));
    }
    if (contract_multiplier <= 0) {
        throw InvalidOrderError("contract_multiplier must be positive, got " +
                                std::to_string(contract_multiplier));
    }

    const long long filled = std::min(quantity, available_size(quote, side));
    const double spread = half_spread(quote);
    return LegFill{
        quantity,
        filled,
        touch_price(quote, side),
        mid_price(quote),
        spread,
        static_cast<double>(filled) * static_cast<double>(contract_multiplier) * spread,
        status_for(quantity, filled),
    };
}

PackageFill fill_package(const std::vector<PackageLeg>& legs) {
    if (legs.empty()) {
        throw InvalidOrderError("a package needs at least one leg");
    }

    std::vector<LegFill> fills;
    fills.reserve(legs.size());
    for (const PackageLeg& leg : legs) {
        fills.push_back(fill_at_touch(leg.quote, leg.side, leg.quantity, leg.contract_multiplier));
    }

    long long requested = 0;
    long long filled = 0;
    double cost = 0.0;
    double net_vega = 0.0;
    for (std::size_t index = 0; index < legs.size(); ++index) {
        requested += legs[index].quantity;
        filled += fills[index].filled_quantity;
        cost += fills[index].cost_against_mid;
        net_vega += signed_direction(legs[index].side) *
                    static_cast<double>(fills[index].filled_quantity) *
                    static_cast<double>(legs[index].contract_multiplier) *
                    legs[index].vega_with_respect_to_volatility;
    }

    const double magnitude = std::abs(net_vega);
    return PackageFill{
        fills,
        requested,
        filled,
        cost,
        net_vega,
        magnitude < minimum_net_vega,
        round_trip_crossings * cost / std::max(magnitude, minimum_net_vega),
        status_for(requested, filled),
    };
}

}
