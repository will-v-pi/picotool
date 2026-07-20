/**
 * bi_bdev - a minimal firmware that declares an embedded block device via
 * *binary info* (rather than via a partition table).
 *
 * This is the other way picotool can locate a block device: the firmware embeds
 * a BINARY_INFO_TYPE_BLOCK_DEVICE entry (SDK `bi_block_device` macro) describing
 * where the block device lives in flash, and `picotool bdev` reads it straight
 * out of the image - no partition table required. It's the same mechanism
 * MicroPython / CircuitPython use to expose their filesystems.
 *
 * The device is placed 1 MiB into flash and is 256 KiB long, which is safe on
 * both the 2 MiB RP2040 and 4 MiB RP2350 parts - this program lives at the
 * start of flash and is tiny, so it never reaches the reserved region.
 */
#include "pico/stdlib.h"
#include "pico/binary_info.h"
#include "hardware/address_mapped.h"  // XIP_BASE

#define BDEV_OFFSET (1u * 1024 * 1024)  // 1 MiB into flash
#define BDEV_SIZE   (256u * 1024)       // 256 KiB

bi_decl(bi_block_device(
    BINARY_INFO_TAG_RASPBERRY_PI,
    "testfs",
    XIP_BASE + BDEV_OFFSET,
    BDEV_SIZE,
    0,  // no extra info list
    BINARY_INFO_BLOCK_DEV_FLAG_READ
        | BINARY_INFO_BLOCK_DEV_FLAG_WRITE
        | BINARY_INFO_BLOCK_DEV_FLAG_REFORMAT));

int main() {
    // Expose USB stdio so the harness can force BOOTSEL with `reboot -u -f`.
    stdio_init_all();
    while (true) {
        tight_loop_contents();
    }
}
