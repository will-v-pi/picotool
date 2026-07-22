"""Discovery and state management for the RP-series boards under test.

The harness talks to two boards - an RP2040 (Raspberry Pi Pico) and an RP2350
(Raspberry Pi Pico 2) - each of which has BOTH its native USB port and a debug
probe connected to the host. picotool drives the boards over USB; the debug
probes (via OpenOCD) are used as a guaranteed recovery / BOOTSEL-entry path.

Design notes
------------
* Boards are identified by *chip* (rp2040 / rp2350), never by a cached USB
  address - addresses change every time a board re-enumerates.
* USB enumeration is done with `lsusb`, which gives bus / address / product-id
  without ever poking the devices.  BOOTSEL devices are identified purely by
  product id (0x0003 = RP2040, 0x000f = RP2350).
* Discovery is done entirely from `lsusb`, by USB product id: BOOTSEL boards
  via BOOTSEL_PIDS, running-app boards via APP_PIDS (the SDK's stdio PIDs,
  which are distinct per chip).
"""
from __future__ import annotations

import os
import contextlib
import re
import subprocess
import time
from dataclasses import dataclass

from .picotool import Picotool

VENDOR_ID = 0x2E8A
PROBE_PID = 0x000C
# product id -> chip, for devices in BOOTSEL mode
BOOTSEL_PIDS = {0x0003: "rp2040", 0x000F: "rp2350"}
# product id -> chip, for a board running the SDK's USB-stdio application
# (the Pico SDK CDC PIDs - see https://github.com/raspberrypi/usb-pid). These
# are what the suite's own example binaries enumerate as, and they're distinct
# per chip, so a running app can be mapped to its chip straight from lsusb
# without querying the device. Confirmed on the rig by BOOTSEL round-trip:
# 0x000a reboots to 0x0003 (RP2040), 0x0009 reboots to 0x000f (RP2350).
APP_PIDS = {0x000A: "rp2040", 0x0009: "rp2350"}

PROBE_CONFIG = {
    "rp2040": {"target": "target/rp2040.cfg", "multidrop": False},
    "rp2350": {"target": "target/rp2350.cfg", "multidrop": True},
}
# interface config passed to OpenOCD's `-f`; override for a non-CMSIS-DAP probe.
OPENOCD_INTERFACE = os.environ.get("PICOTOOL_TEST_OPENOCD_INTERFACE", "interface/cmsis-dap.cfg")


@dataclass(frozen=True)
class UsbDev:
    bus: int
    addr: int
    pid: int

    @property
    def selector(self) -> list[str]:
        return ["--bus", str(self.bus), "--address", str(self.addr)]


def lsusb_rp_devices() -> list[UsbDev]:
    """All RP-vendor USB devices currently enumerated (probes included)."""
    try:
        out = subprocess.run(
            ["lsusb", "-d", f"{VENDOR_ID:04x}:"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    devs = []
    for line in out.splitlines():
        m = re.match(
            rf"Bus (\d+) Device (\d+): ID {VENDOR_ID:04x}:([0-9a-fA-F]{{4}})", line
        )
        if m:
            devs.append(UsbDev(int(m.group(1)), int(m.group(2)), int(m.group(3), 16)))
    return devs


def bootsel_devices() -> list[tuple[str, UsbDev]]:
    """(chip, dev) for every device currently in BOOTSEL mode."""
    return [
        (BOOTSEL_PIDS[d.pid], d)
        for d in lsusb_rp_devices()
        if d.pid in BOOTSEL_PIDS
    ]


def list_probe_serials() -> list[str]:
    """Serial numbers of every attached debug probe (CMSIS-DAP, vid:pid 2e8a:000c).

    Uses `lsusb -v`, which doesn't require elevated permissions to read the
    serial-number string descriptor.
    """
    try:
        out = subprocess.run(
            ["lsusb", "-v", "-d", f"{VENDOR_ID:04x}:{PROBE_PID:04x}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    # One "iSerial" line appears per probe's device descriptor, in device order;
    # we only need the serial value itself (not bus/address).
    return re.findall(r"^\s*iSerial\s+\d+\s+(\S+)", out, re.MULTILINE)


def probe_targets_chip(
    openocd: str, interface: str, serial: str, chip: str, timeout: float = 15
) -> bool:
    """Whether the debug probe `serial` is wired to a board running `chip`.

    Passive/non-destructive: for both chips this only performs an SWD connect +
    target examination (`init`), never a reset - confirmed by hand to leave a
    running application undisturbed whichever probe it's pointed at, including
    "wrong" probe/chip combinations (which simply fail to connect).
    """
    cfg = PROBE_CONFIG[chip]
    cmd = [openocd, "-f", interface, "-c", f"adapter serial {serial}"]
    if cfg["multidrop"]:
        cmd += ["-c", "set SWD_MULTIDROP 1"]
    cmd += ["-f", cfg["target"], "-c", "init", "-c", "exit"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    return proc.returncode == 0


@dataclass
class BoardConfig:
    chip: str  # "rp2040" / "rp2350"
    pico_board: str  # "pico" / "pico2"
    bootsel_pid: int

    @property
    def openocd_target(self) -> str:
        return PROBE_CONFIG[self.chip]["target"]

    @property
    def multidrop(self) -> bool:
        return PROBE_CONFIG[self.chip]["multidrop"]


BOARD_CONFIGS = {
    "rp2040": BoardConfig("rp2040", "pico", 0x0003),
    "rp2350": BoardConfig("rp2350", "pico2", 0x000F),
}


class DeviceError(RuntimeError):
    pass


def _elf_entry(path) -> int:
    """Read the entry point (e_entry) from a little-endian ELF32 file."""
    with open(path, "rb") as f:
        data = f.read(28)
    if data[:4] != b"\x7fELF":
        raise DeviceError(f"not an ELF file: {path}")
    # ELF32: e_entry is a 4-byte word at offset 24.
    return int.from_bytes(data[24:28], "little")


class DeviceManager:
    """Owns picotool + OpenOCD and drives boards between app / BOOTSEL states."""

    def __init__(
        self,
        picotool: Picotool,
        binaries,  # dict[str, BinarySet]
        openocd: str = "openocd",
        use_openocd: bool = True,
        bootsel_timeout: float = 20.0,
        reboot_timeout: float = 20.0,
    ):
        self.pt = picotool
        self.binaries = binaries
        self._probe_serials: dict[str, str] | None = None
        self.openocd = openocd
        self.use_openocd = use_openocd
        self.bootsel_timeout = bootsel_timeout
        self.reboot_timeout = reboot_timeout

    # -- polling ---------------------------------------------------------
    @staticmethod
    def _wait(predicate, timeout: float, interval: float = 0.3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            val = predicate()
            if val:
                return val
            time.sleep(interval)
        return predicate()

    # -- enumeration -----------------------------------------------------
    def find_bootsel(self, chip: str) -> UsbDev | None:
        for c, dev in bootsel_devices():
            if c == chip:
                return dev
        return None

    def any_bootsel(self) -> bool:
        return bool(bootsel_devices())

    def app_selector(self, chip: str, retries: int = 5) -> list[str] | None:
        """USB selector for `chip` running an application, or None.

        Maps the running-app USB PID to a chip straight from `lsusb` (see
        APP_PIDS). Retries a few times because a board that has
        just re-enumerated (e.g. right after a teardown) can be transiently
        absent from the listing. Returns None for a board running a non-USB app
        (e.g. blink) or firmware with a non-SDK PID (MicroPython/CircuitPython);
        the caller (ensure_bootsel) then falls back to the debug probe.
        """
        for attempt in range(retries):
            for d in lsusb_rp_devices():
                if APP_PIDS.get(d.pid) == chip:
                    return d.selector
            if attempt < retries - 1:
                time.sleep(1.0)
        return None

    # -- state transitions ----------------------------------------------
    def ensure_no_bootsel(self):
        """Reboot any BOOTSEL devices back to application mode.

        A board whose flash is empty (or still holds enter_bootsel) reboots
        straight back into BOOTSEL; such boards are re-flashed with a known
        application so the enumeration settles.
        """
        for _attempt in range(3):
            devs = bootsel_devices()
            if not devs:
                return
            for _chip, dev in devs:
                self.pt.run("reboot", *dev.selector, timeout=self.reboot_timeout)
            self._wait(lambda: not self.any_bootsel(), self.reboot_timeout)
            if not self.any_bootsel():
                return
            # Still stuck in BOOTSEL - restore a real application.
            for chip, _dev in bootsel_devices():
                try:
                    self.flash_app(Board(chip, self))
                except DeviceError:
                    pass

    def ensure_bootsel(self, board: "Board") -> UsbDev:
        """Put `board` into BOOTSEL and return its current USB device."""
        dev = self.find_bootsel(board.chip)
        if dev:
            return dev

        # 1) reboot the running application into BOOTSEL over USB (primary path).
        for _attempt in range(3):
            sel = self.app_selector(board.chip)
            if not sel:
                break
            self.pt.run("reboot", "-u", "-f", *sel, timeout=self.reboot_timeout)
            dev = self._wait(
                lambda: self.find_bootsel(board.chip), self.bootsel_timeout
            )
            if dev:
                return dev

        # 2) fall back to the debug probe: flash the enter_bootsel helper.
        if self.use_openocd:
            try:
                self.openocd_enter_bootsel(board)
                dev = self._wait(
                    lambda: self.find_bootsel(board.chip), self.bootsel_timeout
                )
                if dev:
                    return dev
            except DeviceError:
                pass

        raise DeviceError(f"could not put {board.chip} into BOOTSEL mode")

    def app_visible(self, chip: str) -> bool:
        """Whether `chip` is enumerated as a running USB application right now.

        Reads it from lsusb by the SDK stdio PID (see APP_PIDS) - the same
        source as app_selector. A board running a non-USB app (blink) or
        non-SDK firmware (MicroPython/CircuitPython) reads as not visible, which
        is what callers want (they restore/recover it).
        """
        return any(APP_PIDS.get(d.pid) == chip for d in lsusb_rp_devices())

    def wait_app_visible(self, chip: str, timeout: float | None = None) -> bool:
        """Poll until `chip` shows up as a USB application (allow enumeration)."""
        return bool(
            self._wait(
                lambda: self.app_visible(chip),
                timeout or self.reboot_timeout,
                interval=1.0,
            )
        )

    def ensure_app(self, board: "Board", reflash: bool = False):
        """Leave `board` running a USB-visible, known-good application (hello_usb)."""
        dev = self.find_bootsel(board.chip)
        if dev is not None:
            # In BOOTSEL: load a USB app and reboot into it.
            self.flash_app(board)
            return
        if reflash or not self.app_visible(board.chip):
            # Running a non-USB / unknown image - get to BOOTSEL and restore.
            # (app_visible reads lsusb by PID, so it's reliable even when the
            # other board is in BOOTSEL - no cross-board guard needed.)
            self.ensure_bootsel(board)
            self.flash_app(board)

    # -- OpenOCD ---------------------------------------------------------
    def probe_serial(self, chip: str) -> str | None:
        """The debug-probe serial wired to `chip`'s board, or None.

        PICOTOOL_TEST_PROBE_<CHIP> always wins if set. Otherwise this is
        auto-detected (and cached for the life of this DeviceManager) - see
        `_discover_probes`. None means either no probe is configured/detected,
        or there's exactly one probe attached in total (in which case OpenOCD
        auto-selects it and no serial needs to be passed at all).
        """
        env = os.environ.get(f"PICOTOOL_TEST_PROBE_{chip.upper()}")
        if env:
            return env
        return self._discover_probes().get(chip)

    def _discover_probes(self) -> dict[str, str]:
        """Auto-detect which debug-probe serial is wired to each chip.

        Cached after the first call. Chips already configured via
        PICOTOOL_TEST_PROBE_<CHIP> are left for `probe_serial` to resolve
        directly and are excluded from detection here. With a single physical
        probe and a single undetermined chip, detection is skipped entirely
        (nothing to disambiguate). Otherwise, every unclaimed probe is tried
        (passively, see `probe_targets_chip`) against every undetermined chip;
        a chip is only assigned a serial if exactly one probe matched it -
        an ambiguous or absent match is left unset rather than guessed at.
        """
        if self._probe_serials is not None:
            return self._probe_serials

        undetermined = [
            chip
            for chip in PROBE_CONFIG
            if not os.environ.get(f"PICOTOOL_TEST_PROBE_{chip.upper()}")
        ]
        result: dict[str, str] = {}
        if undetermined:
            explicit = {
                os.environ[f"PICOTOOL_TEST_PROBE_{c.upper()}"]
                for c in PROBE_CONFIG
                if c not in undetermined
            }
            candidates = [s for s in list_probe_serials() if s not in explicit]

            if len(candidates) == 1 and len(undetermined) == 1:
                # Nothing to disambiguate.
                result[undetermined[0]] = candidates[0]
            else:
                matches = {chip: [] for chip in undetermined}
                for serial in candidates:
                    for chip in undetermined:
                        if probe_targets_chip(self.openocd, OPENOCD_INTERFACE, serial, chip):
                            matches[chip].append(serial)
                for chip, serials in matches.items():
                    if len(serials) == 1:
                        result[chip] = serials[0]
                    # else: no match, or ambiguous (>1 probe answered) - leave
                    # unset; the caller falls back to no --serial / a clear
                    # OpenOCD error rather than guessing wrong.

        self._probe_serials = result
        return result

    def _openocd_base(self, board: "Board") -> list[str]:
        cfg = BOARD_CONFIGS[board.chip]
        cmd = [self.openocd, "-f", OPENOCD_INTERFACE]
        serial = self.probe_serial(board.chip)
        if serial:
            cmd += ["-c", f"adapter serial {serial}"]
        if cfg.multidrop:
            cmd += ["-c", "set SWD_MULTIDROP 1"]
        cmd += ["-f", cfg.openocd_target]
        return cmd

    def _openocd(self, board: "Board", tcl_cmds: list[str], timeout: float = 60):
        cmd = self._openocd_base(board)
        for c in tcl_cmds:
            cmd += ["-c", c]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            # A hung probe raises TimeoutExpired, not a non-zero return - surface
            # it as DeviceError so the graceful-degradation callers that catch
            # DeviceError (ensure_bootsel's probe fallback, ensure_no_bootsel)
            # don't get an uncaught exception mid-recovery.
            raise DeviceError(
                f"openocd timed out after {timeout}s for {board.chip}:\n"
                + " ".join(cmd)
            ) from e
        if proc.returncode != 0:
            raise DeviceError(
                f"openocd failed for {board.chip}:\n"
                + " ".join(cmd)
                + "\n"
                + proc.stdout
                + proc.stderr
            )
        return proc

    def _run_openocd(self, board: "Board", program_cmd: str, timeout: float = 60):
        return self._openocd(board, [program_cmd], timeout)

    @contextlib.contextmanager
    def usb_disconnected(self, board: "Board"):
        """Drop `board` off the USB bus for the duration of the block.

        Runs the RAM-only `usb_disconnect` helper over SWD (it resets the USB
        controller, releasing the pull-up), so the board genuinely disappears
        from lsusb rather than just being halted - unlike an SWD core reset,
        which leaves the pull-up asserted. Used to remove the *other* board as
        a candidate so a picotool command run with no --bus/--address selector
        targets the single remaining device. On exit the board is rebooted back
        into its flashed app (the helper never touched flash). Requires OpenOCD
        and the usb_disconnect helper (run build_binaries.sh).
        """
        if not self.use_openocd:
            raise DeviceError("usb_disconnected needs OpenOCD")
        elf = self.binaries[board.chip].tool("usb_disconnect", "elf")
        if not elf:
            raise DeviceError(
                f"no usb_disconnect.elf for {board.chip} - run build_binaries.sh"
            )
        # Load + run it from SRAM (Thumb bit cleared on the entry point), same
        # sequence as openocd_ram_bootsel.
        entry = _elf_entry(elf) & ~1
        self._openocd(
            board,
            ["init", "reset halt", f"load_image {elf}", f"resume {entry:#x}", "exit"],
        )
        # Confirm it actually left the bus before proceeding, so a no-selector
        # command can't accidentally still see two devices.
        if not self._wait(
            lambda: not self.app_visible(board.chip)
            and self.find_bootsel(board.chip) is None,
            self.reboot_timeout,
        ):
            with contextlib.suppress(DeviceError):
                self._openocd(board, ["init", "reset run", "exit"], timeout=30)
            raise DeviceError(f"{board.chip} did not drop off USB")
        try:
            yield
        finally:
            # Reboot into the flashed app and let it come back on USB.
            with contextlib.suppress(DeviceError):
                self._openocd(board, ["init", "reset run", "exit"], timeout=30)
            with contextlib.suppress(DeviceError):
                self.ensure_app(board)

    def openocd_enter_bootsel(self, board: "Board"):
        """Enter BOOTSEL by flashing enter_bootsel (overwrites flash)."""
        elf = self.binaries[board.chip].enter_bootsel_elf
        if not elf:
            raise DeviceError(
                f"no enter_bootsel.elf for {board.chip} - run build_binaries.sh"
            )
        self._run_openocd(board, f"program {elf} verify reset exit")

    def boot_firmware_then_bootsel(self, board: "Board", firmware_uf2, boot_wait: float = 10.0):
        """Flash `firmware_uf2`, let it boot (e.g. so it creates its embedded drive),
        then return to BOOTSEL over SWD without erasing flash.

        Returns a BootselSession positioned on the board in BOOTSEL, from which
        the firmware's embedded drive can be read with `bdev`. Requires OpenOCD.
        """
        if not self.use_openocd:
            raise DeviceError("boot_firmware_then_bootsel needs OpenOCD")
        # Use ensure_bootsel's return value directly: it either returns a live
        # BOOTSEL device or raises DeviceError, so this avoids a re-query that
        # could race to None (and then AttributeError on dev.selector).
        dev = self.ensure_bootsel(board)
        self.pt.run("erase", "-a", *dev.selector, timeout=120)
        self.pt.run("load", *dev.selector, str(firmware_uf2), timeout=120)
        dev = self.find_bootsel(board.chip)
        if dev:
            self.pt.run("reboot", *dev.selector, timeout=self.reboot_timeout)
        # Wait for the firmware to leave BOOTSEL and initialise its filesystem.
        self._wait(
            lambda: self.find_bootsel(board.chip) is None, self.reboot_timeout
        )
        time.sleep(boot_wait)
        # Re-enter BOOTSEL from RAM, preserving the flash (and the new drive).
        self.openocd_ram_bootsel(board)
        if self.find_bootsel(board.chip) is None:
            raise DeviceError(f"{board.chip} did not re-enter BOOTSEL after firmware boot")
        return BootselSession(self, board)

    def openocd_ram_bootsel(self, board: "Board"):
        """Enter BOOTSEL by running enter_bootsel from RAM over SWD.

        Unlike openocd_enter_bootsel this does NOT touch flash, so it can be used
        to reach BOOTSEL on firmware (MicroPython / CircuitPython) whose embedded
        drive we then want to read.
        """
        elf = self.binaries[board.chip].enter_bootsel_ram_elf
        if not elf:
            raise DeviceError(
                f"no enter_bootsel_ram.elf for {board.chip} - run build_binaries.sh"
            )
        # Resume at the ELF entry point (Thumb bit cleared). This differs per
        # chip - RP2040 puts crt0 at 0x20000000, RP2350 further in.
        entry = _elf_entry(elf) & ~1
        self._openocd(
            board,
            ["init", "reset halt", f"load_image {elf}", f"resume {entry:#x}", "exit"],
        )
        self._wait(lambda: self.find_bootsel(board.chip), self.bootsel_timeout)

    def _load_and_boot(self, chip: str, uf2, erase: bool = False):
        """Load `uf2` onto the in-BOOTSEL `chip` and reboot into it."""
        dev = self.find_bootsel(chip)
        if dev is None:
            return
        if erase:
            self.pt.run("erase", "-a", *dev.selector, timeout=120)
            dev = self.find_bootsel(chip) or dev
        self.pt.run("load", *dev.selector, str(uf2), timeout=90)
        cur = self.find_bootsel(chip)
        if cur:
            self.pt.run("reboot", *cur.selector, timeout=self.reboot_timeout)
        self._wait(lambda: not self.find_bootsel(chip), self.reboot_timeout)

    def flash_app(self, board: "Board"):
        """Restore a known-good USB application (hello_usb) onto `board`.

        Loads over USB when the board is in BOOTSEL. If the app fails to
        enumerate (e.g. a leftover partition table redirects the boot), the
        flash is erased and the app re-loaded. Falls back to the debug probe
        when the board is not in BOOTSEL.
        """
        bset = self.binaries[board.chip]
        uf2 = bset.get("hello_usb", "uf2") or bset.get("blink", "uf2")
        dev = self.find_bootsel(board.chip)
        if dev is not None and uf2:
            self._load_and_boot(board.chip, uf2)
            if self.wait_app_visible(board.chip):
                return
            # Boot failed - wipe flash (drops any partition table) and retry.
            self.ensure_bootsel(board)
            self._load_and_boot(board.chip, uf2, erase=True)
            if self.wait_app_visible(board.chip):
                return
        # Not in BOOTSEL (or USB restore failed) - use the debug probe.
        if not self.use_openocd:
            raise DeviceError("cannot restore application: OpenOCD disabled")
        elf = bset.get("hello_usb", "elf") or bset.get("blink", "elf")
        if not elf:
            raise DeviceError(f"no application binary for {board.chip}")
        self._run_openocd(board, f"program {elf} verify reset exit")
        self._wait(lambda: not self.find_bootsel(board.chip), self.reboot_timeout)


class BootselSession:
    """A board held in BOOTSEL for the duration of a `with` block.

    Every call re-resolves the BOOTSEL device's bus/address, so it stays valid
    even if the device re-enumerates mid-session (e.g. after a `load`).
    """

    def __init__(self, manager: DeviceManager, board: "Board"):
        self.manager = manager
        self.board = board
        self.pt = manager.pt

    def selector(self) -> list[str]:
        dev = self.manager.find_bootsel(self.board.chip)
        if dev is None:
            # re-enter if the device dropped off (e.g. reboot during a test)
            dev = self.manager.ensure_bootsel(self.board)
        return dev.selector

    # Transient device errors worth retrying (device mid-reboot / re-enumerating).
    _TRANSIENT = ("rebooting", "Communication with", "not in BOOTSEL", "no known route")

    def run(self, *args, **kwargs):
        return self.pt.run(*args, *self.selector(), **kwargs)

    def ok(self, *args, retries: int = 4, **kwargs):
        """Run a command, retrying transient device errors, and assert success."""
        last = None
        for attempt in range(retries):
            last = self.pt.run(*args, *self.selector(), **kwargs)
            if last.ok:
                return last
            if not any(t in last.out for t in self._TRANSIENT):
                break
            time.sleep(1.0)
        from .picotool import PicotoolError

        raise PicotoolError(last)

    def reboot_rescan(self):
        """Reboot so the bootrom re-scans flash, then return to BOOTSEL.

        Writing a partition table while in BOOTSEL does not update the running
        bootrom's view of it; a reboot is required for `partition info` (and the
        block-device commands) to see the new table. This assumes flash holds no
        bootable image, so the board comes back to BOOTSEL on its own; if it
        boots an application instead, it is forced back into BOOTSEL.
        """
        chip = self.board.chip
        self.pt.run("reboot", *self.selector(), timeout=self.manager.reboot_timeout)
        # Wait for a full disconnect/reconnect cycle so we talk to the fresh
        # BOOTSEL instance, not the one that is still tearing down.
        self.manager._wait(
            lambda: self.manager.find_bootsel(chip) is None,
            self.manager.reboot_timeout,
            interval=0.2,
        )
        dev = self.manager._wait(
            lambda: self.manager.find_bootsel(chip),
            self.manager.bootsel_timeout,
            interval=0.2,
        )
        if dev is None:
            self.manager.ensure_bootsel(self.board)
        # Let the bootrom finish initialising before the next command.
        time.sleep(1.5)


class Board:
    """A single board under test, addressed by chip type."""

    def __init__(self, chip: str, manager: DeviceManager):
        self.chip = chip
        self.config = BOARD_CONFIGS[chip]
        self.manager = manager
        self.pt = manager.pt

    @property
    def is_rp2350(self) -> bool:
        return self.chip == "rp2350"

    @property
    def binaries(self):
        return self.manager.binaries[self.chip]

    def app_selector(self) -> list[str]:
        sel = self.manager.app_selector(self.chip)
        if sel is None:
            raise DeviceError(f"no running application found for {self.chip}")
        return sel

    def force(self, *args, **kwargs):
        """Run a picotool command with `-f`, targeting this board's app.

        picotool reboots the app into BOOTSEL, runs the command, then reboots
        it back to application mode - so the board is left running afterwards.
        """
        sel = self.app_selector()
        return self.pt.run(*args, "-f", *sel, **kwargs)

    def bootsel(self) -> "BootselContext":
        return BootselContext(self)


class BootselContext:
    def __init__(self, board: Board):
        self.board = board

    def __enter__(self) -> BootselSession:
        self.board.manager.ensure_bootsel(self.board)
        return BootselSession(self.board.manager, self.board)

    def __exit__(self, exc_type, exc, tb):
        # Always try to return the board to application mode. If the flash is
        # empty (e.g. after an erase test) restore a known-good app.
        self.board.manager.ensure_app(self.board)
        return False
