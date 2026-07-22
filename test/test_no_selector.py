"""picotool commands driven with NO --bus/--address selector.

With two boards on the rig, picotool needs a single candidate device when it's
given no selector. Each test here puts the target chip into BOOTSEL and drops
every *other* connected board off the USB bus (device_manager.usb_disconnected,
which runs the RAM usb_disconnect helper over SWD), then exercises picotool
without a selector - checking it auto-targets the one remaining board.

The disconnect is done through the debug probe, so these skip under
--no-openocd.
"""
import contextlib

import pytest

from lib.devices import Board

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


@pytest.fixture
def solo(board, device_manager, connected_chips):
    """`board` in BOOTSEL as the sole candidate: every other connected board is
    dropped off USB for the duration of the test, then brought back."""
    dm = device_manager
    if not dm.use_openocd:
        pytest.skip("no-selector isolation needs OpenOCD to disconnect the other board")
    others = [c for c in connected_chips if c != board.chip]
    with contextlib.ExitStack() as stack:
        for chip in others:
            stack.enter_context(dm.usb_disconnected(Board(chip, dm)))
        dm.ensure_bootsel(board)
        yield board


def test_info_no_selector(solo):
    """`picotool info` with no selector targets the one available board."""
    r = solo.pt.run("info")
    assert r.ok, r
    # Plain `info` on a BOOTSEL device prints Program Information (it doesn't
    # print the chip type for RP2040), so just confirm it read a single device.
    assert "Program Information" in r.out, r


def test_info_all_no_selector_reports_chip(solo):
    """`picotool info -a` with no selector identifies the one available board."""
    r = solo.pt.run("info", "-a")
    assert r.ok, r
    assert solo.chip.upper() in r.out, r


def test_config_no_selector(solo):
    """`picotool config` with no selector reads the one available board."""
    r = solo.pt.run("config")
    assert r.ok, r


def test_load_verify_no_selector(solo, fw):
    """load then verify - both with no selector - against the one available
    board, exercising the write path's single-device auto-targeting too."""
    uf2 = str(fw.path("blink.uf2"))
    assert solo.pt.run("load", uf2, timeout=90).ok
    r = solo.pt.run("verify", uf2, timeout=90)
    assert r.ok, r
