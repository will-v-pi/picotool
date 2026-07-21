#!/usr/bin/env python3
"""CI cleanup: leave every selected board on a known-good, USB-visible app,
and - critically - never in BOOTSEL mode. Run from within test/ (it imports
lib.* relative to cwd).

Used by .github/workflows/hardware-tests.yml as an `if: always()` step, so a
test that left a board on a partition table, BOOTSEL, or other non-default
state doesn't affect the next run.
"""
import sys
import time

sys.path.insert(0, ".")

from lib.binaries import BinarySet
from lib.devices import Board, DeviceManager
from lib.picotool import Picotool

RETRIES = 3
RETRY_DELAY = 2.0


def restore_chip(dm: DeviceManager, chip: str) -> bool:
    """Try hard to get `chip` out of BOOTSEL and onto a known-good app.

    Returns True once the board is confirmed not in BOOTSEL - the one
    property that matters for the runner - even if earlier attempts raised.
    """
    for attempt in range(1, RETRIES + 1):
        try:
            dm.ensure_app(Board(chip, dm), reflash=True)
        except Exception as e:
            print(f"{chip}: attempt {attempt}/{RETRIES} failed: {e}")
        if dm.find_bootsel(chip) is None:
            print(f"{chip}: restored (not in BOOTSEL)")
            return True
        time.sleep(RETRY_DELAY)
    return False


def main():
    picotool_path = sys.argv[1] if len(sys.argv) > 1 else "../install/picotool/picotool"
    chips = sys.argv[2:] or ["rp2040", "rp2350"]

    dm = DeviceManager(Picotool(picotool_path), {c: BinarySet(c) for c in ("rp2040", "rp2350")})
    all_ok = True
    for chip in chips:
        if not restore_chip(dm, chip):
            print(
                f"ERROR: {chip} is still in BOOTSEL after {RETRIES} attempts"
            )
            all_ok = False
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
