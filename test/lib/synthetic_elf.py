"""Build minimal synthetic ELF32 ARM files with precise PT_LOAD segment layouts.

Used to exercise `elf_file::store_squashed` (segment-squashing before `seal`)
with exact byte-level control over segment gaps, aliasing and picobin block
placement -- control a real toolchain build can't reliably guarantee across
compiler/linker versions.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

EH_SIZE = 52
PH_SIZE = 32
SH_SIZE = 40

PICOBIN_BLOCK_MARKER_START = 0xFFFFDED3
PICOBIN_BLOCK_MARKER_END = 0xAB123579
PICOBIN_BLOCK_ITEM_2BS_LAST = 0x80 | 0x7F
PICOBIN_BLOCK_ITEM_2BS_IGNORED = 0x80 | 0x7E
PICOBIN_BLOCK_ITEM_1BS_IMAGE_TYPE_EXE_ARM_SECURE = 0x10210142


@dataclass
class Segment:
    """One PT_LOAD segment. vaddr/memsz default to paddr/filez (RAM-style)."""

    paddr: int
    filez: int
    vaddr: int | None = None
    memsz: int | None = None
    data: bytes = b""

    def __post_init__(self):
        if self.vaddr is None:
            self.vaddr = self.paddr
        if self.memsz is None:
            self.memsz = self.filez
        assert len(self.data) <= self.filez


def _words(*ws: int) -> bytes:
    return struct.pack("<%dI" % len(ws), *(w & 0xFFFFFFFF for w in ws))


def image_def_block(next_block_rel: int) -> bytes:
    """A minimal IMAGE_DEF block (EXE, ARM, Secure) linking to next_block_rel."""
    return _words(
        PICOBIN_BLOCK_MARKER_START,
        PICOBIN_BLOCK_ITEM_1BS_IMAGE_TYPE_EXE_ARM_SECURE,
        PICOBIN_BLOCK_ITEM_2BS_LAST | (1 << 8),
        next_block_rel,
        PICOBIN_BLOCK_MARKER_END,
    )


def ignored_block(next_block_rel: int) -> bytes:
    """A minimal block containing a single IGNORED item, linking to next_block_rel."""
    return _words(
        PICOBIN_BLOCK_MARKER_START,
        PICOBIN_BLOCK_ITEM_2BS_IGNORED | (1 << 8),
        PICOBIN_BLOCK_ITEM_2BS_LAST | (1 << 8),
        next_block_rel,
        PICOBIN_BLOCK_MARKER_END,
    )


def build_elf(path: Path, segments: list[Segment]) -> Path:
    """Write a minimal ELF32 ARM executable with the given PT_LOAD segments.

    Includes a section per segment (PROGBITS for filez>0, NOBITS otherwise) so
    the file survives `remove_sh_holes` / signing, matching what a linker-built
    ELF looks like to picotool.
    """
    ph_num = len(segments)
    data_off = EH_SIZE + ph_num * PH_SIZE

    blob = b""
    seg_offs = []
    for s in segments:
        seg_offs.append(data_off + len(blob))
        blob += s.data + bytes(s.filez - len(s.data))

    shstrtab = b"\0"
    sh = [b"\0" * SH_SIZE]
    for i, s in enumerate(segments):
        name_off = len(shstrtab)
        shstrtab += f".seg{i}".encode() + b"\0"
        if s.filez:
            sh.append(struct.pack("<10I", name_off, 1, 2, s.vaddr, seg_offs[i], s.filez, 0, 0, 4, 0))
        else:
            sh.append(struct.pack("<10I", name_off, 8, 2, s.vaddr, data_off + len(blob), s.memsz, 0, 0, 4, 0))
    name_off = len(shstrtab)
    shstrtab += b".shstrtab\0"
    strtab_off = data_off + len(blob)
    sh.append(struct.pack("<10I", name_off, 3, 0, 0, strtab_off, len(shstrtab), 0, 0, 1, 0))
    sh_offset = strtab_off + len(shstrtab)

    common = struct.pack(
        "<IBBBBB7xHHI",
        0x464C457F,  # magic
        1, 1, 1, 0, 0,  # class32, LE, version, ABI none, ABI version
        2,     # ET_EXEC
        0x28,  # EM_ARM
        1,     # version2
    )
    hdr = common + struct.pack(
        "<IIIIHHHHHH",
        0x20000000,  # entry
        EH_SIZE,     # ph_offset
        sh_offset,
        0,           # flags
        EH_SIZE, PH_SIZE, ph_num,
        SH_SIZE, len(sh), len(sh) - 1,  # sh_str_index = last section
    )
    assert len(hdr) == EH_SIZE

    phs = b""
    for i, s in enumerate(segments):
        phs += struct.pack("<IIIIIIII", 1, seg_offs[i], s.vaddr, s.paddr, s.filez, s.memsz, 4, 4)

    path.write_bytes(hdr + phs + blob + shstrtab + b"".join(sh))
    return path


def read_load_segments(path: Path) -> list[tuple[int, int]]:
    """Read back (paddr, filez) for every PT_LOAD entry in an ELF32 file.

    `picotool info` reports picobin metadata, not raw ELF program headers, so
    verifying where store_squashed actually placed a segment means reading
    the ELF program header table directly.
    """
    data = path.read_bytes()
    # e_phoff(28,4) e_shoff(32,4) e_flags(36,4) e_ehsize(40,2) e_phentsize(42,2)
    # e_phnum(44,2) e_shentsize(46,2) e_shnum(48,2) e_shstrndx(50,2)
    ph_off = struct.unpack_from("<I", data, 28)[0]
    ph_entsize = struct.unpack_from("<H", data, 42)[0]
    ph_num = struct.unpack_from("<H", data, 44)[0]
    segments = []
    for i in range(ph_num):
        off = ph_off + i * ph_entsize
        p_type, _off, _vaddr, p_paddr, p_filesz, _memsz, _flags, _align = struct.unpack_from("<IIIIIIII", data, off)
        if p_type == 1:  # PT_LOAD
            segments.append((p_paddr, p_filesz))
    return segments


def overlapping_pairs(segments: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Pairs of (paddr, filez) segments whose physical ranges overlap.

    A non-empty result means squashing corrupted one segment's stored bytes
    by placing another segment on top of it.
    """
    sized = [(p, f) for p, f in segments if f > 0]
    pairs = []
    for i, (p1, f1) in enumerate(sized):
        for p2, f2 in sized[i + 1:]:
            if p1 < p2 + f2 and p2 < p1 + f1:
                pairs.append(((p1, f1), (p2, f2)))
    return pairs
