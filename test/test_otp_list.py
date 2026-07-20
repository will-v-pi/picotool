"""`picotool otp list` - reads the built-in OTP layout, needs no device.

These run unconditionally (no --run-otp required) because they never touch a
chip's OTP; they only exercise picotool's knowledge of the RP2350 OTP map.
"""
import pytest

pytestmark = pytest.mark.otp


def test_otp_list_all(picotool):
    r = picotool.run("otp", "list")
    assert r.ok, r
    rows = [ln for ln in r.out.splitlines() if ln.startswith("ROW")]
    assert len(rows) > 100, f"expected a large OTP map, got {len(rows)} rows"


def test_otp_list_known_row(picotool):
    r = picotool.run("otp", "list", "CHIPID0")
    assert r.ok, r
    assert "CHIPID0" in r.out
    assert "ROW 0x0000" in r.out


def test_otp_list_names_only(picotool):
    # -n restricts output to names (no descriptions)
    r = picotool.run("otp", "list", "-n")
    assert r.ok, r
    assert "ROW" in r.out


def test_otp_list_bootkey(picotool):
    r = picotool.run("otp", "list", "BOOTKEY0")
    assert r.ok, r
    assert "BOOTKEY0" in r.out


def test_otp_list_row_one(picotool):
    """Regression for #296: row 1 (0x0001) must be listed, not skipped."""
    r = picotool.run("otp", "list", "1")
    assert r.ok, r
    assert "ROW 0x0001" in r.out
