/*
 * Copyright (c) 2026 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 */

#ifndef DEVICE_MBEDTLS_CONFIG_H
#define DEVICE_MBEDTLS_CONFIG_H

/*
 * mbedtls configuration for picotool running on-device (RP2350).
 *
 * Differences from picotool_mbedtls_config.h (host build):
 *   - No MBEDTLS_HAVE_TIME / MBEDTLS_HAVE_TIME_DATE  (no RTC on bare metal)
 *   - No MBEDTLS_FS_IO                               (no filesystem)
 *   - No MBEDTLS_AESNI_C / MBEDTLS_PADLOCK_C        (x86-only acceleration)
 *   - No MBEDTLS_TIMING_C                            (uses POSIX time API)
 *   - No MBEDTLS_SELF_TEST                           (saves flash)
 *   - MBEDTLS_ENTROPY_HARDWARE_ALT enabled           (pico_mbedtls.c supplies
 *                                                     mbedtls_hardware_poll via
 *                                                     pico/rand.h TRNG)
 *   - MBEDTLS_NO_PLATFORM_ENTROPY enabled            (no /dev/urandom)
 *   - MBEDTLS_AES_ROM_TABLES enabled                 (saves RAM)
 */

#define MBEDTLS_HAVE_ASM

/* Entropy — hardware TRNG provided by pico_mbedtls.c */
#define MBEDTLS_ENTROPY_HARDWARE_ALT
#define MBEDTLS_NO_PLATFORM_ENTROPY

/* Store AES S-boxes in flash rather than computing them in RAM */
#define MBEDTLS_AES_ROM_TABLES

/* Cipher modes */
#define MBEDTLS_CIPHER_MODE_CBC
#define MBEDTLS_CIPHER_MODE_CFB
#define MBEDTLS_CIPHER_MODE_CTR
#define MBEDTLS_CIPHER_MODE_OFB
#define MBEDTLS_CIPHER_MODE_XTS
#define MBEDTLS_CIPHER_PADDING_PKCS7
#define MBEDTLS_CIPHER_PADDING_ONE_AND_ZEROS
#define MBEDTLS_CIPHER_PADDING_ZEROS_AND_LEN
#define MBEDTLS_CIPHER_PADDING_ZEROS

#define MBEDTLS_REMOVE_ARC4_CIPHERSUITES
#define MBEDTLS_REMOVE_3DES_CIPHERSUITES

/* ECP curves — keep the same set as the host build */
#define MBEDTLS_ECP_DP_SECP192R1_ENABLED
#define MBEDTLS_ECP_DP_SECP224R1_ENABLED
#define MBEDTLS_ECP_DP_SECP256R1_ENABLED
#define MBEDTLS_ECP_DP_SECP384R1_ENABLED
#define MBEDTLS_ECP_DP_SECP521R1_ENABLED
#define MBEDTLS_ECP_DP_SECP192K1_ENABLED
#define MBEDTLS_ECP_DP_SECP224K1_ENABLED
#define MBEDTLS_ECP_DP_SECP256K1_ENABLED
#define MBEDTLS_ECP_DP_BP256R1_ENABLED
#define MBEDTLS_ECP_DP_BP384R1_ENABLED
#define MBEDTLS_ECP_DP_BP512R1_ENABLED
#define MBEDTLS_ECP_DP_CURVE25519_ENABLED
#define MBEDTLS_ECP_DP_CURVE448_ENABLED
#define MBEDTLS_ECP_NIST_OPTIM
#define MBEDTLS_ECDH_LEGACY_CONTEXT

/* PK / ASN.1 / certificate support */
#define MBEDTLS_PK_PARSE_EC_EXTENDED
#define MBEDTLS_PK_RSA_ALT_SUPPORT
#define MBEDTLS_PKCS1_V15
#define MBEDTLS_PKCS1_V21

/* Misc feature flags */
#define MBEDTLS_ERROR_STRERROR_DUMMY
#define MBEDTLS_GENPRIME
#define MBEDTLS_VERSION_FEATURES

/* Crypto modules */
#define MBEDTLS_AES_C
#define MBEDTLS_ASN1_PARSE_C
#define MBEDTLS_ASN1_WRITE_C
#define MBEDTLS_BASE64_C
#define MBEDTLS_BIGNUM_C
#define MBEDTLS_CIPHER_C
#define MBEDTLS_CTR_DRBG_C
#define MBEDTLS_ECDSA_C
#define MBEDTLS_ECP_C
#define MBEDTLS_ENTROPY_C
#define MBEDTLS_ERROR_C
#define MBEDTLS_HKDF_C
#define MBEDTLS_HMAC_DRBG_C
#define MBEDTLS_MD_C
#define MBEDTLS_MD5_C
#define MBEDTLS_OID_C
#define MBEDTLS_PEM_PARSE_C
#define MBEDTLS_PEM_WRITE_C
#define MBEDTLS_PK_C
#define MBEDTLS_PK_PARSE_C
#define MBEDTLS_PK_WRITE_C
#define MBEDTLS_PKCS5_C
#define MBEDTLS_PKCS12_C
#define MBEDTLS_PLATFORM_C
#define MBEDTLS_POLY1305_C
#define MBEDTLS_SHA1_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_SHA512_C
#define MBEDTLS_VERSION_C

#endif /* DEVICE_MBEDTLS_CONFIG_H */
