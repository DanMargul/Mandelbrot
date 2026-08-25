#include "volarb/random_source.hpp"

#include <cmath>

namespace volarb {

UnsignedWide pcg_multiplier() {
    return (static_cast<UnsignedWide>(0x2360ED051FC65DA4ULL) << 64) |
           static_cast<UnsignedWide>(0x4385DF649FCCF645ULL);
}

PcgState advanced(const PcgState& source) {
    return PcgState{source.state * pcg_multiplier() + source.increment, source.increment};
}

std::uint64_t rotate_right(std::uint64_t value, unsigned rotation) {
    return (value >> rotation) | (value << ((0U - rotation) & 63U));
}

std::uint64_t output_of(const PcgState& source) {
    const std::uint64_t xorshifted =
        static_cast<std::uint64_t>((source.state >> 64) ^ source.state);
    return rotate_right(xorshifted, static_cast<unsigned>(source.state >> rotation_shift));
}

PcgState seeded_source(UnsignedWide initial_state, UnsignedWide sequence) {
    const UnsignedWide increment = (sequence << 1) | 1;
    PcgState source = advanced(PcgState{0, increment});
    source = PcgState{source.state + initial_state, increment};
    return advanced(source);
}

BitsDraw next_bits(const PcgState& source) {
    const PcgState stepped = advanced(source);
    return BitsDraw{stepped, output_of(stepped)};
}

UniformDraw next_uniform(const PcgState& source) {
    const BitsDraw drawn = next_bits(source);
    return UniformDraw{drawn.state,
                       static_cast<double>(drawn.bits >> mantissa_shift) * mantissa_scale};
}

UniformDraw next_positive_uniform(const PcgState& source) {
    const BitsDraw drawn = next_bits(source);
    return UniformDraw{drawn.state,
                       static_cast<double>((drawn.bits >> mantissa_shift) + 1) * mantissa_scale};
}

NormalPair next_standard_normal_pair(const PcgState& source) {
    const UniformDraw first = next_positive_uniform(source);
    const UniformDraw second = next_uniform(first.state);
    const double radius = std::sqrt(-2.0 * std::log(first.value));
    const double angle = two_pi * second.value;
    return NormalPair{second.state, radius * std::cos(angle), radius * std::sin(angle)};
}

std::vector<double> uniforms(const PcgState& source, int count) {
    if (count < 0) {
        throw InvalidRandomSourceError("count must not be negative, got " + std::to_string(count));
    }
    std::vector<double> values;
    values.reserve(static_cast<std::size_t>(count));
    PcgState current = source;
    for (int index = 0; index < count; ++index) {
        const UniformDraw drawn = next_uniform(current);
        current = drawn.state;
        values.push_back(drawn.value);
    }
    return values;
}

std::vector<double> standard_normals(const PcgState& source, int count) {
    if (count < 0) {
        throw InvalidRandomSourceError("count must not be negative, got " + std::to_string(count));
    }
    std::vector<double> values;
    values.reserve(static_cast<std::size_t>(count));
    PcgState current = source;
    while (static_cast<int>(values.size()) < count) {
        const NormalPair pair = next_standard_normal_pair(current);
        current = pair.state;
        values.push_back(pair.first);
        if (static_cast<int>(values.size()) < count) {
            values.push_back(pair.second);
        }
    }
    return values;
}

}
