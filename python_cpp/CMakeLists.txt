cmake_minimum_required(VERSION 3.25)
project(volarb_cpp_bindings LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)
include(volarb_compile_options)

set(VOLARB_CORE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../cpp_core ${CMAKE_CURRENT_BINARY_DIR}/cpp_core)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_volarb_core bindings/module.cpp)
target_link_libraries(_volarb_core PRIVATE volarb_core volarb_warnings)

install(TARGETS _volarb_core DESTINATION volarb_cpp)
