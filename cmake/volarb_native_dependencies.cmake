if(APPLE AND NOT VOLARB_HOMEBREW_PREFIX_RESOLVED)
    if(DEFINED ENV{HOMEBREW_PREFIX})
        set(volarb_homebrew_prefix $ENV{HOMEBREW_PREFIX})
    else()
        find_program(VOLARB_BREW_EXECUTABLE brew)
        if(VOLARB_BREW_EXECUTABLE)
            execute_process(
                COMMAND ${VOLARB_BREW_EXECUTABLE} --prefix
                OUTPUT_VARIABLE volarb_homebrew_prefix
                OUTPUT_STRIP_TRAILING_WHITESPACE
            )
        endif()
    endif()
    if(volarb_homebrew_prefix)
        list(APPEND CMAKE_PREFIX_PATH ${volarb_homebrew_prefix})
        set(CMAKE_PREFIX_PATH ${CMAKE_PREFIX_PATH} PARENT_SCOPE)
        message(STATUS "volarb: native dependencies from ${volarb_homebrew_prefix}")
    endif()
    set(VOLARB_HOMEBREW_PREFIX_RESOLVED ON PARENT_SCOPE)
endif()
