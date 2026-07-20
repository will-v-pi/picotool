"""Smoke tests for `picotool link` and `picotool coprodis` (no hardware)."""
import pytest

CHIPS = ["rp2040", "rp2350"]


@pytest.fixture
def bset(require_binaries, chip):
    return require_binaries[chip]


def test_link_bins(picotool, require_binaries, tmp_path):
    """link combines multiple BINs into one block loop image.

    Block loops are an RP2350 feature - the input BINs must carry an embedded
    block, which RP2040 images do not, so this is RP2350-only.
    """
    bset = require_binaries["rp2350"]
    out = tmp_path / "linked.bin"
    r = picotool.run(
        "link",
        str(out),
        str(bset.path("blink.bin")),
        str(bset.path("hello_usb.bin")),
    )
    assert r.ok, r
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.parametrize("chip", CHIPS)
def test_link_requires_bins(picotool, bset, tmp_path):
    """Linking ELFs is rejected with a clear error."""
    out = tmp_path / "linked.bin"
    r = picotool.run(
        "link",
        str(out),
        str(bset.path("blink.elf")),
        str(bset.path("hello_usb.elf")),
    )
    assert not r.ok
    assert "BIN" in r.out


def test_coprodis_runs(picotool, tmp_path):
    """coprodis post-processes a disassembly file and writes an output file."""
    src = tmp_path / "in.dis"
    src.write_text(
        "10000100:\tee000110 \tmcr\t14, 0, r0, cr0, cr0, {0}\n"
        "10000104:\t4770      \tbx\tlr\n"
    )
    out = tmp_path / "out.dis"
    r = picotool.run("coprodis", str(src), str(out))
    assert r.ok, r
    assert out.exists()
