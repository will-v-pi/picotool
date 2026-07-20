"""`picotool bdev` embedded block-device commands (RP2350-only).

Ports the flow from the repo's bdev_test.sh into the harness: create a
block-device partition, then format the filesystem and copy / list / read /
remove files. Runs for both littlefs and fatfs.
"""
import json

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.rp2350, pytest.mark.slow]

FS_TABLE = {
    "version": [1, 0],
    "unpartitioned": {
        "families": ["absolute"],
        "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
    },
    "partitions": [
        {
            "name": "Filesystem",
            "id": "0x626C6F636B646576",
            "size": "512K",
            "families": [],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        }
    ],
}


@pytest.fixture
def blockdev(rp2350_board, picotool, tmp_path):
    """An RP2350 with a freshly written block-device partition, in BOOTSEL."""
    j = tmp_path / "pt.json"
    j.write_text(json.dumps(FS_TABLE))
    pt = tmp_path / "pt.uf2"
    assert picotool.run("partition", "create", str(j), str(pt)).ok
    ctx = rp2350_board.bootsel()
    dev = ctx.__enter__()
    dev.ok("erase", "-a", timeout=120)
    dev.ok("load", str(pt))
    dev.reboot_rescan()
    try:
        yield dev
    finally:
        ctx.__exit__(None, None, None)


@pytest.mark.parametrize("fs", ["littlefs", "fatfs"])
def test_bdev_file_roundtrip(blockdev, fs, tmp_path):
    dev = blockdev
    dev.ok("bdev", "format", "--filesystem", fs, timeout=60)

    f1 = tmp_path / "file1.txt"
    f2 = tmp_path / "file2.txt"
    f1.write_text("this is file 1\n")
    f2.write_text("this is file 2\n")

    dev.ok("bdev", "cp", str(f1), ":/")
    dev.ok("bdev", "cp", str(f2), ":/")

    # both files listed
    ls = dev.run("bdev", "ls")
    assert ls.ok, ls
    assert "file1.txt" in ls.out and "file2.txt" in ls.out

    # cat returns the exact contents
    cat = dev.run("bdev", "cat", "file1.txt")
    assert cat.ok, cat
    assert "this is file 1" in cat.out

    # remove one file and confirm it's gone
    dev.ok("bdev", "rm", "file2.txt")
    ls2 = dev.run("bdev", "ls")
    assert "file2.txt" not in ls2.out
    assert "file1.txt" in ls2.out


def test_bdev_cat_matches_uploaded(blockdev, tmp_path):
    dev = blockdev
    dev.ok("bdev", "format", "--filesystem", "littlefs", timeout=60)
    src = tmp_path / "payload.txt"
    src.write_text("round-trip payload contents\n")
    dev.ok("bdev", "cp", str(src), ":/")
    got = dev.run("bdev", "cat", "payload.txt")
    assert got.ok, got
    assert "round-trip payload contents" in got.out
