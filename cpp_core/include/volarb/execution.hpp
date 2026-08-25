#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

enum class OrderSide { Buy, Sell };
enum class FillStatus { Filled, PartiallyFilled, Unfilled };

inline constexpr double minimum_net_vega = 1e-12;
inline constexpr double round_trip_crossings = 2.0;

class InvalidQuoteError : public std::invalid_argument {
  public:
    explicit InvalidQuoteError(const std::string& message) : std::invalid_argument(message) {}
};

class InvalidOrderError : public std::invalid_argument {
  public:
    explicit InvalidOrderError(const std::string& message) : std::invalid_argument(message) {}
};

struct Quote {
    double bid_price;
    double ask_price;
    long long bid_size;
    long long ask_size;
};

struct PackageLeg {
    Quote quote;
    OrderSide side;
    long long quantity;
    int contract_multiplier;
    double vega_with_respect_to_volatility;
};

struct LegFill {
    long long requested_quantity;
    long long filled_quantity;
    double touch_price;
    double mid_price;
    double half_spread;
    double cost_against_mid;
    FillStatus status;
};

struct PackageFill {
    std::vector<LegFill> leg_fills;
    long long requested_quantity;
    long long filled_quantity;
    double total_cost_against_mid;
    double net_vega;
    bool net_vega_is_negligible;
    double round_trip_cost_in_volatility_points;
    FillStatus status;
};

OrderSide order_side_from_name(const std::string& name);
std::string name_of_order_side(OrderSide side);
std::string name_of_fill_status(FillStatus status);

void validate_quote(const Quote& quote);
double mid_price(const Quote& quote);
double half_spread(const Quote& quote);
double touch_price(const Quote& quote, OrderSide side);
long long available_size(const Quote& quote, OrderSide side);

LegFill fill_at_touch(const Quote& quote, OrderSide side, long long quantity, int contract_multiplier);
PackageFill fill_package(const std::vector<PackageLeg>& legs);

}
