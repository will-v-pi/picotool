#!/usr/bin/env bash
#
# fetch_firmware.sh - download third-party firmware (MicroPython, CircuitPython)
# used by the block-device tests, into test/binaries/<chip>/firmware/.
#
# These firmwares expose an embedded drive (a filesystem) once booted, declared
# via binary info, which `picotool bdev` can then read. They are downloaded
# rather than built, and the bdev tests SKIP if the files are absent - so the
# suite still runs offline.
#
# Override any URL with the matching environment variable, e.g.
#   MICROPYTHON_RP2040_URL=... ./fetch_firmware.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_ROOT="$HERE/binaries"

# Known-good versions (update as new releases land).
MICROPYTHON_RP2040_URL="${MICROPYTHON_RP2040_URL:-https://micropython.org/resources/firmware/RPI_PICO-20260406-v1.28.0.uf2}"
MICROPYTHON_RP2350_URL="${MICROPYTHON_RP2350_URL:-https://micropython.org/resources/firmware/RPI_PICO2-20260406-v1.28.0.uf2}"
CIRCUITPYTHON_RP2040_URL="${CIRCUITPYTHON_RP2040_URL:-https://downloads.circuitpython.org/bin/raspberry_pi_pico/en_US/adafruit-circuitpython-raspberry_pi_pico-en_US-10.2.1.uf2}"
CIRCUITPYTHON_RP2350_URL="${CIRCUITPYTHON_RP2350_URL:-https://downloads.circuitpython.org/bin/raspberry_pi_pico2/en_US/adafruit-circuitpython-raspberry_pi_pico2-en_US-10.2.1.uf2}"

fetch() {
    local chip="$1" name="$2" url="$3"
    local dir="$OUT_ROOT/$chip/firmware"
    local dest="$dir/$name.uf2"
    mkdir -p "$dir"
    echo "== $chip/$name <- $url =="
    curl -fL --retry 3 --max-time 300 -o "$dest" "$url"
    ls -l "$dest" | awk '{print "   ", $5, "bytes"}'
}

fetch rp2040 micropython    "$MICROPYTHON_RP2040_URL"
fetch rp2350 micropython    "$MICROPYTHON_RP2350_URL"
fetch rp2040 circuitpython  "$CIRCUITPYTHON_RP2040_URL"
fetch rp2350 circuitpython  "$CIRCUITPYTHON_RP2350_URL"

# Universal (multi-family) binaries, used by the info tests (issue #112). These
# are chip-independent, so they live under binaries/universal/.
BLINK_UNIVERSAL_URL="${BLINK_UNIVERSAL_URL:-https://github.com/raspberrypi/pico-sdk-prebuilts/releases/latest/download/blink_universal.uf2}"
NUKE_UNIVERSAL_URL="${NUKE_UNIVERSAL_URL:-https://github.com/raspberrypi/pico-sdk-prebuilts/releases/latest/download/nuke_universal.uf2}"
fetch universal blink_universal "$BLINK_UNIVERSAL_URL"
fetch universal nuke_universal  "$NUKE_UNIVERSAL_URL"

echo "Firmware downloaded under $OUT_ROOT/<chip>/firmware/"
