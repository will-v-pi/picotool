"""`picotool bdev` against a block device declared via *binary info*.

Unlike test_bdev_partition.py (which uses a partition table to locate the block device),
here the block device is described by a BINARY_INFO_TYPE_BLOCK_DEVICE entry
embedded in the firmware (the bi_bdev helper, tools/bi_bdev). picotool reads that
straight out of flash and needs no `-p` / partition arguments - the same
mechanism MicroPython / CircuitPython use. Runs on both RP2040 and RP2350.
"""
import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.slow]


@pytest.fixture
def binfo_bdev(board, fw):
    """Board in BOOTSEL running bi_bdev (block device declared via binary info)."""
    uf2 = fw.tool("bi_bdev", "uf2")
    if uf2 is None:
        pytest.skip("bi_bdev firmware not built - run build_binaries.sh")
    ctx = board.bootsel()
    dev = ctx.__enter__()
    # Setup inside the try so the BOOTSEL-exit cleanup still runs if erase/load
    # raises partway through.
    try:
        dev.ok("erase", "-a", timeout=120)
        dev.ok("load", str(uf2))
        yield dev
    finally:
        ctx.__exit__(None, None, None)


def test_binfo_block_device_autodetected(binfo_bdev):
    """`bdev ls` finds the block device from binary info, without -p."""
    r = binfo_bdev.ok("bdev", "format", "--filesystem", "littlefs", timeout=60)
    # picotool prints the located embedded drive when it acts on it.
    assert "embedded drive" in r.out
    assert "testfs" in r.out


@pytest.mark.parametrize("fs", ["littlefs", "fatfs"])
def test_binfo_bdev_roundtrip(binfo_bdev, fs, tmp_path):
    dev = binfo_bdev
    dev.ok("bdev", "format", "--filesystem", fs, timeout=60)

    src = tmp_path / "hello.txt"
    src.write_text("binary-info block device\n")
    dev.ok("bdev", "cp", str(src), ":/")

    ls = dev.ok("bdev", "ls")
    assert "hello.txt" in ls.out

    cat = dev.ok("bdev", "cat", "hello.txt")
    assert "binary-info block device" in cat.out

    dev.ok("bdev", "rm", "hello.txt")
    assert "hello.txt" not in dev.ok("bdev", "ls").out
