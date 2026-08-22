cmake_minimum_required(VERSION 3.25)
project(mandelbrot LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake)
include(volarb_compile_options)

enable_testing()

add_subdirectory(cpp_core)
add_subdirectory(cpp_pure)
