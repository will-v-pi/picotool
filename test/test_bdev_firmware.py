"""`picotool bdev` against MicroPython / CircuitPython embedded drives.

MicroPython and CircuitPython expose a filesystem in flash, declared via binary
info, once they have booted. This exercises picotool's bdev commands against
those real firmwares on both RP2040 and RP2350.

Neither firmware honours picotool's `-f` reset interface, so the harness uses
the debug probe (OpenOCD) to re-enter BOOTSEL *without erasing flash* (running a
RAM-only enter_bootsel) after letting the firmware boot and create its drive.
These tests therefore require OpenOCD and the downloaded firmware, and are
skipped otherwise.
"""
import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


@pytest.fixture
def need_openocd(device_manager):
    if not device_manager.use_openocd:
        pytest.skip("firmware bdev tests need the debug probe (OpenOCD) to re-enter BOOTSEL")


def _boot_firmware(device_manager, board, fw, name, boot_wait=12.0):
    uf2 = fw.firmware(name)
    if uf2 is None:
        pytest.skip(f"{name} firmware not downloaded - run fetch_firmware.sh")
    return device_manager.boot_firmware_then_bootsel(board, uf2, boot_wait=boot_wait)


def test_micropython_embedded_drive(board, device_manager, fw, need_openocd, tmp_path):
    dev = _boot_firmware(device_manager, board, fw, "micropython")
    ls = dev.ok("bdev", "ls")
    assert "MicroPython" in ls.out  # picotool names the embedded drive

    # Round-trip a file through MicroPython's (littlefs) filesystem.
    src = tmp_path / "hello_mp.py"
    src.write_text("print('hello from picotool')\n")
    dev.ok("bdev", "cp", str(src), ":/")
    assert "hello_mp.py" in dev.ok("bdev", "ls").out
    assert "hello from picotool" in dev.ok("bdev", "cat", "hello_mp.py").out


def test_circuitpython_embedded_drive(board, device_manager, fw, need_openocd):
    dev = _boot_firmware(device_manager, board, fw, "circuitpython", boot_wait=18.0)
    ls = dev.ok("bdev", "ls")
    # CircuitPython creates boot_out.txt on its first boot.
    assert "boot_out.txt" in ls.out
    cat = dev.ok("bdev", "cat", "boot_out.txt")
    assert "CircuitPython" in cat.out
