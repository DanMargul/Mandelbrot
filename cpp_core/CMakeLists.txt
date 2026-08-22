list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)
include(volarb_compile_options)

add_library(volarb_core STATIC
    src/pricing.cpp
    src/implied_vol.cpp
)

target_include_directories(volarb_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(volarb_core PUBLIC volarb_numerical_reproducibility PRIVATE volarb_warnings)
set_target_properties(volarb_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

option(VOLARB_CORE_BUILD_TESTS "Build the Catch2 test suite for volarb_core" ON)

if(VOLARB_CORE_BUILD_TESTS)
    find_package(Catch2 3 REQUIRED)

    add_executable(volarb_core_tests
        tests/test_pricing.cpp
        tests/test_implied_vol.cpp
    )
    target_link_libraries(volarb_core_tests PRIVATE volarb_core volarb_warnings Catch2::Catch2WithMain)

    include(Catch)
    catch_discover_tests(volarb_core_tests)
endif()
