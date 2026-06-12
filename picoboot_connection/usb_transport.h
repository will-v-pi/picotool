/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

// Abstract USB transport interface for picoboot_connection.
//
// Select a backend by defining exactly one of:
//   HAS_LIBUSB=1  – libusb (desktop build, default)
//   USE_TINYUSB=1 – TinyUSB host (on-device build, e.g. RP2350 as USB host)
//
// Both backends expose the same set of functions so that picoboot_connection.c
// compiles without modification for either target.

#pragma once

#include <stdint.h>
#include <stdbool.h>

// ─────────────────────────────────────────────────────────────────────────────
// usb_device_t — backend-specific device handle
// ─────────────────────────────────────────────────────────────────────────────

#if USE_TINYUSB
    // TinyUSB identifies devices by their 8-bit address on the bus.
    typedef uint8_t usb_device_t;
    #define INVALID_USB_DEVICE ((usb_device_t)0)
#elif HAS_LIBUSB
    // libusb uses an opaque handle pointer.
    struct libusb_device_handle;
    typedef struct libusb_device_handle *usb_device_t;
    #define INVALID_USB_DEVICE ((usb_device_t)NULL)
#else
    typedef void *usb_device_t;
    #define INVALID_USB_DEVICE ((usb_device_t)NULL)
#endif

// ─────────────────────────────────────────────────────────────────────────────
// Standard USB bmRequestType field components (USB 2.0 spec values).
// These match the libusb definitions so code written against libusb constants
// compiles without change.
// ─────────────────────────────────────────────────────────────────────────────

#define USB_REQ_TYPE_STANDARD    0x00u
#define USB_REQ_TYPE_CLASS       0x20u
#define USB_REQ_TYPE_VENDOR      0x40u

#define USB_RECIPIENT_DEVICE     0x00u
#define USB_RECIPIENT_INTERFACE  0x01u
#define USB_RECIPIENT_ENDPOINT   0x02u

#define USB_ENDPOINT_IN          0x80u
#define USB_ENDPOINT_OUT         0x00u

// Standard bRequest codes
#define USB_REQ_GET_STATUS       0x00u
#define USB_REQ_CLEAR_FEATURE    0x01u

// Feature selector for ClearFeature(ENDPOINT_HALT)
#define USB_ENDPOINT_HALT_FEATURE 0x00u

// ─────────────────────────────────────────────────────────────────────────────
// USB_XFER_BUF — DMA-accessible buffer declaration
//
// TinyUSB (especially on RP2350 with DCache) requires buffers passed to
// tuh_edpt_xfer to be DMA-accessible with correct alignment.  This macro
// declares a static buffer with the necessary attributes on TinyUSB builds and
// falls back to a plain stack declaration on libusb builds.
//
// Usage:  USB_XFER_BUF(uint8_t, ack_buf, 64);
// ─────────────────────────────────────────────────────────────────────────────

#if USE_TINYUSB
    #include "tusb.h"
    #define USB_XFER_BUF(type, name, size) \
        CFG_TUH_MEM_SECTION CFG_TUH_MEM_ALIGN static type name[size]
#else
    #define USB_XFER_BUF(type, name, size) type name[size]
#endif

// ─────────────────────────────────────────────────────────────────────────────
// Transfer functions
// ─────────────────────────────────────────────────────────────────────────────

// Control transfer on EP0.
// Returns the number of bytes transferred on success (≥ 0), negative on error.
int usb_ctrl_transfer(usb_device_t dev, uint8_t bmRequestType, uint8_t bRequest,
                      uint16_t wValue, uint16_t wIndex, unsigned char *data,
                      uint16_t length, unsigned int timeout_ms);

// Bulk transfer on a non-zero endpoint.
// Returns 0 on success, negative on error.
// *actual_length (if non-NULL) is set to the number of bytes transferred.
int usb_bulk_transfer(usb_device_t dev, uint8_t endpoint, unsigned char *data,
                      int length, int *actual_length, unsigned int timeout_ms);

// ─────────────────────────────────────────────────────────────────────────────
// Endpoint halt (STALL) management
// ─────────────────────────────────────────────────────────────────────────────

bool usb_is_endpoint_halted(usb_device_t dev, uint8_t ep);
int  usb_clear_endpoint_halt(usb_device_t dev, uint8_t ep);

// ─────────────────────────────────────────────────────────────────────────────
// Interface / endpoint accessors
//
// For libusb builds these return the global state set by picoboot_open_device.
// For TinyUSB builds they read per-device state populated during device setup.
// ─────────────────────────────────────────────────────────────────────────────

unsigned int usb_get_interface(usb_device_t dev);
unsigned int usb_get_out_ep(usb_device_t dev);
unsigned int usb_get_in_ep(usb_device_t dev);

// Register the interface/endpoint mapping for a device.
// Called from picoboot_open_device() in the libusb build.
// For TinyUSB builds this is called automatically during device setup, but may
// also be called by the application if it performs its own enumeration.
void usb_set_device_endpoints(usb_device_t dev,
                               unsigned int itf,
                               unsigned int out_ep,
                               unsigned int in_ep);

// ─────────────────────────────────────────────────────────────────────────────
// Error description
// ─────────────────────────────────────────────────────────────────────────────

// Returns a human-readable string for an error code.
// On libusb builds this wraps libusb_error_name; on TinyUSB builds it returns
// a generic string.
const char *usb_error_name(int error_code);

// ─────────────────────────────────────────────────────────────────────────────
// TinyUSB lifecycle helpers (only available in USE_TINYUSB builds)
//
// Wire these into your application's TinyUSB callbacks and main loop:
//
//   void tuh_mount_cb(uint8_t daddr)   { usb_tinyusb_mount(daddr); }
//   void tuh_umount_cb(uint8_t daddr)  { usb_tinyusb_unmount(daddr); }
//   // in main loop:
//   usb_tinyusb_task();
// ─────────────────────────────────────────────────────────────────────────────

#if USE_TINYUSB

#ifdef __cplusplus
extern "C" {
#endif

// Check whether daddr is a PICOBOOT device and schedule endpoint setup.
// Call from tuh_mount_cb().
void usb_tinyusb_mount(uint8_t daddr);

// Clean up state for a disconnected device.
// Call from tuh_umount_cb().
void usb_tinyusb_unmount(uint8_t daddr);

// Perform deferred endpoint setup for newly detected PICOBOOT devices.
// Call every iteration of the main loop.
void usb_tinyusb_task(void);

// Returns true if daddr is a ready PICOBOOT device.
bool usb_tinyusb_is_mounted(uint8_t daddr);

// Returns the device address of the first connected PICOBOOT device, or 0.
uint8_t usb_tinyusb_get_daddr(void);

// Returns true if the device at daddr is an RP2350 (false = RP2040).
bool usb_tinyusb_is_rp2350(uint8_t daddr);

// ─────────────────────────────────────────────────────────────────────────────
// stdio_usb (application mode) device support.
// Detects non-PICOBOOT RP-series devices that expose a USB reset interface,
// enabling forced reboot to BOOTSEL mode.
// ─────────────────────────────────────────────────────────────────────────────

// Returns the device address of the first connected stdio_usb device, or 0.
uint8_t usb_tinyusb_get_stdio_daddr(void);

// Returns true if daddr is a ready stdio_usb device (has reset interface).
bool usb_tinyusb_is_stdio_mounted(uint8_t daddr);

// Returns true if the stdio_usb device at daddr is an RP2350.
bool usb_tinyusb_is_stdio_rp2350(uint8_t daddr);

// Send a USB reset-interface control request to reboot the device.
//   bootsel=true  → reboot into BOOTSEL mode (RESET_REQUEST_BOOTSEL)
//   bootsel=false → reboot into application mode (RESET_REQUEST_FLASH)
//   disable_mask  → passed as wValue in the BOOTSEL request (e.g. MSC disable)
// Returns 0 on success, negative on error.
int usb_tinyusb_reboot_device(uint8_t daddr, bool bootsel, unsigned int disable_mask);

#ifdef __cplusplus
} // extern "C"
#endif

#endif // USE_TINYUSB
