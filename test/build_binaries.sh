#!/usr/bin/env bash
#
# build_binaries.sh - build the curated set of firmware binaries that the
# picotool test suite uses.
#
# Binaries are built from the *develop* branches of pico-sdk and pico-examples
# (plus a couple of test programs) for both RP2040 (board
# "pico") and RP2350 (board "pico2").
#
# Outputs are collected under test/binaries/<chip>/ where <chip> is rp2040 or
# rp2350, e.g.
#     test/binaries/rp2040/blink.elf
#     test/binaries/rp2350/hello_encrypted.uf2
#
# A small recovery helper (enter_bootsel) is also built per chip into
# test/binaries/<chip>/tools/ - the harness can flash it over SWD to force a
# board into BOOTSEL.
#
# Environment overrides:
#   PICO_SDK_PATH             an existing pico-sdk checkout to build against,
#                             instead of cloning one. Default (if unset): clone
#                             into PICOTOOL_TEST_DEPS_DIR/pico-sdk
#   PICO_EXAMPLES_PATH        likewise for pico-examples
#   PICO_SDK_REPO/BRANCH      git URL / branch to clone pico-sdk from
#                             (default: raspberrypi/pico-sdk, develop)
#   PICO_EXAMPLES_REPO/BRANCH likewise for pico-examples
#   PICOTOOL_TEST_DEPS_DIR    where cloned dependencies are placed,
#                             default: test/_deps
#   PICOTOOL_TEST_BUILD_ROOT  scratch build tree, default: test/_work
#   PICOTOOL_INSTALL_DIR      an already-installed picotool (see
#                             BUILDING.md's "Custom Path Installation"), reused
#                             instead of letting each build directory
#                             fetch and build its own copy from git. Default:
#                             ../install. Ignored if it doesn't look like a
#                             flat picotool install.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # .../picotool/test
REPO_ROOT="$(cd "$HERE/.." && pwd)"                        # .../picotool

DEPS_DIR="${PICOTOOL_TEST_DEPS_DIR:-$HERE/_deps}"

PICO_SDK_REPO="${PICO_SDK_REPO:-https://github.com/raspberrypi/pico-sdk.git}"
PICO_SDK_BRANCH="${PICO_SDK_BRANCH:-develop}"
PICO_EXAMPLES_REPO="${PICO_EXAMPLES_REPO:-https://github.com/raspberrypi/pico-examples.git}"
PICO_EXAMPLES_BRANCH="${PICO_EXAMPLES_BRANCH:-develop}"

PICO_SDK_PATH="${PICO_SDK_PATH:-$DEPS_DIR/pico-sdk}"
PICO_EXAMPLES_PATH="${PICO_EXAMPLES_PATH:-$DEPS_DIR/pico-examples}"
BUILD_ROOT="${PICOTOOL_TEST_BUILD_ROOT:-$HERE/_work}"
OUT_ROOT="$HERE/binaries"
PICOTOOL_INSTALL_DIR="${PICOTOOL_INSTALL_DIR:-$REPO_ROOT/install}"

echo "picotool test binary builder"
echo "  PICO_SDK_PATH        = $PICO_SDK_PATH"
echo "  PICO_EXAMPLES_PATH   = $PICO_EXAMPLES_PATH"
echo "  BUILD_ROOT           = $BUILD_ROOT"
echo "  OUT_ROOT             = $OUT_ROOT"
echo "  PICOTOOL_INSTALL_DIR = $PICOTOOL_INSTALL_DIR"
echo

# ensure_repo <dir> <url> <branch> <label> <path-env-var-name>
# If <dir> is already a source checkout, use it as-is. If <dir> doesn't exist
# yet, clone <branch> of <url> into it (shallow - only the source tree is
# needed to build). If <dir> exists but isn't a checkout, refuse to touch it.
ensure_repo() {
    local dir="$1" url="$2" branch="$3" label="$4" path_var="$5"
    if [ -f "$dir/CMakeLists.txt" ]; then
        echo "  (using existing $label checkout at $dir)"
        return
    fi
    if [ -e "$dir" ]; then
        echo "ERROR: $dir exists but doesn't look like a $label source tree (no CMakeLists.txt)" >&2
        echo "       remove it, or point $path_var at a valid checkout" >&2
        exit 1
    fi
    echo "== cloning $label ($branch) into $dir =="
    mkdir -p "$(dirname "$dir")"
    git clone --depth 1 --branch "$branch" "$url" "$dir"
}

ensure_repo "$PICO_SDK_PATH" "$PICO_SDK_REPO" "$PICO_SDK_BRANCH" pico-sdk PICO_SDK_PATH
ensure_repo "$PICO_EXAMPLES_PATH" "$PICO_EXAMPLES_REPO" "$PICO_EXAMPLES_BRANCH" pico-examples PICO_EXAMPLES_PATH

# ensure_shared_picotool: pico-sdk's pico_init_picotool() (tools/CMakeLists.txt)
# has each project fetch-and-build its own copy of picotool from git unless
# find_package(picotool CONFIG) already succeeds - which it will if picotool_DIR
# points at an installed CMake package config. If PICOTOOL_INSTALL_DIR already
# holds a flat picotool install (picotoolConfig.cmake alongside the binary -
# see BUILDING.md's "Custom Path Installation"), just point picotool_DIR at it
# so every cmake -S/-B call below (6 of them: 2 example builds + 4 tool
# builds) reuses that one install instead of each independently
# fetching+building picotool from git. Falls back to the old per-build fetch
# behaviour if no install is found.
ensure_shared_picotool() {
    if [ ! -f "$PICOTOOL_INSTALL_DIR/picotool/picotoolConfig.cmake" ] || [ ! -x "$PICOTOOL_INSTALL_DIR/picotool/picotool" ]; then
        echo "::warning :: (no picotool install at $PICOTOOL_INSTALL_DIR - each build below will fetch/build its own)"
        return
    fi

    export picotool_DIR="$PICOTOOL_INSTALL_DIR/picotool"
    echo "== reusing installed picotool: picotool_DIR = $picotool_DIR =="
}

ensure_shared_picotool

# tinyusb is a submodule required for pico_stdio_usb, which hello_usb,
# and hello_anything all depend on.
if [ -e "$PICO_SDK_PATH/.git" ] && [ ! -f "$PICO_SDK_PATH/lib/tinyusb/src/tusb.c" ]; then
    echo "== fetching tinyusb submodule (required for USB stdio examples) =="
    ( cd "$PICO_SDK_PATH" && git submodule update --init --depth 1 lib/tinyusb )
fi

# pico-examples executable targets built for every board.
# dev_multi_cdc advertises a custom USB vid/pid (0xcafe/0x4102) plus the RPI
# reset interface - used by test_selectors.py to exercise --vid/--pid selection.
COMMON_TARGETS=(blink hello_usb hello_serial hello_anything dev_multi_cdc)
# Extra targets only meaningful on RP2350.
declare -A EXTRA_TARGETS=( [pico2]="hello_encrypted" )

# copy_outputs <build-dir> <target-name> <out-dir>
# Copies <target>.{elf,uf2,bin} to <out-dir> if they exist.
copy_outputs() {
    local bdir="$1" target="$2" out="$3"
    local found=0 f
    while IFS= read -r -d '' f; do
        cp -f "$f" "$out/"
        found=1
    done < <(find "$bdir" -type f \( \
                -name "$target.elf" -o -name "$target.uf2" -o -name "$target.bin" \
             \) -print0)
    if [ "$found" -eq 0 ]; then
        echo "::warning :: no outputs found for target '$target'" >&2
    fi
}

build_board() {
    local board="$1" chip="$2"
    local bdir="$BUILD_ROOT/examples-$board"
    local out="$OUT_ROOT/$chip"
    mkdir -p "$out"

    echo "=== $board ($chip): configuring pico-examples ==="
    if [ ! -f "$bdir/build.ninja" ]; then
        cmake -S "$PICO_EXAMPLES_PATH" -B "$bdir" -G Ninja \
            -D PICO_SDK_PATH="$PICO_SDK_PATH" \
            -D PICO_BOARD="$board" \
            -D CMAKE_BUILD_TYPE=Release
    else
        echo "  (reusing existing configuration in $bdir)"
    fi

    local targets=("${COMMON_TARGETS[@]}")
    if [ -n "${EXTRA_TARGETS[$board]:-}" ]; then
        # shellcheck disable=SC2206
        targets+=(${EXTRA_TARGETS[$board]})
    fi

    echo "=== $board ($chip): building ${targets[*]} ==="
    cmake --build "$bdir" --target "${targets[@]}"

    echo "=== $board ($chip): collecting outputs ==="
    for t in "${targets[@]}"; do
        copy_outputs "$bdir" "$t" "$out"
    done

    build_tool "$board" "$chip" enter_bootsel
    build_tool "$board" "$chip" bi_bdev
    build_tool "$board" "$chip" usb_disconnect

    echo "=== $board ($chip): done -> $out ==="
    ls -1 "$out"
    echo
}

# build_tool <board> <chip> <tool-name>
# Builds a standalone SDK helper program from tools/<tool-name>/ into
# binaries/<chip>/tools/.
build_tool() {
    local board="$1" chip="$2" name="$3"
    local src="$HERE/tools/$name"
    local bdir="$BUILD_ROOT/$name-$board"
    local out="$OUT_ROOT/$chip/tools"
    mkdir -p "$out"

    echo "--- $board ($chip): building $name helper ---"
    if [ ! -f "$bdir/build.ninja" ]; then
        cmake -S "$src" -B "$bdir" -G Ninja \
            -D PICO_SDK_PATH="$PICO_SDK_PATH" \
            -D PICO_BOARD="$board" \
            -D CMAKE_BUILD_TYPE=Release
    fi
    cmake --build "$bdir"
    copy_outputs "$bdir" "$name" "$out"
    # enter_bootsel also produces a RAM-only variant used for non-destructive
    # BOOTSEL entry over SWD (see lib/devices.py openocd_ram_bootsel).
    if [ -f "$bdir/${name}_ram.elf" ]; then
        copy_outputs "$bdir" "${name}_ram" "$out"
    fi
}

build_board pico  rp2040
build_board pico2 rp2350

echo "All binaries built under $OUT_ROOT"
