"""Secure boot and rollback-protection tests against a live RP2350 device.

These provision real secure-boot state into OTP - see test_seal_secure_boot.py
for the file-only tests of picotool's seal/sign/rollback logic itself, which
need no hardware and always run.

There are two distinct risk tiers here, gated separately:

1. TestProvisionBootKey - burns one boot-key slot (BOOTKEY0 + KEY_VALID) but
   deliberately does NOT set CRIT1.SECURE_BOOT_ENABLE, so the board still boots
   ordinary unsigned images afterward. Gated behind --run-otp like the rest of
   test_otp_device.py, and uses the normal board/rp2350_board fixtures (whose
   teardown reflashes a plain unsigned app - which still works here).

2. TestSecureBootEnforcement - sets CRIT1.SECURE_BOOT_ENABLE. This is not like
   the other OTP tests: it is a ONE-WAY, WHOLE-CHIP operation. Once set, this
   *specific physical chip* will NEVER again boot an unsigned image, for the
   rest of its life - there is no "restore to normal" afterward, unlike every
   other test in this suite. Per picotool's own OTP field description:

       SECURE_BOOT_ENABLE: "Enable boot signature enforcement, and permanently
       disable the RISC-V cores."

   i.e. this ALSO permanently removes RISC-V boot capability from the chip,
   independent of and in addition to the secure-boot lock-in - do not run this
   against any chip you might ever want to boot in RISC-V mode again. It
   requires BOTH --run-otp AND a second, separate opt-in
   (PICOTOOL_TEST_ENABLE_SECURE_BOOT=1) so it can never fire just because
   --run-otp is set for the (recoverable) tests elsewhere in this module.

   Only ever run this against an FPGA image whose OTP-equivalent state you can
   reset afterward, and run it IN ISOLATION - once it has run, plain/unsigned
   binaries used by the rest of this suite (blink, hello_usb, etc.) will no
   longer boot on that chip, breaking every other hardware test that assumes a
   board can be returned to an ordinary unsigned app. This class deliberately
   does NOT use the shared board/rp2350_board fixtures, because their teardown
   reflashes a plain unsigned app - which would never come up again here. It
   manages its own device handle and its own recovery (reloading the last
   signed-good image) instead of relying on the shared machinery.

This has been carefully derived from picotool's documented seal/otp behaviour
and verified file-side (test_seal_secure_boot.py; the exact wording asserted
below - "signature: incorrect", the DEFAULT_BOOT_VERSION0/1 thermometer-counter
rows, --rollback's row-count and row-spacing rules) - but the on-device
enforcement paths in TestSecureBootEnforcement have deliberately never been run
against real hardware while writing this suite (only real, disposable Pico /
Pico 2 boards were available, never an OTP-resettable FPGA). Treat this class
as reviewed-but-unexercised until it has been run once, successfully, on your
FPGA.
"""
import json
import os
import re
import subprocess

import pytest

from lib.devices import Board

pytestmark = [pytest.mark.hardware, pytest.mark.rp2350, pytest.mark.otp]

ENABLE_SECURE_BOOT = os.environ.get("PICOTOOL_TEST_ENABLE_SECURE_BOOT") == "1"


def _genkey(path):
    subprocess.run(
        ["openssl", "ecparam", "-name", "secp256k1", "-genkey", "-out", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _flip_byte_in_first_segment(src, dst):
    """Corrupt one byte inside the source ELF's first PT_LOAD segment - see the
    identical helper (and its rationale) in test_seal_secure_boot.py."""
    data = bytearray(open(src, "rb").read())
    data[0x2000] ^= 0xFF
    open(dst, "wb").write(data)


class TestProvisionBootKey:
    """Burns a boot key slot; does NOT enable secure boot enforcement."""

    def test_boot_key_burns_and_reads_back(self, rp2350_board, require_binaries, tmp_path):
        elf = require_binaries["rp2350"].path("hello_usb.elf")
        key = _genkey(tmp_path / "key.pem")
        signed = tmp_path / "signed.elf"
        full_otp = tmp_path / "otp.json"
        assert rp2350_board.pt.run(
            "seal", "--sign", str(elf), str(signed), str(key), str(full_otp)
        ).ok

        # Strip secure_boot_enable before provisioning - this test must not
        # enable enforcement, only burn the key material.
        data = json.loads(full_otp.read_text())
        data.pop("crit1", None)
        stripped = tmp_path / "otp_no_enable.json"
        stripped.write_text(json.dumps(data))

        with rp2350_board.bootsel() as dev:
            dev.ok("otp", "load", str(stripped))
            # `otp get` prints "field NAME (bits N) = VALUE" - bootkey0's slot is
            # bit 0 of KEY_VALID, so setting only it gives a field value of 1.
            key_valid = dev.ok("otp", "get", "BOOT_FLAGS1.KEY_VALID")
            assert re.search(r"KEY_VALID\b.*=\s*1\b", key_valid.out, re.DOTALL), key_valid
            bootkey0 = dev.ok("otp", "get", "BOOTKEY0_0")
            assert bootkey0.ok
            # secure boot must still be OFF - this test never touched CRIT1.
            enable = dev.ok("otp", "get", "CRIT1.SECURE_BOOT_ENABLE")
            assert re.search(r"SECURE_BOOT_ENABLE\b.*=\s*0\b", enable.out, re.DOTALL), enable


@pytest.mark.skipif(
    not ENABLE_SECURE_BOOT,
    reason="sets CRIT1.SECURE_BOOT_ENABLE, a permanent whole-chip change that "
    "also permanently disables the RISC-V cores - requires --run-otp AND "
    "PICOTOOL_TEST_ENABLE_SECURE_BOOT=1 (FPGA only, run in isolation - see "
    "module docstring)",
)
class TestSecureBootEnforcement:
    """Enables secure boot and exercises real enforcement, including rollback.

    A single test intentionally covers the whole story (provision -> verified
    boot -> tampered image rejected -> insufficient-rollback image rejected ->
    version bump -> previously-rejected image now boots): each of these steps
    depends on the previous one's OTP state, and CRIT1.SECURE_BOOT_ENABLE can
    only usefully be set once, so splitting this into independent tests would
    either re-provision redundantly or silently depend on execution order.
    """

    def test_secure_boot_and_rollback_enforcement(
        self, device_manager, connected_chips, selected_chips, require_binaries, tmp_path
    ):
        chip = "rp2350"
        if chip not in selected_chips:
            pytest.skip(f"{chip} not selected (--boards)")
        if chip not in connected_chips:
            pytest.skip(f"{chip} board not connected")
        board = Board(chip, device_manager)
        elf = require_binaries[chip].path("hello_usb.elf")
        key = _genkey(tmp_path / "key.pem")

        # rollback version 1: boots once version>=1 is provisioned.
        signed_v1 = tmp_path / "signed_v1.elf"
        otp_v1 = tmp_path / "otp_v1.json"
        assert device_manager.pt.run(
            "seal", "--sign", str(elf), str(signed_v1), str(key), str(otp_v1),
            "--rollback", "1",
        ).ok

        # rollback version 2, same key: only boots once version>=2 is set.
        signed_v2 = tmp_path / "signed_v2.elf"
        otp_v2 = tmp_path / "otp_v2.json"
        assert device_manager.pt.run(
            "seal", "--sign", str(elf), str(signed_v2), str(key), str(otp_v2),
            "--rollback", "2",
        ).ok

        # Same key -> same bootkey hash in both otp files; provisioning either
        # is equivalent, so only otp_v1.json needs loading.
        assert json.loads(otp_v1.read_text())["bootkey0"] == json.loads(otp_v2.read_text())["bootkey0"]

        # A same-key, tampered copy of v1 - signature must fail on this one.
        tampered_v1 = tmp_path / "tampered_v1.elf"
        _flip_byte_in_first_segment(signed_v1, tampered_v1)

        def boots(elf_path, timeout=20.0) -> bool:
            """Erase, load `elf_path`, reboot, and report whether it came up as
            a running (USB-visible) application."""
            dev = device_manager.ensure_bootsel(board)
            device_manager.pt.run("erase", "-a", *dev.selector, timeout=120)
            dev = device_manager.find_bootsel(chip)
            device_manager.pt.run("load", *dev.selector, str(elf_path), timeout=90)
            cur = device_manager.find_bootsel(chip)
            if cur:
                device_manager.pt.run("reboot", *cur.selector, timeout=device_manager.reboot_timeout)
            device_manager._wait(
                lambda: device_manager.find_bootsel(chip) is None,
                device_manager.reboot_timeout,
            )
            return device_manager.wait_app_visible(chip, timeout=timeout)

        def otp_cmd(*args):
            """Run an OTP command against the board while it's in BOOTSEL.

            Deliberately does NOT use board.bootsel(): that context manager's
            __exit__ calls ensure_app(), which - since an `otp` write doesn't
            reboot the device, so it's still in BOOTSEL on exit - would
            immediately reflash a PLAIN UNSIGNED app right after enabling
            secure boot, before this test ever gets to check anything. Every
            device interaction in this test goes through here or `boots()`
            instead, both bypassing that teardown entirely.
            """
            dev = device_manager.find_bootsel(chip) or device_manager.ensure_bootsel(board)
            return device_manager.pt.run(*args, *dev.selector, check=True)

        try:
            # --- irreversible step: burn the key and enable enforcement -----
            otp_cmd("otp", "load", str(otp_v1))
            # Provision the rollback counter to version 1 (thermometer:
            # bit 0 set = count 1). Raw + set-bits, per DEFAULT_BOOT_VERSION0's
            # own description ("thermometer counter... (RBIT-3)"), and #294 -
            # style set-bits-only writes so this never tries to clear a bit.
            otp_cmd("otp", "set", "DEFAULT_BOOT_VERSION0", "0x1", "-r", "-s")

            # --- positive: correctly signed, sufficient rollback -> boots ---
            assert boots(signed_v1), "correctly signed, sufficiently-versioned image failed to boot"

            # --- negative: tampered (bad signature) -> must NOT boot --------
            assert not boots(tampered_v1), "a tampered image booted - signature check did not reject it"

            # --- negative: valid signature, insufficient rollback -----------
            assert not boots(signed_v2), (
                "an image requiring rollback version 2 booted with only version 1 "
                "provisioned - rollback protection did not reject it"
            )

            # --- bump the counter to version 2 (add the 2nd bit) ------------
            otp_cmd("otp", "set", "DEFAULT_BOOT_VERSION0", "0x3", "-r", "-s")

            # --- the previously-rejected image now boots --------------------
            assert boots(signed_v2), (
                "image requiring rollback version 2 still failed to boot after "
                "the OTP counter was bumped to version 2"
            )
        finally:
            # Best-effort: leave the board on the last known-good SIGNED image.
            # There is no "restore to unsigned" after this test - see the
            # module docstring.
            boots(signed_v2)
