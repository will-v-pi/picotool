"""`picotool info` / `config` against binary FILES (no hardware needed)."""
import pytest

CHIPS = ["rp2040", "rp2350"]
EXTS = ["elf", "uf2", "bin"]


@pytest.fixture
def bset(require_binaries, chip):
    return require_binaries[chip]


@pytest.mark.parametrize("chip", CHIPS)
class TestInfoFromFile:
    @pytest.mark.parametrize("ext", EXTS)
    def test_info_all(self, picotool, bset, ext):
        f = bset.path(f"blink.{ext}")
        r = picotool.run("info", "-a", str(f))
        assert r.ok, r
        assert "Program Information" in r.out
        assert "name:" in r.out and "blink" in r.out

    @pytest.mark.parametrize("ext", EXTS)
    def test_info_reports_binary_range(self, picotool, bset, ext):
        f = bset.path(f"blink.{ext}")
        r = picotool.run("info", "-a", str(f))
        assert r.ok, r
        assert "binary start:" in r.out
        assert "binary end:" in r.out

    def test_info_build_attributes(self, picotool, bset):
        # -l / --build includes build attributes such as the SDK version.
        r = picotool.run("info", "-l", str(bset.path("hello_anything.elf")))
        assert r.ok, r
        assert "sdk version:" in r.out

    def test_info_pins(self, picotool, bset):
        # -p prints pin information; hello_anything declares UART pins.
        r = picotool.run("info", "-p", str(bset.path("hello_anything.uf2")))
        assert r.ok, r

    def test_info_rich_metadata(self, picotool, bset):
        # hello_anything embeds lots of binary_info; -a should surface it.
        r = picotool.run("info", "-a", str(bset.path("hello_anything.elf")))
        assert r.ok, r
        assert "hello_anything" in r.out

    def test_info_missing_file_fails(self, picotool, bset):
        r = picotool.run("info", "-a", "does-not-exist.elf")
        assert not r.ok


@pytest.mark.parametrize("chip", CHIPS)
class TestConfigFromFile:
    def test_config_lists_settings(self, picotool, bset):
        # hello_anything registers a named string + feature flags.
        r = picotool.run("config", str(bset.path("hello_anything.uf2")))
        assert r.ok, r
        assert "text" in r.out


class TestInfoRegressions:
    def test_rp2040_reports_boot2(self, require_binaries, picotool):
        """Regression for #15: RP2040 binaries report their boot2 stage."""
        r = picotool.run("info", "-a", str(require_binaries["rp2040"].path("blink.elf")))
        assert r.ok, r
        assert "boot2_name:" in r.out

    @pytest.mark.parametrize("name", ["blink_universal", "nuke_universal"])
    def test_info_universal_binary(self, picotool, name):
        """Regression for #112: info on a multi-family (universal) binary must
        not fail with 'Found overlapping memory ranges'."""
        from lib.binaries import universal_binary

        uf2 = universal_binary(name)
        if uf2 is None:
            pytest.skip(f"{name}.uf2 not downloaded - run fetch_firmware.sh")
        r = picotool.run("info", "-a", str(uf2))
        assert r.ok, r
        assert "overlapping memory" not in r.out
