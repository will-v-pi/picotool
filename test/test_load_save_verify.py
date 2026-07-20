"""Flash data-path tests: load / verify / save / erase on real hardware.

Runs against every connected & selected board (RP2040 + RP2350). Each test
enters BOOTSEL, drives picotool with an explicit --bus/--address selector, and
the `board` fixture restores a USB application afterwards.
"""
import pytest

from conftest import FLASH_SIZE

pytestmark = pytest.mark.hardware


class TestLoadVerify:
    def test_load_uf2_then_verify(self, board, fw):
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("verify", str(fw.path("blink.uf2")))
            assert r.ok, r

    def test_load_elf_then_verify(self, board, fw):
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.elf")))
            r = dev.run("verify", str(fw.path("blink.elf")))
            assert r.ok, r

    def test_verify_detects_mismatch(self, board, fw):
        """After loading blink, verifying a different program must fail."""
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("verify", str(fw.path("hello_usb.uf2")))
            assert not r.ok
            assert "did not match" in r.out

    def test_reload_replaces_program(self, board, fw):
        """Loading a second program then verifying the first must fail."""
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            dev.ok("load", str(fw.path("hello_usb.uf2")))
            assert dev.run("verify", str(fw.path("hello_usb.uf2"))).ok
            assert not dev.run("verify", str(fw.path("blink.uf2"))).ok


class TestSave:
    def test_save_program(self, board, fw, tmp_path):
        out = tmp_path / "prog.bin"
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("save", "-p", str(out))
            assert r.ok, r
        assert out.exists() and out.stat().st_size > 0

    def test_save_range(self, board, fw, tmp_path):
        out = tmp_path / "range.bin"
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("save", "-r", "0x10000000", "0x10001000", str(out))
            assert r.ok, r
        assert out.stat().st_size == 0x1000

    @pytest.mark.slow
    def test_save_all_is_full_flash(self, board, fw, tmp_path):
        out = tmp_path / "all.bin"
        with board.bootsel() as dev:
            r = dev.run("save", "-a", str(out), timeout=120)
            assert r.ok, r
        assert out.stat().st_size == FLASH_SIZE[board.chip]

    def test_save_reload_roundtrip(self, board, fw, tmp_path):
        """Save a loaded program, erase, reload the saved image, verify."""
        saved = tmp_path / "saved.bin"
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            dev.ok("save", "-p", str(saved))
            # Reload the saved raw image at the flash base and re-verify.
            dev.ok("load", str(saved), "-t", "bin", "-o", "0x10000000")
            assert dev.run("verify", str(fw.path("blink.uf2"))).ok

    def test_save_verify_flag(self, board, fw, tmp_path):
        """Regression for #113: `save -v` verifies the saved data."""
        out = tmp_path / "prog.bin"
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("save", "-v", "-p", str(out))
            assert r.ok, r
        assert out.exists() and out.stat().st_size > 0

    def test_save_range_uf2_is_loadable(self, board, fw, tmp_path):
        """Regression for #24: a range saved to UF2 must be a valid, loadable
        image (the bug produced an oversized UF2 that failed to load)."""
        saved = tmp_path / "range.uf2"
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            dev.ok("save", "-r", "0x10000000", "0x10010000", str(saved))
            # Round-trip: erase, reload the saved UF2, and re-verify blink.
            dev.ok("erase", "-a", timeout=120)
            dev.ok("load", str(saved))
            assert dev.run("verify", str(fw.path("blink.uf2"))).ok


class TestErase:
    def test_erase_all(self, board, fw):
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            assert dev.run("verify", str(fw.path("blink.uf2"))).ok
            r = dev.run("erase", "-a", timeout=120)
            assert r.ok, r
            # After a full erase the program no longer verifies.
            assert not dev.run("verify", str(fw.path("blink.uf2"))).ok

    def test_erase_range(self, board, fw):
        with board.bootsel() as dev:
            dev.ok("load", str(fw.path("blink.uf2")))
            r = dev.run("erase", "-r", "0x10000000", "0x10001000")
            assert r.ok, r
            assert not dev.run("verify", str(fw.path("blink.uf2"))).ok
