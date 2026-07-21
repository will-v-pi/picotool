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

TestSecureBootEnforcement has been run successfully end-to-end against a real
RP2350 FPGA (2026-07-20): first boot of a rollback-versioned signed image
succeeds, a tampered copy is rejected (signature), an older-versioned image is
rejected once a newer one has run (rollback - confirmed via the "OTP version
applied" diagnostic being absent on rejection), and a newer version always
succeeds and bumps the bootrom's own counter. Two things learned in the
process that shaped this test:

* Rollback protection is managed by the BOOTROM itself, not the provisioner -
  there is no "pre-provision the required minimum version" step; the bootrom
  compares an image's embedded version against whatever it last recorded and
  updates that record itself as it boots newer images. (An earlier version of
  this test wrongly tried to pre-set the OTP counter via `otp set` - that was
  removed; see `boots()`'s structure below for the corrected flow.)
* Signature/rollback verification took roughly 2-3 minutes per boot on the
  FPGA used to validate this (crypto emulation is far slower than real
  silicon's hardware accelerator) - `boots()`'s timeout is generously sized
  for that; expect a full run of this test to take ~10-15 minutes.
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

@pytest.mark.skipif(
    ENABLE_SECURE_BOOT,
    reason="TestSecureBootEnforcement used instead of TestProvisionBootKey when ENABLE_SECURE_BOOT=1",
)
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
        """
        Rollback protection is managed by the BOOTROM itself, not the
        provisioner: it does NOT work by pre-setting a required minimum
        version in OTP ahead of time. Instead, on every boot of a
        rollback-versioned image, the bootrom compares the image's embedded
        version against whatever it last recorded in OTP - an OLDER image is
        rejected, but a NEWER one is always accepted, and the bootrom bumps
        the OTP counter to match as it boots it. (An earlier version of this
        test wrongly modelled it as something the test needed to pre-provision
        via `otp set` - manually touching the counter isn't part of the normal
        flow at all and was removed.)

        So the meaningful sequence is: boot a version, THEN show an older
        version is rejected, while a newer one still isn't.
        """
        chip = "rp2350"
        if chip not in selected_chips:
            pytest.skip(f"{chip} not selected (--boards)")
        if chip not in connected_chips:
            pytest.skip(f"{chip} board not connected")
        board = Board(chip, device_manager)
        elf = require_binaries[chip].path("hello_usb.elf")
        key = _genkey(tmp_path / "key.pem")

        def seal(version, name):
            out = tmp_path / f"signed_{name}.elf"
            otp = tmp_path / f"otp_{name}.json"
            if version is not None:
                assert device_manager.pt.run(
                    "seal", "--sign", str(elf), str(out), str(key), str(otp),
                    "--rollback", str(version),
                ).ok
            else:
                assert device_manager.pt.run(
                    "seal", "--sign", str(elf), str(out), str(key), str(otp),
                ).ok
            return out, otp

        signed_nv, _ = seal(None, "nv")  # unversioned - must be rejected once versioned has run
        signed_v1, otp_v1 = seal(1, "v1")  # older - must be rejected once v2 has run
        signed_v2, otp_v2 = seal(2, "v2")  # first boot - always allowed
        signed_v3, _ = seal(3, "v3")  # newer - always allowed, bumps the counter

        # Same key -> same bootkey hash in every otp file; provisioning any one
        # of them is equivalent, so only otp_v1.json needs loading.
        assert json.loads(otp_v1.read_text())["bootkey0"] == json.loads(otp_v2.read_text())["bootkey0"]

        # A same-key, tampered copy of v2 - signature must fail on this one,
        # independently of rollback version.
        tampered_v2 = tmp_path / "tampered_v2.elf"
        _flip_byte_in_first_segment(signed_v2, tampered_v2)

        def boots(elf_path, timeout=120.0) -> bool:
            """Erase, load `elf_path`, reboot, and report whether it came up as
            a running (USB-visible) application.

            `timeout` covers BOTH "wait for BOOTSEL to disappear" and "wait to
            become app-visible" - secure-boot signature/rollback verification
            can take much longer than a normal boot (observed: over 20s, at
            least on the first verified boot after enabling secure boot on an
            FPGA), and DeviceManager.reboot_timeout (used elsewhere for plain
            reboots) is tuned for ordinary reboots, not this. Giving each phase
            the full `timeout` independently means a device that's simply slow
            to leave BOOTSEL doesn't eat into the budget for becoming visible.
            """
            dev = device_manager.ensure_bootsel(board)
            device_manager.pt.run("erase", "-a", *dev.selector, timeout=120)
            # Re-enter if the device dropped off after erase, so dev is never
            # None here (ensure_bootsel returns a live device or raises).
            dev = device_manager.find_bootsel(chip) or device_manager.ensure_bootsel(board)
            device_manager.pt.run("load", *dev.selector, str(elf_path), timeout=90)
            cur = device_manager.find_bootsel(chip)
            if cur:
                device_manager.pt.run("reboot", *cur.selector, timeout=timeout)
            device_manager._wait(
                lambda: device_manager.find_bootsel(chip) is None,
                timeout,
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

            # --- first-ever boot of a rollback-versioned image: always OK ---
            # The bootrom records version 2 in OTP as it boots this.
            assert boots(signed_v2), "correctly signed image failed to boot on its first (only) attempt"

            # --- negative: tampered (bad signature) -> must NOT boot --------
            assert not boots(tampered_v2), "a tampered image booted - signature check did not reject it"

            # --- negative: OLDER than what's recorded -> must NOT boot ------
            assert not boots(signed_v1), (
                "an older-versioned image booted after a newer one had already "
                "run - rollback protection did not reject it"
            )

            # --- positive: NEWER is always allowed, bumps the counter -------
            assert boots(signed_v3), "a newer-versioned image failed to boot"

            # --- negative: OLDER than what's recorded -> must NOT boot ------
            assert not boots(signed_v2), (
                "an older-versioned image booted after a newer one had already "
                "run - rollback protection did not reject it"
            )

            # --- negative: tampered (bad signature) -> must NOT boot --------
            assert not boots(signed_nv), (
                "an unversioned image booted after a versioned one had already "
                "run - rollback protection did not reject it"
            )
        finally:
            # Best-effort: leave the board on the last known-good SIGNED image.
            # There is no "restore to unsigned" after this test - see the
            # module docstring.
            boots(signed_v3)
