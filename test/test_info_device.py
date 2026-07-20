"""`picotool info` / `config` against a live device.

These are regression tests for a bug that existed in earlier develop builds
(around picotool 2.2.1-develop): with two RP-series devices attached (the normal
state of this test rig) and one in BOOTSEL, `picotool info` misbehaved -

  * `info -a` (unfiltered) crashed in info_command::execute (SIGSEGV) or exited
    silently with no output, and
  * a targeted `info` on an RP2040 in BOOTSEL printed nothing, even though the
    same device served save/load/verify correctly.

It was fixed on master/develop (see "fix `picotool info` for non-partition-
capable devices", #338). The tests assert the correct behaviour so the fix
stays in place.
"""
import pytest

pytestmark = pytest.mark.hardware


def test_info_reports_program(board, fw):
    with board.bootsel() as dev:
        dev.ok("load", str(fw.path("hello_anything.uf2")))
        r = dev.run("info", "-a")
        assert r.ok, r
        assert "Program Information" in r.out
        assert "hello_anything" in r.out


def test_info_basic_reports_chip(board, fw):
    with board.bootsel() as dev:
        dev.ok("load", str(fw.path("hello_usb.uf2")))
        r = dev.run("info")
        assert r.ok and r.out.strip(), r


def test_config_reads_device(board, fw):
    with board.bootsel() as dev:
        dev.ok("load", str(fw.path("hello_anything.uf2")))
        r = dev.run("config")
        assert r.ok, r
        assert "text" in r.out


def test_info_a_unfiltered_with_bootsel(board, device_manager):
    """Regression: an unfiltered `info -a` must not crash when this board is in
    BOOTSEL while the other board is running an application."""
    with board.bootsel():
        r = device_manager.pt.run("info", "-a", timeout=20)
        assert r.ok, r
        assert not r.timed_out
