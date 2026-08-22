cmake_minimum_required(VERSION 3.25)
project(mandelbrot LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(volarb_numerical_reproducibility INTERFACE)
target_compile_options(volarb_numerical_reproducibility INTERFACE
    -ffp-contract=off
    -fno-fast-math
)

add_library(volarb_warnings INTERFACE)
target_compile_options(volarb_warnings INTERFACE
    -Wall
    -Wextra
    -Wpedantic
    -Wconversion
    -Wshadow
)

enable_testing()

add_subdirectory(cpp_core)
add_subdirectory(cpp_pure)

option(VOLARB_BUILD_PYTHON_BINDINGS "Build the pybind11 module for the python_cpp track" OFF)
if(VOLARB_BUILD_PYTHON_BINDINGS)
    add_subdirectory(python_cpp/bindings)
endif()
