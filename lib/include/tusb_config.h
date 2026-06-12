/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef _TUSB_CONFIG_H_
#define _TUSB_CONFIG_H_

#ifdef __cplusplus
extern "C" {
#endif

//--------------------------------------------------------------------
// Common Configuration
//--------------------------------------------------------------------

#ifndef CFG_TUSB_MCU
#error CFG_TUSB_MCU must be defined
#endif

#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS           OPT_OS_NONE
#endif

#ifndef CFG_TUSB_DEBUG
#define CFG_TUSB_DEBUG        0
#endif

// USB DMA buffers must be in memory accessible to the DMA controller.
// On RP2350 with DCache these attributes place buffers in the correct section.
#ifndef CFG_TUH_MEM_SECTION
#define CFG_TUH_MEM_SECTION
#endif

#ifndef CFG_TUH_MEM_ALIGN
#define CFG_TUH_MEM_ALIGN     __attribute__((aligned(4)))
#endif

//--------------------------------------------------------------------
// Host Configuration
//--------------------------------------------------------------------

#define CFG_TUH_ENABLED       1

// Default to host port 0 (native USB on RP2350); boards can override.
#ifndef BOARD_TUH_RHPORT
#define BOARD_TUH_RHPORT      0
#endif

#ifndef BOARD_TUH_MAX_SPEED
#define BOARD_TUH_MAX_SPEED   OPT_MODE_DEFAULT_SPEED
#endif

#define CFG_TUH_MAX_SPEED     BOARD_TUH_MAX_SPEED

// Descriptor buffer used during enumeration.
// 512 bytes to comfortably hold a full configuration descriptor.
#define CFG_TUH_ENUMERATION_BUFSIZE 512

// Required for the synchronous bulk/control transfer helpers in
// usb_transport_tinyusb.c (_bulk_xfer_sync / _ctrl_xfer_sync).
#define CFG_TUH_API_EDPT_XFER 1

//--------------------------------------------------------------------
// Driver Configuration
//
// picotool only communicates via raw endpoint transfers (PICOBOOT
// vendor class and the USB reset interface).  No CDC/HID/MSC drivers
// are needed.
//--------------------------------------------------------------------

// Support one hub so a device behind a hub can still be reached.
#define CFG_TUH_HUB           1

// max devices (excluding hubs); 1 hub typically exposes 4 ports
#define CFG_TUH_DEVICE_MAX    (4*CFG_TUH_HUB + 1)

#define CFG_TUH_CDC           0
#define CFG_TUH_HID           0
#define CFG_TUH_MSC           0
#define CFG_TUH_VENDOR        0

#ifdef __cplusplus
}
#endif

#endif /* _TUSB_CONFIG_H_ */
