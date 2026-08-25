#include "volarb/execution.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <vector>

using Catch::Approx;
using volarb::available_size;
using volarb::fill_at_touch;
using volarb::fill_package;
using volarb::FillStatus;
using volarb::half_spread;
using volarb::InvalidOrderError;
using volarb::InvalidQuoteError;
using volarb::LegFill;
using volarb::mid_price;
using volarb::name_of_fill_status;
using volarb::name_of_order_side;
using volarb::order_side_from_name;
using volarb::OrderSide;
using volarb::PackageFill;
using volarb::PackageLeg;
using volarb::Quote;
using volarb::touch_price;

namespace {

const Quote liquid{10.00, 10.20, 50, 40};
const Quote wide{1.00, 1.40, 10, 10};

}

TEST_CASE("a taker pays the touch and never the mid", "[execution]") {
    const LegFill bought = fill_at_touch(liquid, OrderSide::Buy, 10, 100);
    REQUIRE(bought.touch_price == Approx(10.20));
    REQUIRE(bought.mid_price == Approx(10.10));
    REQUIRE(bought.cost_against_mid == Approx(10 * 100 * 0.10));
    REQUIRE(bought.status == FillStatus::Filled);

    const LegFill sold = fill_at_touch(liquid, OrderSide::Sell, 10, 100);
    REQUIRE(sold.touch_price == Approx(10.00));
    REQUIRE(sold.cost_against_mid == Approx(bought.cost_against_mid));
}

TEST_CASE("size beyond the touch is not filled rather than filled worse", "[execution]") {
    const LegFill fill = fill_at_touch(liquid, OrderSide::Buy, 100, 100);
    REQUIRE(fill.filled_quantity == 40);
    REQUIRE(fill.requested_quantity == 100);
    REQUIRE(fill.status == FillStatus::PartiallyFilled);
    REQUIRE(fill.cost_against_mid == Approx(40 * 100 * 0.10));
}

TEST_CASE("an empty book fills nothing", "[execution]") {
    const Quote empty{10.00, 10.20, 0, 0};
    const LegFill fill = fill_at_touch(empty, OrderSide::Buy, 5, 100);
    REQUIRE(fill.filled_quantity == 0);
    REQUIRE(fill.status == FillStatus::Unfilled);
    REQUIRE(fill.cost_against_mid == Approx(0.0));
}

TEST_CASE("a package pays the full spread on every leg", "[execution]") {
    const std::vector<PackageLeg> legs = {
        PackageLeg{liquid, OrderSide::Buy, 10, 100, 0.20},
        PackageLeg{wide, OrderSide::Sell, 10, 100, 0.05},
    };
    const PackageFill fill = fill_package(legs);
    REQUIRE(fill.status == FillStatus::Filled);
    REQUIRE(fill.total_cost_against_mid ==
            Approx(10 * 100 * half_spread(liquid) + 10 * 100 * half_spread(wide)));
    REQUIRE(fill.net_vega == Approx(10 * 100 * 0.20 - 10 * 100 * 0.05));
    REQUIRE_FALSE(fill.net_vega_is_negligible);
    REQUIRE(fill.round_trip_cost_in_volatility_points ==
            Approx(2.0 * fill.total_cost_against_mid / fill.net_vega));
}

TEST_CASE("a vega neutral package pays spread for no exposure", "[execution]") {
    const std::vector<PackageLeg> legs = {
        PackageLeg{liquid, OrderSide::Buy, 10, 100, 0.20},
        PackageLeg{liquid, OrderSide::Sell, 10, 100, 0.20},
    };
    const PackageFill fill = fill_package(legs);
    REQUIRE(fill.total_cost_against_mid > 0.0);
    REQUIRE(fill.net_vega == Approx(0.0));
    REQUIRE(fill.net_vega_is_negligible);
    REQUIRE(fill.round_trip_cost_in_volatility_points > 0.0);
}

TEST_CASE("a partly filled package reports the vega it actually got", "[execution]") {
    const Quote thin_book{10.00, 10.20, 50, 3};
    const std::vector<PackageLeg> legs = {PackageLeg{thin_book, OrderSide::Buy, 10, 100, 0.20}};
    const PackageFill fill = fill_package(legs);
    REQUIRE(fill.status == FillStatus::PartiallyFilled);
    REQUIRE(fill.filled_quantity == 3);
    REQUIRE(fill.net_vega == Approx(3 * 100 * 0.20));
}

TEST_CASE("a crossed book is rejected rather than traded", "[execution]") {
    const Quote crossed{10.30, 10.20, 10, 10};
    REQUIRE_THROWS_AS(fill_at_touch(crossed, OrderSide::Buy, 1, 100), InvalidQuoteError);
}

TEST_CASE("negative prices sizes quantities and multipliers are rejected", "[execution]") {
    REQUIRE_THROWS_AS(fill_at_touch(Quote{-1.0, 1.0, 1, 1}, OrderSide::Buy, 1, 100), InvalidQuoteError);
    REQUIRE_THROWS_AS(fill_at_touch(Quote{1.0, 2.0, -1, 1}, OrderSide::Buy, 1, 100), InvalidQuoteError);
    REQUIRE_THROWS_AS(fill_at_touch(liquid, OrderSide::Buy, 0, 100), InvalidOrderError);
    REQUIRE_THROWS_AS(fill_at_touch(liquid, OrderSide::Buy, 1, 0), InvalidOrderError);
    REQUIRE_THROWS_AS(fill_package({}), InvalidOrderError);
}

TEST_CASE("a locked book costs nothing to cross", "[execution]") {
    const Quote locked{10.10, 10.10, 5, 5};
    const LegFill fill = fill_at_touch(locked, OrderSide::Buy, 5, 100);
    REQUIRE(half_spread(locked) == Approx(0.0));
    REQUIRE(fill.cost_against_mid == Approx(0.0));
    REQUIRE(fill.touch_price == Approx(mid_price(locked)));
}

TEST_CASE("sides and statuses have names that round trip", "[execution]") {
    REQUIRE(order_side_from_name("buy") == OrderSide::Buy);
    REQUIRE(order_side_from_name("sell") == OrderSide::Sell);
    REQUIRE(name_of_order_side(OrderSide::Buy) == "buy");
    REQUIRE(name_of_order_side(OrderSide::Sell) == "sell");
    REQUIRE(name_of_fill_status(FillStatus::Filled) == "filled");
    REQUIRE(name_of_fill_status(FillStatus::PartiallyFilled) == "partially_filled");
    REQUIRE(name_of_fill_status(FillStatus::Unfilled) == "unfilled");
    REQUIRE_THROWS_AS(order_side_from_name("hold"), InvalidOrderError);
    REQUIRE(touch_price(liquid, OrderSide::Buy) == Approx(liquid.ask_price));
    REQUIRE(available_size(liquid, OrderSide::Sell) == liquid.bid_size);
}
