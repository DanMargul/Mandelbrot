#include "volarb/random_source.hpp"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <cmath>
#include <set>
#include <vector>

using Catch::Approx;
using volarb::advanced;
using volarb::InvalidRandomSourceError;
using volarb::next_bits;
using volarb::next_uniform;
using volarb::PcgState;
using volarb::rotate_right;
using volarb::seeded_source;
using volarb::standard_normals;
using volarb::uniforms;

namespace {

const int sample_size = 200000;

}

TEST_CASE("the seeded stream matches the reference implementation", "[random_source]") {
    const PcgState source = seeded_source(42, 54);
    const std::vector<std::uint64_t> expected = {
        9705778491962043240ULL, 1370407407632858425ULL, 11774395822783136600ULL,
        17944889938176486912ULL, 14437308781460811564ULL, 6944869453235589526ULL,
    };
    PcgState current = source;
    for (const std::uint64_t want : expected) {
        const auto drawn = next_bits(current);
        current = drawn.state;
        REQUIRE(drawn.bits == want);
    }
}

TEST_CASE("rotation wraps rather than discarding bits", "[random_source]") {
    REQUIRE(rotate_right(1ULL, 0) == 1ULL);
    REQUIRE(rotate_right(1ULL, 1) == (1ULL << 63));
    REQUIRE(rotate_right(0xFFFFFFFFFFFFFFFFULL, 37) == 0xFFFFFFFFFFFFFFFFULL);
}

TEST_CASE("uniforms land in the half open unit interval", "[random_source]") {
    const std::vector<double> values = uniforms(seeded_source(1, 1), sample_size);
    double total = 0.0;
    double lowest = 1.0;
    double highest = 0.0;
    for (const double value : values) {
        REQUIRE(value >= 0.0);
        REQUIRE(value < 1.0);
        total += value;
        lowest = std::min(lowest, value);
        highest = std::max(highest, value);
    }
    REQUIRE(total / static_cast<double>(values.size()) == Approx(0.5).margin(0.005));
    REQUIRE(lowest < 0.001);
    REQUIRE(highest > 0.999);
}

TEST_CASE("standard normals have the moments they claim", "[random_source]") {
    const std::vector<double> values = standard_normals(seeded_source(7, 3), sample_size);
    double total = 0.0;
    for (const double value : values) {
        total += value;
    }
    const double mean = total / static_cast<double>(values.size());
    double squared = 0.0;
    for (const double value : values) {
        squared += (value - mean) * (value - mean);
    }
    const double variance = squared / static_cast<double>(values.size() - 1);
    REQUIRE(mean == Approx(0.0).margin(0.01));
    REQUIRE(variance == Approx(1.0).margin(0.02));
}

TEST_CASE("different sequences are different streams", "[random_source]") {
    const std::vector<double> one = uniforms(seeded_source(1, 1), 64);
    const std::vector<double> other = uniforms(seeded_source(1, 2), 64);
    REQUIRE(one != other);

    const std::vector<double> repeated = uniforms(seeded_source(1, 1), 64);
    REQUIRE(one == repeated);
}

TEST_CASE("the state advances deterministically", "[random_source]") {
    const PcgState source = seeded_source(11, 13);
    const PcgState once = advanced(source);
    REQUIRE(advanced(source).state == once.state);
    REQUIRE(once.increment == source.increment);
    REQUIRE(next_uniform(source).value == next_uniform(source).value);
}

TEST_CASE("a negative count is rejected", "[random_source]") {
    REQUIRE_THROWS_AS(uniforms(seeded_source(1, 1), -1), InvalidRandomSourceError);
    REQUIRE_THROWS_AS(standard_normals(seeded_source(1, 1), -1), InvalidRandomSourceError);
    REQUIRE(uniforms(seeded_source(1, 1), 0).empty());
}

TEST_CASE("an odd normal count still consumes whole pairs", "[random_source]") {
    const std::vector<double> three = standard_normals(seeded_source(5, 5), 3);
    const std::vector<double> four = standard_normals(seeded_source(5, 5), 4);
    REQUIRE(three.size() == 3);
    REQUIRE(four.size() == 4);
    for (std::size_t index = 0; index < three.size(); ++index) {
        REQUIRE(three[index] == four[index]);
    }
}
