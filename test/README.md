# picotool test suite

A pytest-based test suite that exercises `picotool` end-to-end: file-based
commands run anywhere, and device commands run against real RP2040 and RP2350
hardware. It is built to be driven from the *develop* branches of picotool,
pico-sdk and pico-examples.

## What it covers

| Area | File | Hardware? |
|------|------|-----------|
| `help` / `version` for every command & subcommand | `test_help.py` | no |
| `info` / `config` on ELF / UF2 / BIN files | `test_file_info.py` | no |
| `uf2 convert` / `uf2 combine` | `test_uf2_file.py` | no |
| `partition create` + inspection (files) | `test_partition_file.py` | no |
| `link` / `coprodis` | `test_link_coprodis.py` | no |
| `otp list` (built-in OTP map) | `test_otp_list.py` | no |
| `load` / `save` / `verify` / `erase` round-trips | `test_load_save_verify.py` | **yes** |
| `reboot` variants | `test_reboot.py` | **yes** |
| `info` / `config` on a device (bug regressions) | `test_info_device.py` | **yes** |
| `partition info` + write/read-back (RP2350) | `test_partition_device.py` | **yes** |
| `bdev` via a partition-table block device (RP2350) | `test_bdev.py` | **yes** |
| `bdev` via a *binary-info* block device (RP2040 + RP2350) | `test_bdev_binfo.py` | **yes** |
| `bdev` against MicroPython / CircuitPython drives (RP2040 + RP2350) | `test_bdev_firmware.py` | **yes** |
| `otp` dump / get / set / load (RP2350) | `test_otp_device.py` | **yes, gated** |
| `seal` - hashing, signing, rollback metadata (RP2350) | `test_seal_secure_boot.py` | no |
| Secure boot + rollback enforcement (RP2350) | `test_otp_secure_boot.py` | **yes, gated (extra)** |

Hardware tests are parametrized over every connected & selected chip
(`rp2040`, `rp2350`); a chip that is not connected is skipped automatically.

## Requirements

* Python 3.9+ and `pytest` (`pip install -r requirements.txt`)
* A built `picotool` (defaults to `../build/picotool`)
* For building the firmware binaries: the pico-sdk + pico-examples develop
  trees, CMake, Ninja and `arm-none-eabi-gcc`
* For hardware tests: `libusb` (so picotool can talk over USB) and, for the
  debug-probe recovery path, `openocd`

### Suggested setup

```bash
# from the picotool repo root
cmake -S . -B build -G Ninja -D PICO_SDK_PATH=/path/to/pico-sdk
cmake --build build

cd test
python3 -m venv test-venv
./test-venv/bin/pip install -r requirements.txt
```

## Hardware setup

The device tests assume two boards, each connected to the host **twice**:

* its **native USB** port (so picotool can drive it), and
* a debug probe (e.g. a Raspberry Pi Debug Probe) on SWD, used as a guaranteed
  recovery / BOOTSEL-entry path via OpenOCD.

**Which debug probe is wired to which board is auto-detected** - nothing needs
configuring by hand. On startup, if more than one probe is attached, the harness
lists their serials (`lsusb -v -d 2e8a:000c`) and, for each one not already
pinned by an environment variable, tries a quick passive SWD connect against
each candidate chip to see which target answers - the same manual process
`DEBUG_PROBES.md`-style docs describe, just automated. It's non-destructive (a
plain connect + examine, never a reset) and only takes about a second per
probe; the result is cached for the rest of the test session. With a single
probe attached, detection is skipped entirely - there's nothing to disambiguate.

If detection is wrong or ambiguous for your setup (e.g. more than two probes
attached, or a probe wired to something OpenOCD can examine but that isn't
actually one of these two boards), override it explicitly:

| Variable | Purpose |
|----------|---------|
| `PICOTOOL_TEST_PROBE_RP2040` | force the RP2040 board's debug-probe serial |
| `PICOTOOL_TEST_PROBE_RP2350` | force the RP2350 board's debug-probe serial |
| `PICOTOOL_TEST_OPENOCD_INTERFACE` | OpenOCD interface config, default `interface/cmsis-dap.cfg` (set this for a non-CMSIS-DAP probe) |

Setting one of the two `_PROBE_` variables still lets the other be auto-detected.

Disable the probe path entirely with `--no-openocd` (USB `reboot -u -f` is then
the only way into BOOTSEL; the MicroPython/CircuitPython bdev tests need the
probe and are skipped without it).

## Building the firmware binaries

```bash
./build_binaries.sh
```

This is self-contained: if `PICO_SDK_PATH` / `PICO_EXAMPLES_PATH` aren't set (and
no checkout already exists at the default location), it clones the `develop`
branch of each into `test/_deps/` itself - no particular directory layout is
assumed, and no other checkout needs to exist first. If you already have
pico-sdk / pico-examples checkouts (e.g. for other work), point at them instead
to skip the clone and reuse your existing tree:

```bash
PICO_SDK_PATH=/path/to/pico-sdk PICO_EXAMPLES_PATH=/path/to/pico-examples ./build_binaries.sh
```

It builds a curated set of programs (`blink`, `hello_usb`, `hello_serial`,
`hello_reset`, `hello_anything`, `blink_any`, plus `hello_otp` on RP2350) as
`.elf` / `.uf2` / `.bin` for both boards, into `binaries/<chip>/`. It also builds
helper firmwares into `binaries/<chip>/tools/`:

* `enter_bootsel` / `enter_bootsel_ram` - drop a board into BOOTSEL over SWD.
  The `_ram` variant runs from SRAM so it can reach BOOTSEL **without erasing
  flash** (used to read the drive of firmware that lacks picotool's reset
  interface).
* `bi_bdev` - declares an embedded block device via *binary info* (no partition
  table), used by `test_bdev_binfo.py`.

### Third-party firmware (MicroPython / CircuitPython)

`test_bdev_firmware.py` reads the embedded drives that MicroPython and
CircuitPython expose. Download those firmwares first:

```bash
./fetch_firmware.sh
```

This fetches MicroPython and CircuitPython UF2s for Pico and Pico 2 into
`binaries/<chip>/firmware/`. Override any URL with the matching environment
variable (e.g. `MICROPYTHON_RP2040_URL`). The tests **skip** if the files are
absent, so the rest of the suite still runs offline. Because neither firmware
honours picotool's `-f` reset interface, these tests require the debug probe
(OpenOCD) to re-enter BOOTSEL after the firmware boots.

## Running

```bash
# everything that can run given what's connected
./test-venv/bin/python -m pytest

# only file-based tests (no hardware)
./test-venv/bin/python -m pytest -m "not hardware"

# a single board
./test-venv/bin/python -m pytest --boards rp2350

# skip the slow full-flash / bdev tests
./test-venv/bin/python -m pytest -m "not slow"
```

### Useful options

| Option | Meaning |
|--------|---------|
| `--picotool PATH` | picotool binary under test (default `../build/picotool`) |
| `--boards rp2040,rp2350` | which chips to test |
| `--openocd PATH` | openocd binary |
| `--no-openocd` | disable the debug-probe recovery path |
| `--run-otp` | **enable the OTP device tests — FPGA only (see below)** |
| `--require-boards` | fail the whole run immediately if any selected board isn't connected, instead of silently skipping its tests (see below) |

By default, a board that isn't connected just means its tests are skipped - handy
when iterating with only one board on your desk, but it also means a genuinely
disconnected/dead board in CI produces a suspiciously short, all-green run
instead of a failure. Pass `--require-boards` to turn that into a hard,
immediate failure (checked once per session, before any tests run) - use it in
CI/automation where "both boards were actually exercised" needs to be verified,
not assumed.

## OTP tests

OTP (One-Time-Programmable) memory can only be burned once, so the OTP *device*
tests would permanently consume rows on real silicon. They are therefore
**skipped unless `--run-otp` is passed**, and are meant to be run only against an
FPGA whose OTP can be reset:

```bash
./test-venv/bin/python -m pytest test_otp_device.py --run-otp --boards rp2350
```

The device-free `otp list` tests (`test_otp_list.py`) always run. The scratch
row used by the OTP write tests defaults to an unnamed data row and can be
overridden with `PICOTOOL_TEST_OTP_ROW`.

**Known issue:** `TestOtpIssueRegressions::test_permissions_are_per_page` (the
`#294` regression) has been observed to wedge an RP2350 FPGA - `otp permissions`
loads a temporary helper binary (`xip_ram_perms`) onto the device (required by
errata RP2350-E15), and on at least one FPGA this failed with `ERROR: File to
load contained an invalid memory range`, after which the device stopped
responding to `otp get`/`info -a`/even `erase -a` (though SWD access stayed
healthy throughout). A power cycle fully recovered it, and OTP itself was
unaffected. Root cause not yet identified - possibly an FPGA-specific
incompatibility with the embedded helper binary. If you hit this, power-cycle
the board; consider deselecting this one test on FPGAs where it reproduces:
`--deselect test_otp_device.py::TestOtpIssueRegressions::test_permissions_are_per_page`.

### Secure boot and rollback

`test_seal_secure_boot.py` tests `picotool seal`'s hashing, signing and
rollback-version metadata entirely with files - no hardware, always runs.

`test_otp_secure_boot.py` exercises the real thing on a device, in two tiers:

* `TestProvisionBootKey` - burns one boot-key slot but does **not** enable
  enforcement, so the board keeps booting ordinary unsigned images afterward.
  Gated behind plain `--run-otp`, same as the rest of `test_otp_device.py`.
* `TestSecureBootEnforcement` - sets `CRIT1.SECURE_BOOT_ENABLE`. Unlike every
  other OTP test, this is a **one-way, whole-chip** change: once set, that
  specific chip will never again boot an unsigned image, for the rest of its
  life - and per picotool's own field description, it also **permanently
  disables the RISC-V cores**. There is no "restore to normal" afterward.

  This needs `--run-otp` **and** a second, separate opt-in:

  ```bash
  ./test-venv/bin/python -m pytest test_otp_secure_boot.py::TestSecureBootEnforcement \
      --run-otp --boards rp2350
  # (skipped without this too - see the skip reason for why)
  PICOTOOL_TEST_ENABLE_SECURE_BOOT=1 ./test-venv/bin/python -m pytest \
      test_otp_secure_boot.py::TestSecureBootEnforcement --run-otp --boards rp2350
  ```

  Only ever run it against an FPGA image whose OTP-equivalent state you can
  reset afterward, and run it **in isolation** - once it has run, the plain
  unsigned binaries the rest of this suite relies on will no longer boot on
  that chip. Verified passing end-to-end against a real RP2350 FPGA
  (2026-07-20): correctly signed images boot, tampering is rejected via
  signature, an older rollback version is rejected once a newer one has run,
  and a newer version always succeeds. Signature/rollback verification was
  markedly slower than real silicon on that FPGA (crypto emulation) - budget
  **10-15 minutes** for a full run, not seconds.

## Regression tests for reported issues

Several tests pin behaviour from specific picotool issues so it can't regress:

| Issue | What it checks | Test |
|-------|----------------|------|
| #339 | `uf2 convert` of an image not starting at FLASH_START isn't mis-guessed as RP2040 | `test_uf2_file.py::TestUf2ConvertRegressions::test_convert_image_not_at_flash_start` |
| #185 | `uf2 convert --verbose` actually prints output | `test_uf2_file.py::…::test_verbose_produces_output` |
| #225 / #161 | 64-bit partition ids aren't truncated to 32 bits | `test_partition_file.py::test_partition_id_not_truncated` |
| #290 | partition-table JSON boolean flags are applied independently | `test_partition_file.py::test_partition_boolean_flags_honoured` |
| #296 | `otp list`/`get` include row 1 | `test_otp_list.py::test_otp_list_row_one` |
| #112 | `info` on a universal (multi-family) binary doesn't error on overlaps | `test_file_info.py::TestInfoRegressions::test_info_universal_binary` |
| #15 | RP2040 binaries report their boot2 stage | `test_file_info.py::TestInfoRegressions::test_rp2040_reports_boot2` |
| #113 | `save -v` verifies saved data | `test_load_save_verify.py::TestSave::test_save_verify_flag` |
| #24 | a range saved to UF2 is a valid, loadable image | `test_load_save_verify.py::TestSave::test_save_range_uf2_is_loadable` |
| #336 | `info -a` doesn't crash with a device attached | `test_info_device.py` |
| #294 | `otp permissions` computes each page's lock independently | `test_otp_device.py::TestOtpIssueRegressions::test_permissions_are_per_page` *(--run-otp)* |
| #266 | page locks for pages 32-63 can be set | `test_otp_device.py::…::test_set_high_page_lock` *(--run-otp)* |
| #330 | *(open)* setting a bit in a disagreeing redundant row | `test_otp_device.py::…::test_redundant_row_bit_update` *(--run-otp, xfail, opt-in)* |

The OTP regressions burn OTP, so they only run under `--run-otp` (FPGA only) and
assume a fresh/reset image. #330 is still open (marked `xfail`) and is opt-in via
`PICOTOOL_TEST_OTP_RBIT_FIELD` so it never targets a security-critical field by
accident.

## An `info` bug this suite caught (now fixed)

While building this suite an earlier develop build (~picotool 2.2.1-develop)
was found to mishandle `picotool info` when two RP-series devices are attached
(the normal state of this rig) and one is in BOOTSEL:

1. **`info -a` (unfiltered) crashed** in `info_command::execute` (SIGSEGV), or
   exited silently with no output.
2. **targeted `info` on an RP2040 in BOOTSEL printed nothing**, even though the
   same device served `save` / `load` / `verify` correctly.

This is fixed on current master (2.3.0) and develop (2.3.1-develop) — see "fix
`picotool info` for non-partition-capable devices" (#338). `test_info_device.py`
keeps the regression tests so it stays fixed. Data-path commands were never
affected.

As a belt-and-braces measure the harness still avoids running `info -a` while a
device is in BOOTSEL (`ensure_no_bootsel()` first).

## How the harness handles the hardware

* Boards are identified by *chip*, never by a cached USB address (addresses
  change on every re-enumeration). `lsusb` provides bus/address/product-id;
  BOOTSEL devices are recognised purely by product id (`0x0003` = RP2040,
  `0x000f` = RP2350).
* To avoid the `info -a` crash, the harness never runs `info -a` while any
  device is in BOOTSEL — it reboots stray BOOTSEL devices back to application
  mode first.
* Each hardware test enters BOOTSEL (`reboot -u -f`, or an OpenOCD-flashed
  `enter_bootsel` as a fallback), drives picotool with an explicit
  `--bus/--address` selector, and the `board` fixture restores a USB-visible
  application afterwards (erasing and re-flashing if a leftover partition table
  would otherwise stop it booting).
