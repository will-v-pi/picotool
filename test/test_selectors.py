"""Selecting a device with picotool selectors other than --bus/--address.

- `--ser <serial>`: the serial is the flash id, which `picotool info --debug`
  reports; picotool matches a device by it. Exercised against a board in
  BOOTSEL while the other board is also attached, so it also checks --ser
  disambiguates between the two.
- `--vid`/`--pid`: picotool can target a *running* device by a custom USB
  vid/pid, as long as it exposes the RPI reset interface. dev_multi_cdc
  (pico-examples) advertises 0xcafe/0x4102 and that interface, so we flash it,
  let it run, then reboot it to BOOTSEL selected purely by vid/pid.
"""
import re
import subprocess

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.slow]

# dev_multi_cdc's descriptors: CDC_EXAMPLE_VID / CDC_EXAMPLE_PID (0x4100 | CDC
# count of 2). See pico-examples usb/device/dev_multi_cdc/usb_descriptors.c.
CUSTOM_VID = "0xcafe"
CUSTOM_PID = "0x4102"


def _serial(dev) -> str:
    """The board's USB serial, read from `info --debug`: the flash id on RP2040,
    the chipid on RP2350. picotool's --ser match is case-sensitive and wants the
    upper-case form (RP2350 prints its chipid lower-case, so normalise here)."""
    r = dev.run("info", "--debug")
    assert r.ok, r
    m = re.search(r"(?:flash id|chipid):\s*0x([0-9A-Fa-f]+)", r.out)
    assert m, f"no serial (flash id / chipid) in info --debug output:\n{r.out}"
    return m.group(1).upper()


def test_ser_selects_board(board):
    """`--ser <flash id>` targets the board with no --bus/--address (and
    disambiguates it from the other attached board)."""
    with board.bootsel() as dev:
        serial = _serial(dev)
        r = board.pt.run("info", "-a", "--ser", serial)
        assert r.ok, r
        assert board.chip.upper() in r.out, r


def test_ser_load_verify(board, fw):
    """load then verify, selected only by `--ser`."""
    uf2 = str(fw.path("blink.uf2"))
    with board.bootsel() as dev:
        serial = _serial(dev)
        assert board.pt.run("load", "--ser", serial, uf2, timeout=90).ok
        r = board.pt.run("verify", "--ser", serial, uf2, timeout=90)
        assert r.ok, r


def _custom_present() -> bool:
    return (
        subprocess.run(
            ["lsusb", "-d", f"{CUSTOM_VID[2:]}:{CUSTOM_PID[2:]}"],
            capture_output=True,
        ).returncode
        == 0
    )


def test_vidpid_selects_running_device(board, fw, device_manager):
    """picotool selects a *running* device by a custom vid/pid (no
    --bus/--address) and reboots it to BOOTSEL."""
    dm = device_manager
    uf2 = str(fw.path("dev_multi_cdc.uf2"))

    # Flash dev_multi_cdc and let it run - it comes up as 0xcafe/0x4102.
    dev = dm.ensure_bootsel(board)
    dm.pt.ok("load", *dev.selector, uf2, timeout=90)
    dm.pt.ok("reboot", *dev.selector, timeout=dm.reboot_timeout)
    if not dm._wait(_custom_present, dm.reboot_timeout):
        pytest.skip("dev_multi_cdc did not enumerate with its custom vid/pid")

    # Select it purely by vid/pid and reboot it to BOOTSEL.
    r = dm.pt.run("reboot", "-u", "--vid", CUSTOM_VID, "--pid", CUSTOM_PID, "-f",
                  timeout=dm.reboot_timeout)
    if not r.ok and ("unable to connect" in r.out or "permission" in r.out.lower()):
        pytest.skip(
            "custom-vid device not accessible - needs a udev rule granting the "
            f"{CUSTOM_VID} vid (the CI workflow installs one)"
        )
    assert r.ok, r
    assert dm._wait(lambda: dm.find_bootsel(board.chip), dm.bootsel_timeout), \
        "device selected by vid/pid did not enter BOOTSEL"
    # board fixture teardown restores a normal app.
