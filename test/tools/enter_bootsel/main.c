/**
 * enter_bootsel - a minimal recovery program for the picotool test suite.
 *
 * On boot it immediately drops the chip into BOOTSEL (USB mass-storage /
 * PICOBOOT) mode by calling the bootrom. Flashing this over SWD with a debug
 * probe therefore gives the test harness a deterministic way to get a board
 * into BOOTSEL regardless of what (if anything) was running before - it does
 * not rely on the previously flashed application exposing the USB reset
 * interface.
 *
 * Works on both RP2040 and RP2350 (reset_usb_boot is provided by the bootrom
 * on both families).
 */
#include "pico/stdlib.h"
#include "pico/bootrom.h"

int main() {
    // usb_activity_gpio_pin_mask = 0 (no activity LED), disable_interface_mask = 0
    // (expose both the mass-storage and PICOBOOT interfaces).
    reset_usb_boot(0, 0);
    // reset_usb_boot does not return, but keep the compiler happy.
    while (true) {
        tight_loop_contents();
    }
}
