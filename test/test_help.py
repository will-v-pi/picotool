"""Help / version output. These need neither hardware nor built binaries."""
import re

import pytest

TOP_COMMANDS = [
    "info",
    "config",
    "load",
    "save",
    "verify",
    "erase",
    "reboot",
    "partition",
    "uf2",
    "otp",
    "coprodis",
    "link",
    "bdev",
    "version",
    "help",
]

SUBCOMMANDS = [
    ("partition", "info"),
    ("partition", "create"),
    ("uf2", "convert"),
    ("uf2", "combine"),
    ("uf2", "info"),
    ("otp", "get"),
    ("otp", "set"),
    ("otp", "load"),
    ("otp", "white-label"),
    ("otp", "permissions"),
    ("otp", "dump"),
    ("otp", "list"),
    ("bdev", "ls"),
    ("bdev", "mkdir"),
    ("bdev", "cp"),
    ("bdev", "rm"),
    ("bdev", "cat"),
    ("bdev", "format"),
]


def test_bare_help(picotool):
    r = picotool.run("help")
    assert r.ok, r
    assert "COMMANDS:" in r.out
    # every advertised top-level command should be mentioned
    for cmd in TOP_COMMANDS:
        assert re.search(rf"\b{re.escape(cmd)}\b", r.out), f"{cmd} missing from help"


@pytest.mark.parametrize("cmd", TOP_COMMANDS)
def test_help_for_command(picotool, cmd):
    r = picotool.run("help", cmd)
    assert r.ok, r
    assert r.out.strip(), f"empty help for {cmd}"


@pytest.mark.parametrize("cmd,sub", SUBCOMMANDS)
def test_help_for_subcommand(picotool, cmd, sub):
    # `picotool help <cmd>` documents subcommands; make sure the subcommand is
    # named in the parent's help output.
    r = picotool.run("help", cmd)
    assert r.ok, r
    assert sub in r.out, f"{cmd} help does not mention subcommand {sub}"


def test_version(picotool):
    r = picotool.run("version")
    assert r.ok, r
    assert re.search(r"\bv?\d+\.\d+\.\d+", r.out), r


def test_version_short(picotool):
    r = picotool.run("version", "-s")
    assert r.ok, r
    assert re.match(r"^v?\d+\.\d+\.\d+", r.out.strip()), r


def test_unknown_command_fails(picotool):
    r = picotool.run("definitely-not-a-command")
    assert not r.ok, "unknown command should fail"
