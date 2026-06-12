target_sources(picotool PRIVATE ${CMAKE_CURRENT_LIST_DIR}/device_main.cpp)

target_compile_definitions(picotool PRIVATE HAS_LIBUSB=0 USE_TINYUSB=1)

# lib/include provides tusb_config.h (TinyUSB) and, when mbedtls is
# available, mbedtls_config.h -> device_mbedtls_config.h.
target_include_directories(picotool PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../lib/include)

if (HAS_MBEDTLS)
    # Also inject lib/include via pico_mbedtls_headers so the path
    # propagates to bintool (which links pico_mbedtls PUBLIC).
    target_include_directories(pico_mbedtls_headers INTERFACE ${CMAKE_CURRENT_LIST_DIR}/../lib/include)
    target_link_libraries(picotool pico_mbedtls)
endif()

target_link_libraries(picotool
        pico_stdlib
        tinyusb_host
        tinyusb_board
        picoboot_connection_cxx)

pico_add_extra_outputs(picotool)
target_link_options(picotool PRIVATE -Wl,--print-memory-usage)
