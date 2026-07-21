"""`picotool seal` ELF-squashing behaviour (no hardware needed).

Squashing (elf_file::store_squashed) closes alignment gaps between PT_LOAD
segments before signing/hashing, so a RAM image has no holes. These tests pin
down the segment-placement rules with hand-built ELFs, since the exact gap
sizes / aliasing needed to hit these edge cases aren't reliably reproducible
from a real toolchain build across compiler/linker versions.

`picotool info` reports picobin metadata, not raw ELF program headers, so
placement is verified by reading the output ELF's program header table back
directly (see lib.synthetic_elf.read_load_segments).
"""
from __future__ import annotations

import pytest

from lib.synthetic_elf import (
    Segment,
    build_elf,
    image_def_block,
    ignored_block,
    overlapping_pairs,
    read_load_segments,
)


def segment_map(path):
    """{paddr: filez} for the PT_LOAD segments in an ELF, for easy lookup."""
    return dict(read_load_segments(path))


def test_squash_closes_alignment_gap(picotool, tmp_path):
    """A plain alignment gap between two segments is closed."""
    block = image_def_block(next_block_rel=0)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=block),
            Segment(paddr=0x20000300, filez=0x80),  # gap 0x200 > size 0x80
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out))
    assert r.ok, r
    segs = segment_map(out)
    assert segs.get(0x20000100) == 0x80, segs


def test_squash_exact_fit_gap(picotool, tmp_path):
    """A gap exactly equal to the next segment's size is still closed (no off-by-one)."""
    block = image_def_block(next_block_rel=0)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=block),
            Segment(paddr=0x20000200, filez=0x100),  # gap == size == 0x100
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out))
    assert r.ok, r
    segs = segment_map(out)
    assert segs.get(0x20000100) == 0x100, segs


def test_squash_blocks_self_overlapping_move(picotool, tmp_path):
    """A gap smaller than the segment must not be closed (destination would overlap the segment's own VMA)."""
    block = image_def_block(next_block_rel=0)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=block),
            Segment(paddr=0x20000104, filez=0x200),  # gap 4 < size 0x200
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out), "--verbose")
    assert r.ok, r
    segs = segment_map(out)
    # Must still be at its original address, not moved to 0x20000100.
    assert segs.get(0x20000104) == 0x200, segs


def test_squash_preserves_metadata_block_aliased_on_bss(picotool, tmp_path):
    """The original #335 case: a metadata block placed on top of .bss must not move."""
    image_def = image_def_block(next_block_rel=0x600)
    block2 = ignored_block(next_block_rel=-0x600)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=image_def),
            Segment(paddr=0x20000600, filez=0, memsz=0x400),  # .bss
            Segment(paddr=0x20000600, filez=0x100, data=block2),  # block on top of .bss
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out), "--verbose")
    assert r.ok, r
    segs = segment_map(out)
    assert segs.get(0x20000600) == 0x100, segs


def test_squash_preserves_metadata_block_non_aliased_gap(picotool, tmp_path):
    """A metadata block reachable via an ordinary gap (not paddr-aliased) must not move."""
    image_def = image_def_block(next_block_rel=0x600)
    block2 = ignored_block(next_block_rel=-0x600)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=image_def),
            Segment(paddr=0x20000100, filez=0x100),  # ordinary .data, not aliased to block2
            Segment(paddr=0x20000600, filez=0x100, data=block2),  # gap 0x400, no alias
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out), "--verbose")
    assert r.ok, r
    segs = segment_map(out)
    assert segs.get(0x20000600) == 0x100, segs


def test_squash_does_not_overwrite_protected_block_with_later_segment(picotool, tmp_path):
    """A segment after a protected (aliased-on-.bss) block must squash past it, not onto it."""
    block = image_def_block(next_block_rel=0)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x1000, data=block),
            Segment(paddr=0x20001000, filez=0, memsz=0x400),  # .bss
            Segment(paddr=0x20001000, filez=0x100),  # aliases .bss's paddr, protected from moving
            Segment(paddr=0x20001200, filez=0x40),  # ordinary gap after the protected segment
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out), "--verbose")
    assert r.ok, r
    segs = read_load_segments(out)
    bad = overlapping_pairs(segs)
    assert not bad, f"squashing produced overlapping segments (data corruption): {bad}"


def test_seal_rejects_cyclic_block_loop(picotool, tmp_path):
    """A block loop that cycles without returning to the first block fails cleanly, not a hang."""
    # A -> B -> C -> B (cycle closes on B, not A)
    a = image_def_block(next_block_rel=0x600)
    b = ignored_block(next_block_rel=0x600)
    c = ignored_block(next_block_rel=-0x600)
    elf = build_elf(
        tmp_path / "in.elf",
        [
            Segment(paddr=0x20000000, filez=0x100, data=a),
            Segment(paddr=0x20000600, filez=0x100, data=b),
            Segment(paddr=0x20000C00, filez=0x100, data=c),
        ],
    )
    out = tmp_path / "out.elf"
    r = picotool.run("seal", str(elf), str(out), "--verbose", timeout=10)
    assert not r.timed_out, r
    assert not r.ok
    assert "loop" in r.out.lower()
