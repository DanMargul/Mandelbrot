#include "volarb/rate_curve.hpp"

#include <cmath>

namespace volarb {

void validate_rate_curve(const RateCurve& curve) {
    if (curve.nodes.size() < minimum_curve_nodes) {
        throw InvalidRateCurveError("a curve needs at least " + std::to_string(minimum_curve_nodes) +
                                    " node, got " + std::to_string(curve.nodes.size()));
    }
    if (curve.nodes.front().years_to_maturity <= 0.0) {
        throw InvalidRateCurveError("every node must sit at a positive maturity, got " +
                                    std::to_string(curve.nodes.front().years_to_maturity));
    }
    for (std::size_t index = 1; index < curve.nodes.size(); ++index) {
        if (curve.nodes[index].years_to_maturity <= curve.nodes[index - 1].years_to_maturity) {
            throw InvalidRateCurveError("nodes must be strictly increasing in years_to_maturity");
        }
    }
}

double integrated_rate_at_node(const CurveNode& node) {
    return node.continuously_compounded_zero_rate * node.years_to_maturity;
}

double terminal_forward_rate(const RateCurve& curve) {
    const CurveNode& last = curve.nodes.back();
    if (curve.nodes.size() == minimum_curve_nodes) {
        return last.continuously_compounded_zero_rate;
    }
    const CurveNode& previous = curve.nodes[curve.nodes.size() - 2];
    const double span = last.years_to_maturity - previous.years_to_maturity;
    return (integrated_rate_at_node(last) - integrated_rate_at_node(previous)) / span;
}

double integrated_rate(const RateCurve& curve, double years) {
    validate_rate_curve(curve);
    if (years < 0.0) {
        throw InvalidRateCurveError("years must not be negative, got " + std::to_string(years));
    }
    if (years == 0.0) {
        return 0.0;
    }

    const CurveNode& first = curve.nodes.front();
    if (years <= first.years_to_maturity) {
        return integrated_rate_at_node(first) * (years / first.years_to_maturity);
    }

    const CurveNode& last = curve.nodes.back();
    if (years >= last.years_to_maturity) {
        return integrated_rate_at_node(last) +
               terminal_forward_rate(curve) * (years - last.years_to_maturity);
    }

    for (std::size_t index = 1; index < curve.nodes.size(); ++index) {
        const CurveNode& earlier = curve.nodes[index - 1];
        const CurveNode& later = curve.nodes[index];
        if (earlier.years_to_maturity <= years && years <= later.years_to_maturity) {
            const double span = later.years_to_maturity - earlier.years_to_maturity;
            const double fraction = (years - earlier.years_to_maturity) / span;
            return (1.0 - fraction) * integrated_rate_at_node(earlier) +
                   fraction * integrated_rate_at_node(later);
        }
    }
    throw InvalidRateCurveError("no curve segment contains " + std::to_string(years));
}

double discount_factor(const RateCurve& curve, double years) {
    return std::exp(-integrated_rate(curve, years));
}

double instantaneous_forward_rate(const RateCurve& curve) {
    validate_rate_curve(curve);
    return curve.nodes.front().continuously_compounded_zero_rate;
}

double zero_rate(const RateCurve& curve, double years) {
    if (years <= minimum_year_fraction) {
        return instantaneous_forward_rate(curve);
    }
    return integrated_rate(curve, years) / years;
}

double forward_rate(const RateCurve& curve, double start_years, double end_years) {
    if (!(end_years > start_years)) {
        throw InvalidRateCurveError("the forward period must be positive, got " +
                                    std::to_string(start_years) + " to " + std::to_string(end_years));
    }
    const double span = end_years - start_years;
    return (integrated_rate(curve, end_years) - integrated_rate(curve, start_years)) / span;
}

double forward_discount_factor(const RateCurve& curve, double start_years, double end_years) {
    return std::exp(-forward_rate(curve, start_years, end_years) * (end_years - start_years));
}

}
