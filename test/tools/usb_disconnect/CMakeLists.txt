cmake_minimum_required(VERSION 3.13)

# Standalone SDK project - configure with:
#   cmake -S . -B build -DPICO_SDK_PATH=<sdk> -DPICO_BOARD=pico|pico2
include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(usb_disconnect C CXX ASM)

pico_sdk_init()

# RAM-only (no_flash): the harness loads this into SRAM over SWD and runs it to
# drop the board off USB without touching flash (see lib/devices.py
# usb_disconnected).
add_executable(usb_disconnect main.c)
target_link_libraries(usb_disconnect pico_stdlib hardware_resets)
pico_set_binary_type(usb_disconnect no_flash)
pico_add_extra_outputs(usb_disconnect)
