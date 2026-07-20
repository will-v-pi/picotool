"""`picotool reboot` variants on real hardware."""
import pytest

pytestmark = pytest.mark.hardware


def test_reboot_app_into_bootsel(board):
    """A running application can be forced into BOOTSEL over USB.

    Occasionally a single `reboot -u -f` does not take (the app is still coming
    up), so retry a couple of times as real usage would.
    """
    dev = None
    for attempt in range(3):
        sel = board.app_selector()
        r = board.pt.run(
            "reboot", "-u", "-f", *sel, timeout=board.manager.reboot_timeout
        )
        assert r.ok, r
        dev = board.manager._wait(
            lambda: board.manager.find_bootsel(board.chip),
            board.manager.bootsel_timeout,
        )
        if dev is not None:
            break
    assert dev is not None, "board did not appear in BOOTSEL after reboot -u -f"


def test_reboot_bootsel_into_application(board, fw):
    """A device in BOOTSEL reboots back into the flashed application."""
    with board.bootsel() as dev:
        dev.ok("load", str(fw.path("hello_usb.uf2")))
        r = dev.run("reboot")
        assert r.ok, r
        gone = board.manager._wait(
            lambda: board.manager.find_bootsel(board.chip) is None,
            board.manager.reboot_timeout,
        )
        assert gone, "board stayed in BOOTSEL after reboot"
    # The reflashed hello_usb should now be visible on USB (allow enumeration).
    assert board.manager.wait_app_visible(board.chip)
