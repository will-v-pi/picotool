/**
 * usb_disconnect - a minimal RAM-only helper for the picotool test suite.
 *
 * Resets the USB controller block, which drops the board's USB pull-up so the
 * device disappears from the host's bus, then spins. The harness runs this
 * from SRAM over SWD (OpenOCD load_image + resume - no flash touched) to take
 * the *other* board off USB while a picotool command is driven with no
 * --bus/--address selector, leaving only the board under test as a candidate.
 *
 * RAM-only so it never disturbs the board's flashed application; a plain
 * `reset run` over SWD afterwards brings the board back up.
 *
 * Works on RP2040 and RP2350 (both expose USBCTRL as a reset block).
 */
#include "pico/stdlib.h"
#include "hardware/resets.h"

int main() {
    reset_block_mask(RESETS_RESET_USBCTRL_BITS);
    while (true) {
        tight_loop_contents();
    }
}
