"""`picotool partition create` + inspection on files (RP2350 concept, no hw)."""
import json

import pytest

PARTITION_TABLE = {
    "version": [1, 0],
    "unpartitioned": {
        "families": ["absolute"],
        "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
    },
    "partitions": [
        {
            "name": "A",
            "id": "0x0000000000000001",
            "size": "256K",
            "families": ["rp2350-arm-s"],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        },
        {
            "name": "B",
            "size": "256K",
            "families": ["data"],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        },
    ],
}


@pytest.fixture
def pt_json(tmp_path):
    p = tmp_path / "pt.json"
    p.write_text(json.dumps(PARTITION_TABLE))
    return p


def test_partition_create_uf2(picotool, pt_json, tmp_path):
    out = tmp_path / "pt.uf2"
    r = picotool.run("partition", "create", str(pt_json), str(out))
    assert r.ok, r
    assert out.exists() and out.stat().st_size > 0


def test_partition_table_reported_by_info(picotool, pt_json, tmp_path):
    out = tmp_path / "pt.uf2"
    assert picotool.run("partition", "create", str(pt_json), str(out)).ok
    r = picotool.run("info", "-a", str(out))
    assert r.ok, r
    assert "partition table" in r.out
    assert "partition 0 (A):" in r.out
    assert "partition 1" in r.out


def test_partition_create_bin(picotool, pt_json, tmp_path):
    out = tmp_path / "pt.bin"
    r = picotool.run("partition", "create", str(pt_json), str(out), "-t", "bin")
    assert r.ok, r
    assert out.exists()


def test_partition_create_bad_json_fails(picotool, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json")
    out = tmp_path / "out.uf2"
    r = picotool.run("partition", "create", str(bad), str(out))
    assert not r.ok


def _make_table(tmp_path, partition):
    table = {
        "version": [1, 0],
        "unpartitioned": {
            "families": ["absolute"],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        },
        "partitions": [partition],
    }
    j = tmp_path / "pt.json"
    j.write_text(json.dumps(table))
    return j


def test_partition_id_not_truncated(picotool, tmp_path):
    """Regression for #225 / #161: a 64-bit partition id must survive intact,
    not be truncated to its lower 32 bits."""
    pid = "0x776966696669726d"  # "wififirm" - high 32 bits are non-zero
    j = _make_table(
        tmp_path,
        {
            "name": "WiFi",
            "id": pid,
            "size": "240K",
            "families": ["data"],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
        },
    )
    out = tmp_path / "pt.uf2"
    assert picotool.run("partition", "create", str(j), str(out)).ok
    r = picotool.run("info", "-a", str(out))
    assert r.ok, r
    assert "id=776966696669726d" in r.out.lower()


def test_partition_boolean_flags_honoured(picotool, tmp_path):
    """Regression for #290: boolean flags must be applied independently, not
    conflated (arm ignored, riscv not => arm_boot 0, riscv_boot 1)."""
    j = _make_table(
        tmp_path,
        {
            "name": "P",
            "id": "0x1",
            "size": "256K",
            "families": ["rp2350-arm-s"],
            "permissions": {"secure": "rw", "nonsecure": "rw", "bootloader": "rw"},
            "ignored_during_arm_boot": True,
            "ignored_during_riscv_boot": False,
        },
    )
    out = tmp_path / "pt.uf2"
    assert picotool.run("partition", "create", str(j), str(out)).ok
    r = picotool.run("info", "-a", str(out))
    assert r.ok, r
    assert "arm_boot 0" in r.out
    assert "riscv_boot 1" in r.out
