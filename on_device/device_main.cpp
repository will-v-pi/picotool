/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#if !USE_TINYUSB
    #error "device_main.cpp should only be compiled with USE_TINYUSB"
#endif

#include "pico/stdlib.h"
#include "hardware/watchdog.h"
#include "bsp/board_api.h"

#include <string>
#include <vector>

#include "usb_transport.h"

extern int picotool_main(int argc, char **argv);

static std::vector<std::string> current_argv = {};
static std::string current_string = "";
static bool in_quotes = false;
static volatile bool argv_done = false;
void key_pressed_func(void *param) {
    if (argv_done) return;
    int key = getchar_timeout_us(0);
    printf("%c", key);

    bool word_done = false;
    bool skip_char = false;
    if (key == '\n' || key == '\r') {
        word_done = true;
        argv_done = true;
    } else if (key == ' ' && !in_quotes) {
        word_done = true;
    } else if (key == '"' || key == '\'') {
        in_quotes = !in_quotes;
    } else if (key == '\b') {
        if (current_string.empty()) {
            current_string = current_argv.back();
            current_argv.pop_back();
        } else {
            current_string.pop_back();
        }
        skip_char = true;
        printf(" \b"); // actually delete char from output
    }

    if (word_done) {
        current_argv.push_back(current_string);
        current_string = "";
    } else if (!skip_char) {
        current_string += key;
    }
}

bool repeating_timer_callback(__unused repeating_timer_t *t) {
    watchdog_update();
    return true;
}

extern "C" void tuh_mount_cb(uint8_t daddr) {
    usb_tinyusb_mount(daddr);
}

extern "C" void tuh_umount_cb(uint8_t daddr) {
    usb_tinyusb_unmount(daddr);
}

int main(void) {
    stdio_init_all();

    if (watchdog_enable_caused_reboot()) {
        printf("ERROR: Rebooted by Watchdog\n");
    }

    board_init();
    printf("TinyUSB Picotool\n");
    tuh_init(BOARD_TUH_RHPORT);

    printf("Ready\n");
    stdio_set_chars_available_callback(key_pressed_func, NULL);

    while (!argv_done) {
        tight_loop_contents();
    }

    int argc = current_argv.size();
    char *argv[argc];
    for (int i=0; i < argc; i++) {
        argv[i] = (char*)current_argv[i].c_str();
    }

    printf("argc %d, argv: ", argc);
    for (int argnum=0; argnum < argc; argnum++) {
        printf("%s ", argv[argnum]);
    }
    printf("\n");

    // Add watchdog for crashes
    repeating_timer_t timer;
    add_repeating_timer_ms(5000, repeating_timer_callback, NULL, &timer);
    watchdog_enable(7000, true);

    picotool_main(argc, argv);

    // Reboot ready for next command
    watchdog_reboot(0, 0, 100);
}
