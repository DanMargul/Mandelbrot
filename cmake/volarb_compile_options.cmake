if(NOT TARGET volarb_numerical_reproducibility)
    add_library(volarb_numerical_reproducibility INTERFACE)
    target_compile_options(volarb_numerical_reproducibility INTERFACE
        -ffp-contract=off
        -fno-fast-math
    )
endif()

if(NOT TARGET volarb_warnings)
    add_library(volarb_warnings INTERFACE)
    target_compile_options(volarb_warnings INTERFACE
        -Wall
        -Wextra
        -Wpedantic
        -Wconversion
        -Wshadow
    )
endif()
