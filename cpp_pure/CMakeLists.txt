find_package(nlohmann_json CONFIG REQUIRED)

add_library(volarb_native_cli STATIC
    src/documents.cpp
    src/verbs.cpp
)
target_include_directories(volarb_native_cli PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(volarb_native_cli
    PUBLIC volarb_core nlohmann_json::nlohmann_json
    PRIVATE volarb_warnings
)

add_executable(volarb-native src/main.cpp)
target_link_libraries(volarb-native PRIVATE volarb_native_cli volarb_warnings)

find_package(Catch2 3 REQUIRED)

add_executable(volarb_native_cli_tests tests/test_verbs.cpp)
target_link_libraries(volarb_native_cli_tests PRIVATE volarb_native_cli volarb_warnings Catch2::Catch2WithMain)
target_compile_definitions(volarb_native_cli_tests PRIVATE
    VOLARB_FIXTURE_ROOT="${CMAKE_SOURCE_DIR}/spec/fixtures"
)

include(Catch)
catch_discover_tests(volarb_native_cli_tests)
