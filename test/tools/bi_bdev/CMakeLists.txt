cmake_minimum_required(VERSION 3.13)

# Standalone SDK project - configure with:
#   cmake -S . -B build -DPICO_SDK_PATH=<sdk> -DPICO_BOARD=pico|pico2
include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(bi_bdev C CXX ASM)

pico_sdk_init()

add_executable(bi_bdev main.c)
target_link_libraries(bi_bdev pico_stdlib)
pico_add_extra_outputs(bi_bdev)
