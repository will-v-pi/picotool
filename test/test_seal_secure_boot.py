"""File-based tests for `picotool seal` - hashing, signing (secure boot) and
rollback-version metadata. RP2350-only (secure boot / OTP are RP2350 features;
seal itself is documented as being "to run on RP2350"), and needs no hardware -
everything here operates on files only.

These exist alongside the on-device secure-boot/rollback tests in
test_otp_secure_boot.py: this file proves picotool's own seal/verify logic is
correct (signing, hashing, rollback-metadata validation, tamper detection);
that file proves the *device* actually enforces what gets provisioned.
"""
import json
import subprocess

import pytest

pytestmark = pytest.mark.rp2350

# seal requires a secp256k1 PEM key (see README's seal section).
SECP256K1 = "secp256k1"


def _genkey(path):
    subprocess.run(
        ["openssl", "ecparam", "-name", SECP256K1, "-genkey", "-out", str(path)],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def keypair(tmp_path):
    return _genkey(tmp_path / "a.pem"), _genkey(tmp_path / "b.pem")


@pytest.fixture
def elf(require_binaries):
    # hello_usb (not blink): later, device-level tests need a USB-visible
    # program so a successful boot is observable without extra hardware.
    return require_binaries["rp2350"].path("hello_usb.elf")


def _flip_byte_in_first_segment(src_elf, dst_elf):
    """Corrupt one byte inside the first PT_LOAD segment's *file* content.

    Deliberately not just "some early file offset": ELF headers/program
    headers/non-loaded sections precede and separate the loadable segments, and
    a byte flipped there doesn't touch what actually gets hashed/signed
    (confirmed by hand - flipping bytes outside an actual PT_LOAD segment left
    seal's signature/hash check reporting "verified" instead of "incorrect").
    0x2000 sits inside hello_usb's first (R E, code) PT_LOAD segment, which
    spans roughly file offset 0x1000-0x5000.
    """
    data = bytearray(open(src_elf, "rb").read())
    data[0x2000] ^= 0xFF
    open(dst_elf, "wb").write(data)


class TestSealHash:
    def test_hash_verifies(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "hashed.elf"
        r = picotool.run("seal", "--hash", str(elf), str(out), str(key_a))
        assert r.ok, r
        info = picotool.run("info", "-a", str(out))
        assert info.ok, info
        assert "hash:" in info.out and "verified" in info.out

    def test_hash_detects_tampering(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "hashed.elf"
        assert picotool.run("seal", "--hash", str(elf), str(out), str(key_a)).ok
        tampered = tmp_path / "tampered.elf"
        _flip_byte_in_first_segment(out, tampered)
        info = picotool.run("info", "-a", str(tampered))
        assert info.ok, info
        assert "hash:" in info.out and "incorrect" in info.out

    def test_hash_alone_does_not_configure_secure_boot(self, picotool, elf, keypair, tmp_path):
        """Hashing (no --sign) has nothing to do with secure boot - it must not
        produce any OTP content (in particular, must never suggest enabling
        CRIT1.SECURE_BOOT_ENABLE)."""
        key_a, _ = keypair
        out = tmp_path / "hashed.elf"
        otp_json = tmp_path / "otp.json"
        assert picotool.run("seal", "--hash", str(elf), str(out), str(key_a), str(otp_json)).ok
        assert not otp_json.exists() or otp_json.stat().st_size == 0


class TestSealSign:
    def test_sign_verifies(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "signed.elf"
        r = picotool.run("seal", "--sign", str(elf), str(out), str(key_a))
        assert r.ok, r
        info = picotool.run("info", "-a", str(out))
        assert info.ok, info
        assert "signature:" in info.out and "verified" in info.out

    def test_sign_detects_tampering(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "signed.elf"
        assert picotool.run("seal", "--sign", str(elf), str(out), str(key_a)).ok
        tampered = tmp_path / "tampered.elf"
        _flip_byte_in_first_segment(out, tampered)
        info = picotool.run("info", "-a", str(tampered))
        assert info.ok, info
        assert "signature:" in info.out and "incorrect" in info.out

    def test_sign_produces_provisioning_otp_json(self, picotool, elf, keypair, tmp_path):
        """seal --sign's generated otp.json is the exact artifact that would be
        burned onto a device (via `otp load`) to make it trust this key - so its
        shape matters a lot. Expect: a 32-byte bootkey hash, KEY_VALID set, and
        secure boot enabled."""
        key_a, _ = keypair
        out = tmp_path / "signed.elf"
        otp_json = tmp_path / "otp.json"
        assert picotool.run("seal", "--sign", str(elf), str(out), str(key_a), str(otp_json)).ok
        assert otp_json.exists()
        data = json.loads(otp_json.read_text())

        assert data.get("crit1", {}).get("secure_boot_enable") == 1
        assert data.get("boot_flags1", {}).get("key_valid") == 1

        bootkey_entries = [k for k in data if k.startswith("bootkey")]
        assert len(bootkey_entries) == 1, f"expected exactly one bootkey entry, got {bootkey_entries}"
        key_bytes = data[bootkey_entries[0]]
        assert len(key_bytes) == 32, "boot key hash should be 32 bytes (SHA-256)"
        assert all(isinstance(b, int) and 0 <= b <= 255 for b in key_bytes)

    def test_different_keys_produce_different_bootkey_hash(self, picotool, elf, keypair, tmp_path):
        key_a, key_b = keypair
        otp_a, otp_b = tmp_path / "a.json", tmp_path / "b.json"
        assert picotool.run(
            "seal", "--sign", str(elf), str(tmp_path / "sa.elf"), str(key_a), str(otp_a)
        ).ok
        assert picotool.run(
            "seal", "--sign", str(elf), str(tmp_path / "sb.elf"), str(key_b), str(otp_b)
        ).ok
        data_a = json.loads(otp_a.read_text())
        data_b = json.loads(otp_b.read_text())
        key_a_bytes = next(v for k, v in data_a.items() if k.startswith("bootkey"))
        key_b_bytes = next(v for k, v in data_b.items() if k.startswith("bootkey"))
        assert key_a_bytes != key_b_bytes


class TestSealRollback:
    def test_rollback_requires_sign(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "out.elf"
        r = picotool.run(
            "seal", str(elf), str(out), str(key_a), str(tmp_path / "otp.json"), "--rollback", "5"
        )
        assert not r.ok
        assert "must sign" in r.out.lower()

    def test_rollback_embeds_version_and_default_rows(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "signed.elf"
        r = picotool.run(
            "seal", "--sign", str(elf), str(out), str(key_a),
            str(tmp_path / "otp.json"), "--rollback", "5",
        )
        assert r.ok, r
        info = picotool.run("info", "-a", str(out))
        assert info.ok, info
        assert "rollback version:" in info.out and "5" in info.out
        # OTP_DATA_DEFAULT_BOOT_VERSION0/1 - picotool's default rollback rows.
        assert "0x04e" in info.out and "0x051" in info.out

    def test_rollback_insufficient_default_rows_rejected(self, picotool, elf, keypair, tmp_path):
        """Each RBIT3 row holds 24 rollback increments; the 2 default rows only
        cover versions up to 47, so version 50 (needing a 3rd row) must be
        rejected rather than silently truncated."""
        key_a, _ = keypair
        r = picotool.run(
            "seal", "--sign", str(elf), str(tmp_path / "out.elf"), str(key_a),
            str(tmp_path / "otp.json"), "--rollback", "50",
        )
        assert not r.ok
        assert "requires 3 rows" in r.out

    def test_rollback_custom_rows_too_close_rejected(self, picotool, elf, keypair, tmp_path):
        """Rollback rows are RBIT3 and must be >=3 rows apart."""
        key_a, _ = keypair
        r = picotool.run(
            "seal", "--sign", str(elf), str(tmp_path / "out.elf"), str(key_a),
            str(tmp_path / "otp.json"), "--rollback", "10", "0x100", "0x101",
        )
        assert not r.ok
        assert "too close" in r.out

    def test_rollback_custom_rows_accepted(self, picotool, elf, keypair, tmp_path):
        key_a, _ = keypair
        out = tmp_path / "signed.elf"
        r = picotool.run(
            "seal", "--sign", str(elf), str(out), str(key_a),
            str(tmp_path / "otp.json"), "--rollback", "10", "0x100", "0x103",
        )
        assert r.ok, r
        info = picotool.run("info", "-a", str(out))
        assert "rollback version:" in info.out and "10" in info.out
        assert "0x100" in info.out and "0x103" in info.out
