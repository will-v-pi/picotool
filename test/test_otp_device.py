"""OTP tests against a live device (RP2350 only).

OTP is One-Time-Programmable: rows can only ever be burned once, so the WRITE
tests here would permanently consume rows on a real chip. They are gated behind
`--run-otp` (see conftest) and are intended to be run ONLY against an FPGA,
whose OTP can be reset. Without the flag every test in this module is skipped.

Even the read-only tests (dump / get) are gated, per the project policy of not
poking OTP on real silicon during automated testing.

The scratch row used for write tests defaults to an unnamed general-purpose row;
override it with PICOTOOL_TEST_OTP_ROW for your particular FPGA image (the row
must not already be programmed - OTP is write-once).
"""
import json
import os
import re

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.rp2350, pytest.mark.otp]

# Unnamed general OTP data row (0x040). Override for your FPGA.
SCRATCH_ROW = os.environ.get("PICOTOOL_TEST_OTP_ROW", "0x040")
SCRATCH_VALUE = "0x1234"  # 16-bit ECC value

# Pages the permissions regression (#294) writes locks to. FPGA-resettable;
# override for your image if these collide with something you care about.
PERM_PAGES = os.environ.get("PICOTOOL_TEST_OTP_PAGES", "30,31,32").split(",")
# High page (>=32) lock row for #266; setting these used to fail.
HIGH_LOCK_ROW = os.environ.get("PICOTOOL_TEST_OTP_HIGH_LOCK_ROW", "OTP_DATA_PAGE53_LOCK1")


def _otp_raw(session, selector):
    """Read a single OTP row's raw value via `otp get --raw`."""
    r = session.ok("otp", "get", "--raw", selector)
    m = re.search(r"VALUE\s+0x([0-9a-fA-F]+)", r.out)
    if not m:
        m = re.search(r"RAW_VALUE=0x([0-9a-fA-F]+)", r.out)
    assert m, f"could not parse OTP value for {selector} from:\n{r.out}"
    return int(m.group(1), 16)


class TestOtpRead:
    def test_otp_dump(self, rp2350_board):
        with rp2350_board.bootsel() as dev:
            r = dev.run("otp", "dump", timeout=60)
            assert r.ok, r
            assert "ROW" in r.out

    def test_otp_dump_to_file(self, rp2350_board, tmp_path):
        out = tmp_path / "otp.dump"
        with rp2350_board.bootsel() as dev:
            r = dev.run("otp", "dump", "--output", str(out), timeout=60)
            assert r.ok, r
        assert out.exists() and out.stat().st_size > 0

    def test_otp_get_chipid(self, rp2350_board):
        with rp2350_board.bootsel() as dev:
            r = dev.run("otp", "get", "CHIPID0")
            assert r.ok, r
            assert "CHIPID0" in r.out


class TestOtpWrite:
    """These permanently burn OTP rows - FPGA only."""

    def test_otp_set_then_get(self, rp2350_board):
        with rp2350_board.bootsel() as dev:
            set_r = dev.run("otp", "set", SCRATCH_ROW, SCRATCH_VALUE, "-e")
            assert set_r.ok, set_r
            get_r = dev.run("otp", "get", SCRATCH_ROW, "-e")
            assert get_r.ok, get_r
            assert SCRATCH_VALUE.lower().lstrip("0x") in get_r.out.lower()

    def test_otp_load_from_file(self, rp2350_board, tmp_path):
        # 2 bytes/row for ECC data.
        data = tmp_path / "rows.bin"
        data.write_bytes(bytes([0xAA, 0x55]))
        with rp2350_board.bootsel() as dev:
            r = dev.run(
                "otp", "load", "-e", "-s", SCRATCH_ROW, str(data), "-t", "bin"
            )
            assert r.ok, r


class TestOtpIssueRegressions:
    """Regressions for specific OTP bugs. All burn OTP - FPGA only.

    OTP is write-once, so these assume a fresh (or reset) FPGA image: the rows /
    pages they touch must not already be programmed.
    """

    def test_permissions_are_per_page(self, rp2350_board, tmp_path):
        """Regression for #294: `otp permissions` must compute each page's lock
        independently, not accumulate one page's value into the others.

        Two pages given the *same* permissions must end up equal, and a third
        page with *different* permissions must differ. The bug made all pages
        take the first page's (accumulated) value.
        """
        p_a, p_b, p_c = PERM_PAGES
        perms = {
            p_a: {"lock_ns": 3, "lock_s": 1, "lock_bl": 3},
            p_b: {"lock_ns": 1, "lock_s": 1},
            p_c: {"lock_ns": 1, "lock_s": 1},
        }
        pf = tmp_path / "perms.json"
        pf.write_text(json.dumps(perms))
        with rp2350_board.bootsel() as dev:
            dev.ok("otp", "permissions", str(pf))
            a = (_otp_raw(dev, f"PAGE{p_a}_LOCK0"), _otp_raw(dev, f"PAGE{p_a}_LOCK1"))
            b = (_otp_raw(dev, f"PAGE{p_b}_LOCK0"), _otp_raw(dev, f"PAGE{p_b}_LOCK1"))
            c = (_otp_raw(dev, f"PAGE{p_c}_LOCK0"), _otp_raw(dev, f"PAGE{p_c}_LOCK1"))
        assert b == c, f"pages with identical perms differ: {b} vs {c}"
        assert a != b, f"page with different perms was not applied independently: {a} == {b}"

    def test_set_high_page_lock(self, rp2350_board):
        """Regression for #266: setting page locks for pages 32-63 must not fail
        with 'permission failure'."""
        with rp2350_board.bootsel() as dev:
            r = dev.run("otp", "set", "--raw", HIGH_LOCK_ROW, "0x3d3d3d")
            assert r.ok, r
            assert "permission failure" not in r.out

    @pytest.mark.xfail(
        reason="#330 open: picotool won't set a bit in a redundant (RBIT) row "
        "when the redundant copies disagree (majority 0, main 1)",
        strict=False,
    )
    def test_redundant_row_bit_update(self, rp2350_board):
        """Regression for #330 (OPEN).

        Setting a field that lives in a redundant (RBIT-n) row should update the
        field even when the redundant copies currently disagree. Opt-in only:
        set PICOTOOL_TEST_OTP_RBIT_FIELD to a SAFE, non-security-critical RBIT
        field for your FPGA image (do NOT point this at debug/secure-boot flags).
        """
        field = os.environ.get("PICOTOOL_TEST_OTP_RBIT_FIELD")
        if not field:
            pytest.skip(
                "set PICOTOOL_TEST_OTP_RBIT_FIELD to a safe non-critical RBIT "
                "field to exercise #330"
            )
        with rp2350_board.bootsel() as dev:
            dev.ok("otp", "set", field, "1")
            r = dev.run("otp", "get", field)
            assert r.ok, r
            assert re.search(r"\b=\s*1\b", r.out) or "VALUE 0x1" in r.out
