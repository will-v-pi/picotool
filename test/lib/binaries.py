"""Locate the firmware binaries built by build_binaries.sh."""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BINARIES_ROOT = Path(os.environ.get("PICOTOOL_TEST_BINARIES", HERE.parent / "binaries"))


def universal_binary(stem: str) -> Path | None:
    """A downloaded multi-family "universal" binary, or None if not fetched."""
    p = BINARIES_ROOT / "universal" / "firmware" / f"{stem}.uf2"
    return p if p.exists() else None


class BinarySet:
    """Firmware binaries available for one chip (rp2040 / rp2350)."""

    def __init__(self, chip: str):
        self.chip = chip
        self.root = BINARIES_ROOT / chip

    def available(self) -> bool:
        return self.root.is_dir() and any(self.root.glob("*.elf"))

    def path(self, name: str) -> Path:
        """Return <name> under this chip's binary dir, asserting it exists.

        `name` may be a bare stem+extension like "blink.elf".
        """
        p = self.root / name
        if not p.exists():
            raise FileNotFoundError(f"missing test binary: {p}")
        return p

    def get(self, stem: str, ext: str) -> Path | None:
        """Return <stem>.<ext> if present, else None."""
        p = self.root / f"{stem}.{ext}"
        return p if p.exists() else None

    def stems(self) -> list[str]:
        """All program stems that have at least an ELF."""
        return sorted(p.stem for p in self.root.glob("*.elf"))

    @property
    def enter_bootsel_elf(self) -> Path | None:
        p = self.root / "tools" / "enter_bootsel.elf"
        return p if p.exists() else None

    @property
    def enter_bootsel_ram_elf(self) -> Path | None:
        """RAM-only enter_bootsel, for BOOTSEL entry that preserves flash."""
        p = self.root / "tools" / "enter_bootsel_ram.elf"
        return p if p.exists() else None

    def tool(self, stem: str, ext: str = "uf2") -> Path | None:
        """A helper firmware from tools/ (e.g. bi_bdev), or None if not built."""
        p = self.root / "tools" / f"{stem}.{ext}"
        return p if p.exists() else None

    def firmware(self, stem: str, ext: str = "uf2") -> Path | None:
        """A downloaded third-party firmware (micropython / circuitpython)."""
        p = self.root / "firmware" / f"{stem}.{ext}"
        return p if p.exists() else None

    # Convenience accessors for the well-known programs. Each returns the path
    # or raises if the expected binary was not built.
    def blink(self, ext: str = "elf") -> Path:
        return self.path(f"blink.{ext}")

    def hello_usb(self, ext: str = "elf") -> Path:
        return self.path(f"hello_usb.{ext}")

    def hello_anything(self, ext: str = "elf") -> Path:
        return self.path(f"hello_anything.{ext}")
