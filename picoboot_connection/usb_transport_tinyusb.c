/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

// TinyUSB backend for the USB transport abstraction.
// Compiled only for on-device builds where USE_TINYUSB=1.
//
// This file handles:
//   - TinyUSB device lifecycle (mount / unmount / task)
//   - Synchronous wrappers around tuh_control_xfer and tuh_edpt_xfer
//   - Per-device endpoint state (interface number, IN/OUT endpoint addresses)
//
// Integration — wire the lifecycle helpers into your application:
//
//   void tuh_mount_cb(uint8_t daddr)  { usb_tinyusb_mount(daddr); }
//   void tuh_umount_cb(uint8_t daddr) { usb_tinyusb_unmount(daddr); }
//   // in main loop:
//   tuh_task();
//   usb_tinyusb_task();
//
// Buffer alignment:
//   User buffers passed to picoboot_read() / picoboot_write() must be
//   accessible by the USB DMA controller.  On RP2040 any SRAM buffer works.
//   On RP2350 with DCache enabled, use TUH_EPBUF_DEF() or ensure correct
//   cache coherency before/after transfers.

#include "usb_transport.h"

#if USE_TINYUSB

#include "tusb.h"
#include "pico/usb_reset_interface.h"
#include "hardware/structs/usb_dpram.h"
#include <string.h>
#include <stdio.h>

// ─────────────────────────────────────────────────────────────────────────────
// VID / PID constants
// ─────────────────────────────────────────────────────────────────────────────

#define PICOBOOT_VID        0x2e8au
#define PICOBOOT_PID_RP2040 0x0003u
#define PICOBOOT_PID_RP2350 0x000fu

// ─────────────────────────────────────────────────────────────────────────────
// Per-device disconnect flag
//
// Set in usb_tinyusb_unmount, cleared in usb_tinyusb_mount.
// Checked by _ctrl_xfer_sync/_bulk_xfer_sync so their spin loops can exit
// early when the device disconnects mid-transfer (e.g. reboot request STATUS
// stage never completes because the device rebooted).
// ─────────────────────────────────────────────────────────────────────────────

static volatile bool _disconnected[CFG_TUH_DEVICE_MAX + 1];

// ─────────────────────────────────────────────────────────────────────────────
// Per-device state — PICOBOOT devices
// ─────────────────────────────────────────────────────────────────────────────

typedef struct {
    bool    mounted;
    bool    is_rp2350;
    uint8_t itf_num;
    uint8_t out_ep;
    uint8_t in_ep;
} _picoboot_dev_t;

static _picoboot_dev_t  _devs[CFG_TUH_DEVICE_MAX + 1];
static volatile bool    _needs_setup[CFG_TUH_DEVICE_MAX + 1];

// ─────────────────────────────────────────────────────────────────────────────
// Per-device state — stdio_usb / application-mode devices (reset interface)
// ─────────────────────────────────────────────────────────────────────────────

typedef struct {
    bool    mounted;      // reset interface found; device can be rebooted
    bool    is_rp2350;    // inferred from VID
    uint8_t reset_itf;   // interface number of the USB reset interface
} _stdio_dev_t;

static _stdio_dev_t  _stdio_devs[CFG_TUH_DEVICE_MAX + 1];
static volatile bool _needs_reset_check[CFG_TUH_DEVICE_MAX + 1];

// ─────────────────────────────────────────────────────────────────────────────
// Static DMA-accessible shared buffers
//
// On RP2350 with DCache the CFG_TUH_MEM_SECTION / CFG_TUH_MEM_ALIGN attributes
// ensure correct placement and alignment.  All USB transfers go through these
// buffers to guarantee DMA accessibility; the caller's buffer is memcpy-d when
// necessary (control) or used directly (bulk — caller must satisfy DMA rules).
// ─────────────────────────────────────────────────────────────────────────────

CFG_TUH_MEM_SECTION CFG_TUH_MEM_ALIGN static uint8_t _ctrl_data_buf[256];
CFG_TUH_MEM_SECTION CFG_TUH_MEM_ALIGN static uint8_t _config_buf[256];
CFG_TUH_MEM_SECTION CFG_TUH_MEM_ALIGN static uint8_t _halt_status_buf[2];

// ─────────────────────────────────────────────────────────────────────────────
// Internal transfer helpers
// ─────────────────────────────────────────────────────────────────────────────

static void _xfer_complete_cb(tuh_xfer_t *xfer) {
    *((volatile xfer_result_t *)xfer->user_data) = xfer->result;
}

// Synchronous control transfer.
// Returns number of bytes transferred on success (≥ 0), -1 on failure.
static int _ctrl_xfer_sync(uint8_t daddr, uint8_t bmRequestType, uint8_t bRequest,
                            uint16_t wValue, uint16_t wIndex,
                            uint8_t *data, uint16_t len) {
    tusb_control_request_t const req = {
        .bmRequestType = bmRequestType,
        .bRequest      = bRequest,
        .wValue        = tu_htole16(wValue),
        .wIndex        = tu_htole16(wIndex),
        .wLength       = tu_htole16(len),
    };
    volatile xfer_result_t result = XFER_RESULT_INVALID;
    tuh_xfer_t xfer = {
        .daddr       = daddr,
        .ep_addr     = 0,
        .setup       = &req,
        .buffer      = data,
        .complete_cb = _xfer_complete_cb,
        .user_data   = (uintptr_t)&result,
    };
    if (!tuh_control_xfer(&xfer)) return -1;
    while (result == XFER_RESULT_INVALID) {
        if (daddr < TU_ARRAY_SIZE(_disconnected) && _disconnected[daddr]) return -1;
        tuh_task();
    }
    return (result == XFER_RESULT_SUCCESS) ? (int)len : -1;
}

// Synchronous bulk transfer.  Returns 0 on success, -1 on failure.
static int _bulk_xfer_sync(uint8_t daddr, uint8_t ep_addr,
                            uint8_t *buf, uint32_t len) {
    volatile xfer_result_t result = XFER_RESULT_INVALID;
    tuh_xfer_t xfer = {
        .daddr       = daddr,
        .ep_addr     = ep_addr,
        .buflen      = len,
        .buffer      = buf,
        .complete_cb = _xfer_complete_cb,
        .user_data   = (uintptr_t)&result,
    };
    if (!tuh_edpt_xfer(&xfer)) return -1;
    while (result == XFER_RESULT_INVALID) {
        if (daddr < TU_ARRAY_SIZE(_disconnected) && _disconnected[daddr]) return -1;
        tuh_task();
    }
    return (result == XFER_RESULT_SUCCESS) ? 0 : -1;
}

// ─────────────────────────────────────────────────────────────────────────────
// Device setup helpers
// ─────────────────────────────────────────────────────────────────────────────

// Walk the configuration descriptor of a non-PICOBOOT RP-series device to find
// a USB reset interface (class=0xFF, subclass=0x00, protocol=0x01).  If found,
// the device is recorded as a stdio_usb device that can be rebooted.
static void _check_reset_interface(uint8_t daddr) {
    if (XFER_RESULT_SUCCESS !=
        tuh_descriptor_get_configuration_sync(daddr, 0,
                                              _config_buf, sizeof(_config_buf))) {
        return;
    }

    _stdio_dev_t *dev = &_stdio_devs[daddr];
    dev->reset_itf = 0xff;

    tusb_desc_configuration_t const *p_cfg =
        (tusb_desc_configuration_t const *)_config_buf;
    uint8_t const *p   = (uint8_t const *)p_cfg;
    uint8_t const *end = p + tu_le16toh(p_cfg->wTotalLength);
    p = tu_desc_next(p);

    while (p < end) {
        if (tu_desc_type(p) == TUSB_DESC_INTERFACE) {
            tusb_desc_interface_t const *itf = (tusb_desc_interface_t const *)p;
            if (itf->bInterfaceClass    == 0xffu &&
                itf->bInterfaceSubClass == RESET_INTERFACE_SUBCLASS &&
                itf->bInterfaceProtocol == RESET_INTERFACE_PROTOCOL) {
                dev->reset_itf = itf->bInterfaceNumber;
                dev->mounted   = true;
                printf("stdio_usb: addr %u  reset_itf=%u  is_rp2350=%u\r\n",
                       daddr, dev->reset_itf, dev->is_rp2350);
                return;
            }
        }
        p = tu_desc_next(p);
    }
}

// Walk the configuration descriptor to find the PICOBOOT interface
// (class=0xFF, exactly 2 bulk endpoints) and opens those endpoints.
// Called deferred from usb_tinyusb_task(), not from a TinyUSB callback.
// ─────────────────────────────────────────────────────────────────────────────

static bool _setup_device(uint8_t daddr) {
    if (XFER_RESULT_SUCCESS !=
        tuh_descriptor_get_configuration_sync(daddr, 0,
                                              _config_buf, sizeof(_config_buf))) {
        printf("PICOBOOT: failed to get config descriptor (addr %u)\r\n", daddr);
        return false;
    }

    _picoboot_dev_t *dev = &_devs[daddr];
    dev->itf_num = 0xff;
    dev->out_ep  = 0;
    dev->in_ep   = 0;

    tusb_desc_configuration_t const *p_cfg =
        (tusb_desc_configuration_t const *)_config_buf;
    uint8_t const *p   = (uint8_t const *)p_cfg;
    uint8_t const *end = p + tu_le16toh(p_cfg->wTotalLength);
    bool in_picoboot_itf = false;
    p = tu_desc_next(p);

    while (p < end) {
        switch (tu_desc_type(p)) {
            case TUSB_DESC_INTERFACE: {
                tusb_desc_interface_t const *itf = (tusb_desc_interface_t const *)p;
                if (itf->bInterfaceClass == 0xff && itf->bNumEndpoints == 2) {
                    dev->itf_num    = itf->bInterfaceNumber;
                    in_picoboot_itf = true;
                } else {
                    in_picoboot_itf = false;
                }
                break;
            }
            case TUSB_DESC_ENDPOINT: {
                if (!in_picoboot_itf) break;
                tusb_desc_endpoint_t const *ep = (tusb_desc_endpoint_t const *)p;
                if (!tuh_edpt_open(daddr, ep)) {
                    printf("PICOBOOT: failed to open endpoint 0x%02x\r\n",
                           ep->bEndpointAddress);
                    return false;
                }
                if (ep->bEndpointAddress & TUSB_DIR_IN_MASK) {
                    dev->in_ep = ep->bEndpointAddress;
                } else {
                    dev->out_ep = ep->bEndpointAddress;
                }
                break;
            }
            default:
                break;
        }
        p = tu_desc_next(p);
    }

    if (!dev->out_ep || !dev->in_ep) {
        printf("PICOBOOT: PICOBOOT interface not found on addr %u\r\n", daddr);
        return false;
    }

    dev->mounted = true;
    printf("PICOBOOT: addr %u ready  itf=%u  out=0x%02x  in=0x%02x\r\n",
           daddr, dev->itf_num, dev->out_ep, dev->in_ep);
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Public lifecycle
// ─────────────────────────────────────────────────────────────────────────────

void usb_tinyusb_mount(uint8_t daddr) {
    if (daddr < TU_ARRAY_SIZE(_disconnected)) _disconnected[daddr] = false;
    uint16_t vid, pid;
    tuh_vid_pid_get(daddr, &vid, &pid);
    if (vid == PICOBOOT_VID &&
        (pid == PICOBOOT_PID_RP2040 || pid == PICOBOOT_PID_RP2350)) {
        printf("PICOBOOT: detected  addr=%u  VID=%04x  PID=%04x  chip=%s\r\n",
               daddr, vid, pid,
               pid == PICOBOOT_PID_RP2350 ? "RP2350" : "RP2040");
        if (daddr < TU_ARRAY_SIZE(_needs_setup)) {
            _devs[daddr].is_rp2350 = (pid == PICOBOOT_PID_RP2350);
            _needs_setup[daddr]    = true;
        }
    } else if (vid == PICOBOOT_VID && daddr < TU_ARRAY_SIZE(_stdio_devs)) {
        // Non-PICOBOOT RP-series device: check for USB reset interface so we
        // can offer force-reboot to BOOTSEL mode.
        printf("stdio_usb: detected  addr=%u  VID=%04x  PID=%04x\r\n",
               daddr, vid, pid);
        _stdio_devs[daddr].is_rp2350     = false; // conservative default
        _stdio_devs[daddr].mounted       = false;
        _needs_reset_check[daddr]        = true;
    }
}

void usb_tinyusb_unmount(uint8_t daddr) {
    if (daddr < TU_ARRAY_SIZE(_disconnected)) _disconnected[daddr] = true;
    if (daddr < TU_ARRAY_SIZE(_devs)) {
        bool was_picoboot = _devs[daddr].mounted || _needs_setup[daddr];
        bool was_stdio    = _stdio_devs[daddr].mounted || _needs_reset_check[daddr];
        _devs[daddr].mounted        = false;
        _needs_setup[daddr]         = false;
        _stdio_devs[daddr].mounted  = false;
        _needs_reset_check[daddr]   = false;
        if (was_picoboot)
            printf("PICOBOOT: addr %u disconnected\r\n", daddr);
        else if (was_stdio)
            printf("stdio_usb: addr %u disconnected\r\n", daddr);

        // hcd_device_close() in TinyUSB iterates ep_pool[1..N] and clears each
        // endpoint's buffer_control register, but the shared EPX control endpoint
        // is a separate global that it never touches.  If the device disconnected
        // while a control transfer was in flight (e.g. the reboot STATUS stage
        // ZLP was pending), USB_BUF_CTRL_AVAIL can be left set in epx_buf_ctrl.
        // The next device that enumerates then panics in
        // _hw_endpoint_buffer_control_update32 when it tries to set AVAIL again.
        // Clear the register here as a workaround.
        usbh_dpram->epx_buf_ctrl = 0;
    }
}

void usb_tinyusb_task(void) {
    for (uint8_t daddr = 1; daddr < TU_ARRAY_SIZE(_needs_setup); daddr++) {
        if (_needs_setup[daddr]) {
            _needs_setup[daddr] = false;
            _setup_device(daddr);
        }
        if (_needs_reset_check[daddr]) {
            _needs_reset_check[daddr] = false;
            _check_reset_interface(daddr);
        }
    }
}

bool usb_tinyusb_is_mounted(uint8_t daddr) {
    return daddr < TU_ARRAY_SIZE(_devs) && _devs[daddr].mounted;
}

uint8_t usb_tinyusb_get_daddr(void) {
    for (uint8_t daddr = 1; daddr < TU_ARRAY_SIZE(_devs); daddr++) {
        if (_devs[daddr].mounted) return daddr;
    }
    return 0;
}

bool usb_tinyusb_is_rp2350(uint8_t daddr) {
    return daddr < TU_ARRAY_SIZE(_devs) && _devs[daddr].is_rp2350;
}

uint8_t usb_tinyusb_get_stdio_daddr(void) {
    for (uint8_t daddr = 1; daddr < TU_ARRAY_SIZE(_stdio_devs); daddr++) {
        if (_stdio_devs[daddr].mounted) return daddr;
    }
    return 0;
}

bool usb_tinyusb_is_stdio_mounted(uint8_t daddr) {
    return daddr < TU_ARRAY_SIZE(_stdio_devs) && _stdio_devs[daddr].mounted;
}

bool usb_tinyusb_is_stdio_rp2350(uint8_t daddr) {
    return daddr < TU_ARRAY_SIZE(_stdio_devs) && _stdio_devs[daddr].is_rp2350;
}

int usb_tinyusb_reboot_device(uint8_t daddr, bool bootsel, unsigned int disable_mask) {
    if (daddr >= TU_ARRAY_SIZE(_stdio_devs) || !_stdio_devs[daddr].mounted) return -1;
    uint8_t  itf      = _stdio_devs[daddr].reset_itf;
    uint8_t  bRequest = bootsel ? (uint8_t)RESET_REQUEST_BOOTSEL : (uint8_t)RESET_REQUEST_FLASH;
    uint16_t wValue   = bootsel ? (uint16_t)disable_mask : 0u;
    return _ctrl_xfer_sync(daddr,
                           (uint8_t)(TUSB_REQ_TYPE_CLASS | TUSB_REQ_RCPT_INTERFACE),
                           bRequest, wValue, itf, NULL, 0);
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport interface — control transfer
//
// Control data is bounced through _ctrl_data_buf to guarantee DMA alignment
// on RP2350.  The bounce is only skipped for NULL data (zero-length transfers).
// ─────────────────────────────────────────────────────────────────────────────

int usb_ctrl_transfer(usb_device_t dev, uint8_t bmRequestType, uint8_t bRequest,
                      uint16_t wValue, uint16_t wIndex, unsigned char *data,
                      uint16_t length, unsigned int timeout_ms) {
    (void)timeout_ms;

    if (!data || length == 0) {
        return _ctrl_xfer_sync(dev, bmRequestType, bRequest,
                               wValue, wIndex, NULL, 0);
    }

    if (length > sizeof(_ctrl_data_buf)) return -1;

    // OUT transfer: copy caller data into DMA-accessible buffer before sending
    if (!(bmRequestType & TUSB_DIR_IN_MASK)) {
        memcpy(_ctrl_data_buf, data, length);
    }

    int ret = _ctrl_xfer_sync(dev, bmRequestType, bRequest,
                               wValue, wIndex, _ctrl_data_buf, length);

    // IN transfer: copy received data back to caller
    if (ret >= 0 && (bmRequestType & TUSB_DIR_IN_MASK)) {
        memcpy(data, _ctrl_data_buf, length);
    }

    return ret;
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport interface — bulk transfer
//
// The caller's buffer is passed directly to tuh_edpt_xfer.  The caller must
// ensure it is DMA-accessible (use TUH_EPBUF_DEF or a static buffer with
// CFG_TUH_MEM_SECTION on RP2350 with DCache).
// ─────────────────────────────────────────────────────────────────────────────

int usb_bulk_transfer(usb_device_t dev, uint8_t endpoint, unsigned char *data,
                      int length, int *actual_length, unsigned int timeout_ms) {
    (void)timeout_ms;
    int ret = _bulk_xfer_sync(dev, endpoint, data, (uint32_t)length);
    if (actual_length) *actual_length = (ret == 0) ? length : 0;
    return ret;
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport interface — endpoint halt management
// ─────────────────────────────────────────────────────────────────────────────

bool usb_is_endpoint_halted(usb_device_t dev, uint8_t ep) {
    int ret = _ctrl_xfer_sync(dev,
                              (uint8_t)(TUSB_DIR_IN_MASK | TUSB_REQ_RCPT_ENDPOINT),
                              TUSB_REQ_GET_STATUS, 0, ep,
                              _halt_status_buf, sizeof(_halt_status_buf));
    return (ret >= 0) && (_halt_status_buf[0] & 1u);
}

int usb_clear_endpoint_halt(usb_device_t dev, uint8_t ep) {
    return _ctrl_xfer_sync(dev,
                           TUSB_REQ_RCPT_ENDPOINT,
                           TUSB_REQ_CLEAR_FEATURE,
                           TUSB_REQ_FEATURE_EDPT_HALT, ep,
                           NULL, 0);
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport interface — accessors
// ─────────────────────────────────────────────────────────────────────────────

void usb_set_device_endpoints(usb_device_t dev,
                               unsigned int itf,
                               unsigned int out_ep,
                               unsigned int in_ep) {
    if (dev >= TU_ARRAY_SIZE(_devs)) return;
    _devs[dev].itf_num = (uint8_t)itf;
    _devs[dev].out_ep  = (uint8_t)out_ep;
    _devs[dev].in_ep   = (uint8_t)in_ep;
}

unsigned int usb_get_interface(usb_device_t dev) {
    return (dev < TU_ARRAY_SIZE(_devs)) ? _devs[dev].itf_num : 0u;
}

unsigned int usb_get_out_ep(usb_device_t dev) {
    return (dev < TU_ARRAY_SIZE(_devs)) ? _devs[dev].out_ep : 0u;
}

unsigned int usb_get_in_ep(usb_device_t dev) {
    return (dev < TU_ARRAY_SIZE(_devs)) ? _devs[dev].in_ep : 0u;
}

// ─────────────────────────────────────────────────────────────────────────────
// Transport interface — error string
// ─────────────────────────────────────────────────────────────────────────────

const char *usb_error_name(int error_code) {
    (void)error_code;
    return "usb_error";
}

#endif // USE_TINYUSB
