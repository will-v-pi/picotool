"""pytest configuration and fixtures for the picotool test suite."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from lib.binaries import BinarySet, BINARIES_ROOT
from lib.devices import (
    BOARD_CONFIGS,
    Board,
    DeviceManager,
    bootsel_devices,
)
from lib.picotool import Picotool

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

ALL_CHIPS = list(BOARD_CONFIGS.keys())  # ["rp2040", "rp2350"]


# --------------------------------------------------------------------------
# Command line options
# --------------------------------------------------------------------------
def pytest_addoption(parser):
    g = parser.getgroup("picotool")
    g.addoption(
        "--picotool",
        default=os.environ.get("PICOTOOL", str(REPO_ROOT / "build" / "picotool")),
        help="path to the picotool binary under test",
    )
    g.addoption(
        "--openocd",
        default=os.environ.get("OPENOCD", "openocd"),
        help="path to the openocd binary (debug-probe recovery)",
    )
    g.addoption(
        "--no-openocd",
        action="store_true",
        help="disable the OpenOCD/debug-probe recovery path",
    )
    g.addoption(
        "--boards",
        default=os.environ.get("PICOTOOL_TEST_BOARDS", ",".join(ALL_CHIPS)),
        help="comma-separated chips to test (rp2040,rp2350)",
    )
    g.addoption(
        "--run-otp",
        action="store_true",
        help="run OTP tests that WRITE to a device. OTP is one-time-programmable "
        "- only enable this against an FPGA, never a real chip.",
    )
    g.addoption(
        "--require-boards",
        action="store_true",
        help="fail the whole run immediately if any selected board (--boards) "
        "isn't connected, instead of silently skipping its tests. Useful in CI "
        "to catch a disconnected/dead board rather than getting a suspiciously "
        "short, all-green run.",
    )


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------
def pytest_configure(config):
    for name, desc in [
        ("hardware", "test requires a connected board"),
        ("rp2040", "test applies to RP2040"),
        ("rp2350", "test applies to RP2350"),
        ("otp", "test touches OTP; device variants need --run-otp (FPGA only)"),
        ("slow", "slow test (reflashes / long transfers)"),
    ]:
        config.addinivalue_line("markers", f"{name}: {desc}")


def pytest_collection_modifyitems(config, items):
    run_otp = config.getoption("--run-otp")
    skip_otp = pytest.mark.skip(
        reason="OTP device test skipped; pass --run-otp (FPGA only) to enable"
    )
    for item in items:
        # Skip OTP *device* tests unless explicitly enabled. OTP tests that only
        # touch files opt out of the gate with @pytest.mark.otp(device=False)...
        # here we gate any otp-marked test that also needs a board.
        if "otp" in item.keywords and "board" in getattr(item, "fixturenames", []):
            if not run_otp:
                item.add_marker(skip_otp)


# --------------------------------------------------------------------------
# Session-scoped fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def picotool(request) -> Picotool:
    exe = request.config.getoption("--picotool")
    if not (os.path.isabs(exe) and os.path.exists(exe)) and shutil.which(exe) is None:
        if not os.path.exists(exe):
            pytest.exit(f"picotool binary not found: {exe}", returncode=2)
    return Picotool(exe)


@pytest.fixture(scope="session")
def binaries() -> dict[str, BinarySet]:
    sets = {chip: BinarySet(chip) for chip in ALL_CHIPS}
    return sets


@pytest.fixture(scope="session")
def require_binaries(binaries):
    """Skip if the firmware binaries have not been built."""
    missing = [c for c, b in binaries.items() if not b.available()]
    if missing:
        pytest.skip(
            f"no test binaries for {missing} under {BINARIES_ROOT}; "
            "run test/build_binaries.sh"
        )
    return binaries


@pytest.fixture(scope="session")
def device_manager(request, picotool, binaries) -> DeviceManager:
    return DeviceManager(
        picotool,
        binaries,
        openocd=request.config.getoption("--openocd"),
        use_openocd=not request.config.getoption("--no-openocd"),
    )


@pytest.fixture(scope="session")
def selected_chips(request) -> list[str]:
    raw = request.config.getoption("--boards")
    chips = [c.strip() for c in raw.split(",") if c.strip()]
    bad = [c for c in chips if c not in ALL_CHIPS]
    if bad:
        pytest.exit(f"unknown chips in --boards: {bad}", returncode=2)
    return chips


@pytest.fixture(scope="session")
def connected_chips(request, device_manager, selected_chips) -> list[str]:
    """Chips that are actually reachable over USB right now.

    Recovers any board left in a bad state (BOOTSEL loop / empty flash) first,
    then retries discovery a few times to ride out re-enumeration. With
    --require-boards, any selected chip that's still missing aborts the whole
    run instead of leaving its tests to skip individually.
    """
    import time

    from lib.devices import Board

    dm = device_manager
    present: set[str] = set()
    for attempt in range(4):
        dm.ensure_no_bootsel()
        res = dm.pt.run("info", "-a", timeout=30)
        for m in re.finditer(r"(RP2040|RP2350) device", res.out):
            present.add(m.group(1).lower())
        for chip, _dev in bootsel_devices():
            present.add(chip)
        if all(c in present for c in selected_chips):
            break
        time.sleep(1.0)

    # A board left running third-party firmware (MicroPython / CircuitPython)
    # reports only as an "RP-series device" (no chip), so it is not detected
    # above. If a selected chip is still missing, recover it via the debug probe
    # by re-flashing a known application, then re-check.
    missing = [c for c in selected_chips if c not in present]
    if missing and dm.use_openocd:
        for chip in missing:
            try:
                dm.flash_app(Board(chip, dm))
                if dm.wait_app_visible(chip):
                    present.add(chip)
            except Exception as e:  # pragma: no cover - best-effort recovery
                print(f"warning: could not recover {chip}: {e}")

    still_missing = [c for c in selected_chips if c not in present]
    if still_missing and request.config.getoption("--require-boards"):
        pytest.exit(
            f"--require-boards: not connected: {still_missing} "
            f"(connected: {sorted(present) or 'none'})",
            returncode=1,
        )

    return [c for c in selected_chips if c in present]


# --------------------------------------------------------------------------
# Per-test board fixture (parametrized over chips)
# --------------------------------------------------------------------------
@pytest.fixture(params=ALL_CHIPS)
def board(request, device_manager, connected_chips, selected_chips) -> Board:
    chip = request.param
    if chip not in selected_chips:
        pytest.skip(f"{chip} not selected (--boards)")
    if chip not in connected_chips:
        pytest.skip(f"{chip} board not connected")
    b = Board(chip, device_manager)
    yield b
    # Teardown: always leave the board running an application.
    try:
        device_manager.ensure_app(b)
    except Exception as e:  # pragma: no cover - best-effort cleanup
        print(f"warning: could not restore {chip} to app mode: {e}")


@pytest.fixture
def rp2350_board(board) -> Board:
    """A board fixture that only yields for RP2350 (skips RP2040)."""
    if not board.is_rp2350:
        pytest.skip("RP2350-only test")
    return board


@pytest.fixture
def fw(board, require_binaries):
    """The firmware BinarySet for the board currently under test."""
    return require_binaries[board.chip]


# Expected flash sizes (bytes) for the boards under test.
FLASH_SIZE = {"rp2040": 2 * 1024 * 1024, "rp2350": 4 * 1024 * 1024}
