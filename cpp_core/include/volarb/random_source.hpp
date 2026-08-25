#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace volarb {

using UnsignedWide = __uint128_t;

inline constexpr int rotation_shift = 122;
inline constexpr int mantissa_shift = 11;
inline constexpr double mantissa_scale = 1.0 / 9007199254740992.0;
inline constexpr double two_pi = 6.283185307179586;

class InvalidRandomSourceError : public std::invalid_argument {
  public:
    explicit InvalidRandomSourceError(const std::string& message) : std::invalid_argument(message) {}
};

struct PcgState {
    UnsignedWide state;
    UnsignedWide increment;
};

struct BitsDraw {
    PcgState state;
    std::uint64_t bits;
};

struct UniformDraw {
    PcgState state;
    double value;
};

struct NormalPair {
    PcgState state;
    double first;
    double second;
};

UnsignedWide pcg_multiplier();
PcgState advanced(const PcgState& source);
std::uint64_t rotate_right(std::uint64_t value, unsigned rotation);
std::uint64_t output_of(const PcgState& source);
PcgState seeded_source(UnsignedWide initial_state, UnsignedWide sequence);

BitsDraw next_bits(const PcgState& source);
UniformDraw next_uniform(const PcgState& source);
UniformDraw next_positive_uniform(const PcgState& source);
NormalPair next_standard_normal_pair(const PcgState& source);

std::vector<double> uniforms(const PcgState& source, int count);
std::vector<double> standard_normals(const PcgState& source, int count);

}
