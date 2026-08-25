#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

inline constexpr std::size_t minimum_curve_nodes = 1;
inline constexpr double minimum_year_fraction = 1e-12;

class InvalidRateCurveError : public std::invalid_argument {
  public:
    explicit InvalidRateCurveError(const std::string& message) : std::invalid_argument(message) {}
};

struct CurveNode {
    double years_to_maturity;
    double continuously_compounded_zero_rate;
};

struct RateCurve {
    std::vector<CurveNode> nodes;
};

void validate_rate_curve(const RateCurve& curve);
double integrated_rate_at_node(const CurveNode& node);
double terminal_forward_rate(const RateCurve& curve);
double integrated_rate(const RateCurve& curve, double years);
double discount_factor(const RateCurve& curve, double years);
double zero_rate(const RateCurve& curve, double years);
double instantaneous_forward_rate(const RateCurve& curve);
double forward_rate(const RateCurve& curve, double start_years, double end_years);
double forward_discount_factor(const RateCurve& curve, double start_years, double end_years);

}
