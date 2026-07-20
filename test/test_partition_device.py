"""`picotool partition` against a live RP2350 device (RP2350-only feature)."""
import json

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.rp2350]

# A partition table with a single block-device ("blockdev") partition.
FS_TABLE = {
    "version": [1, 0],
    "unpartitioned": {
        "families": ["absolute"],
        "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
    },
    "partitions": [
        {
            "name": "Filesystem",
            "id": "0x626C6F636B646576",  # "blockdev"
            "size": "512K",
            "families": [],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        }
    ],
}


@pytest.fixture
def fs_table_uf2(picotool, tmp_path):
    j = tmp_path / "pt.json"
    j.write_text(json.dumps(FS_TABLE))
    out = tmp_path / "pt.uf2"
    assert picotool.run("partition", "create", str(j), str(out)).ok
    return out


def test_partition_info_runs(rp2350_board):
    """`partition info` executes on-device and reports the table state."""
    with rp2350_board.bootsel() as dev:
        r = dev.run("partition", "info")
        assert r.ok, r
        assert "un-partitioned_space" in r.out


def test_partition_write_and_read_back(rp2350_board, fs_table_uf2):
    """Create a partition table, write it, re-scan, and read it back."""
    with rp2350_board.bootsel() as dev:
        dev.ok("erase", "-a", timeout=120)
        dev.ok("load", str(fs_table_uf2))
        dev.reboot_rescan()
        r = dev.ok("partition", "info")
        assert "Filesystem" in r.out
        assert "626c6f636b646576" in r.out.lower()
