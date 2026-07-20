cmake_minimum_required(VERSION 3.13)

# Standalone SDK project - configure with:
#   cmake -S . -B build -DPICO_SDK_PATH=<sdk> -DPICO_BOARD=pico|pico2
include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(enter_bootsel C CXX ASM)

pico_sdk_init()

add_executable(enter_bootsel main.c)
target_link_libraries(enter_bootsel pico_stdlib)
pico_add_extra_outputs(enter_bootsel)

# A RAM-only (no_flash) build of the same program. The harness loads this into
# SRAM over SWD (OpenOCD load_image) and runs it to drop a board into BOOTSEL
# *without touching flash* - needed to read the embedded drive of firmware
# (MicroPython / CircuitPython) that does not expose picotool's reset interface.
add_executable(enter_bootsel_ram main.c)
target_link_libraries(enter_bootsel_ram pico_stdlib)
pico_set_binary_type(enter_bootsel_ram no_flash)
pico_add_extra_outputs(enter_bootsel_ram)
