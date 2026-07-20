"""`picotool uf2 convert` / `uf2 combine` file operations (no hardware)."""
import pytest

CHIPS = ["rp2040", "rp2350"]
FAMILY = {"rp2040": "rp2040", "rp2350": "rp2350-arm-s"}


@pytest.fixture
def bset(require_binaries, chip):
    return require_binaries[chip]


@pytest.mark.parametrize("chip", CHIPS)
class TestUf2Convert:
    def test_elf_to_uf2(self, picotool, bset, tmp_path):
        out = tmp_path / "out.uf2"
        r = picotool.run("uf2", "convert", str(bset.path("blink.elf")), str(out))
        assert r.ok, r
        assert out.exists() and out.stat().st_size > 0

    def test_roundtrip_info_matches(self, picotool, bset, tmp_path):
        """An ELF converted to UF2 should report the same program via info."""
        out = tmp_path / "blink.uf2"
        assert picotool.run(
            "uf2", "convert", str(bset.path("blink.elf")), str(out)
        ).ok
        r_elf = picotool.run("info", "-a", str(bset.path("blink.elf")))
        r_uf2 = picotool.run("info", "-a", str(out))
        assert r_elf.ok and r_uf2.ok
        for key in ("binary start:", "binary end:"):
            assert key in r_uf2.out

    def test_bin_to_uf2(self, picotool, bset, chip, tmp_path):
        out = tmp_path / "frombin.uf2"
        r = picotool.run(
            "uf2", "convert",
            str(bset.path("blink.bin")), "-t", "bin",
            str(out),
            "--family", FAMILY[chip],
            "-o", "0x10000000",
        )
        assert r.ok, r
        assert out.exists() and out.stat().st_size > 0

    def test_convert_to_non_uf2_rejected(self, picotool, bset, tmp_path):
        # uf2 convert only produces UF2 output.
        out = tmp_path / "out.bin"
        r = picotool.run("uf2", "convert", str(bset.path("blink.elf")), str(out), "-t", "bin")
        assert not r.ok


@pytest.mark.parametrize("chip", CHIPS)
class TestUf2Combine:
    def test_combine_two(self, picotool, bset, tmp_path):
        out = tmp_path / "combined.uf2"
        r = picotool.run(
            "uf2", "combine",
            str(bset.path("blink.uf2")),
            str(bset.path("hello_usb.uf2")),
            str(out),
        )
        assert r.ok, r
        assert out.exists() and out.stat().st_size > 0


class TestUf2ConvertRegressions:
    def test_convert_image_not_at_flash_start(self, picotool, require_binaries, tmp_path):
        """Regression for #339: converting an RP2350 image whose lowest segment
        isn't at FLASH_START must not be mis-guessed as RP2040 and rejected.

        The RAM-only enter_bootsel_ram build lives entirely in SRAM (no segment
        at FLASH_START) and, on RP2350, uses RAM beyond the RP2040's range - so
        a wrong RP2040 guess would fail with 'outside of valid address range'.
        """
        ram_elf = require_binaries["rp2350"].tool("enter_bootsel_ram", "elf")
        if ram_elf is None:
            pytest.skip("enter_bootsel_ram not built")
        out = tmp_path / "ram.uf2"
        r = picotool.run("uf2", "convert", str(ram_elf), str(out))
        assert r.ok, r
        assert out.exists() and out.stat().st_size > 0
        assert "outside of valid address range" not in r.out

    def test_verbose_produces_output(self, picotool, require_binaries, tmp_path):
        """Regression for #185: `uf2 convert --verbose` must print output."""
        elf = str(require_binaries["rp2040"].path("blink.elf"))
        quiet = picotool.run("uf2", "convert", elf, str(tmp_path / "q.uf2"))
        verbose = picotool.run("uf2", "convert", "--verbose", elf, str(tmp_path / "v.uf2"))
        assert quiet.ok and verbose.ok
        assert len(verbose.out) > len(quiet.out)
        assert verbose.out.strip()
