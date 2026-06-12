/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

// libusb backend for the USB transport abstraction.
// Compiled when HAS_LIBUSB=1 and USE_TINYUSB is not set.

#include "usb_transport.h"

#if HAS_LIBUSB && !USE_TINYUSB

#include <libusb.h>

// ─────────────────────────────────────────────────────────────────────────────
// Per-handle state
//
// Only one device at a time is supported — this matches the module-level
// global design already present in picoboot_connection.c.
// ─────────────────────────────────────────────────────────────────────────────

static unsigned int _interface;
static unsigned int _out_ep;
static unsigned int _in_ep;

// ─────────────────────────────────────────────────────────────────────────────
// Transfer operations
// ─────────────────────────────────────────────────────────────────────────────

int usb_ctrl_transfer(usb_device_t dev, uint8_t bmRequestType, uint8_t bRequest,
                      uint16_t wValue, uint16_t wIndex, unsigned char *data,
                      uint16_t length, unsigned int timeout_ms) {
    return libusb_control_transfer(dev, bmRequestType, bRequest, wValue, wIndex,
                                   data, length, (unsigned int)timeout_ms);
}

int usb_bulk_transfer(usb_device_t dev, uint8_t endpoint, unsigned char *data,
                      int length, int *actual_length, unsigned int timeout_ms) {
    int transferred = 0;
    int ret = libusb_bulk_transfer(dev, endpoint, data, length,
                                   &transferred, (unsigned int)timeout_ms);
    if (actual_length) *actual_length = transferred;
    return ret;
}

// ─────────────────────────────────────────────────────────────────────────────
// Endpoint halt management
// ─────────────────────────────────────────────────────────────────────────────

bool usb_is_endpoint_halted(usb_device_t dev, uint8_t ep) {
    uint8_t status[2] = {0, 0};
    int ret = libusb_control_transfer(
        dev,
        (uint8_t)(LIBUSB_RECIPIENT_ENDPOINT | LIBUSB_ENDPOINT_IN),
        LIBUSB_REQUEST_GET_STATUS,
        0, ep, status, (uint16_t)sizeof(status), 1000);
    return (ret == (int)sizeof(status)) && (status[0] & 1u);
}

int usb_clear_endpoint_halt(usb_device_t dev, uint8_t ep) {
    return libusb_clear_halt(dev, ep);
}

// ─────────────────────────────────────────────────────────────────────────────
// Accessors
// ─────────────────────────────────────────────────────────────────────────────

void usb_set_device_endpoints(usb_device_t dev,
                               unsigned int itf,
                               unsigned int out_ep,
                               unsigned int in_ep) {
    (void)dev;  // single-device: ignore the handle
    _interface = itf;
    _out_ep    = out_ep;
    _in_ep     = in_ep;
}

unsigned int usb_get_interface(usb_device_t dev) { (void)dev; return _interface; }
unsigned int usb_get_out_ep(usb_device_t dev)    { (void)dev; return _out_ep; }
unsigned int usb_get_in_ep(usb_device_t dev)     { (void)dev; return _in_ep; }

// ─────────────────────────────────────────────────────────────────────────────
// Error string
// ─────────────────────────────────────────────────────────────────────────────

const char *usb_error_name(int error_code) {
    return libusb_error_name(error_code);
}

#endif // HAS_LIBUSB && !USE_TINYUSB
