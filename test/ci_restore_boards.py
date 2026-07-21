#!/usr/bin/env python3
"""Best-effort CI cleanup: leave every selected board on a known-good,
USB-visible app. Run from within test/ (it imports lib.* relative to cwd).

Used by .github/workflows/hardware-tests.yml as an `if: always()` step, so a
test that left a board on a partition table or other non-default state
doesn't affect the next run (or the next person picking up a board).
"""
import sys

sys.path.insert(0, ".")

from lib.binaries import BinarySet
from lib.devices import Board, DeviceManager
from lib.picotool import Picotool


def main():
    picotool_path = sys.argv[1] if len(sys.argv) > 1 else "../build/picotool"
    chips = sys.argv[2:] or ["rp2040", "rp2350"]

    dm = DeviceManager(Picotool(picotool_path), {c: BinarySet(c) for c in ("rp2040", "rp2350")})
    for chip in chips:
        try:
            dm.ensure_app(Board(chip, dm), reflash=True)
            print(f"{chip}: restored")
        except Exception as e:  # best-effort - never fail the CI run over this
            print(f"warning: could not restore {chip}: {e}")


if __name__ == "__main__":
    main()
