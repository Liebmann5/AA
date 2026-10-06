"""Parity pins: install_pins.txt is the ONE source of truth for the
bootstrap pins, read by install.sh, install.ps1 and Python alike.

A version literal in a shell script or a second parser in Python is how the
three readers drift — this file fails on any of them.
"""
from __future__ import annotations

import re
from pathlib import Path

from auto_apply.application.services.install.bootstrap_pins import (
    DEFAULT_PINS_PATH,
    REQUIRED_KEYS,
    is_placeholder_checksum,
    load_pins,
)

PKG = Path(__file__).resolve().parents[2]
INSTALL_SH = PKG / "install.sh"
INSTALL_PS1 = PKG / "install.ps1"
SRC = PKG / "src" / "auto_apply"

_VERSION_LITERAL = re.compile(r"UV_VERSION\s*=\s*[\"']?\d")


def test_pins_file_is_wellformed() -> None:
    """GUARD: required keys, plausible versions, checksums real-or-placeholder."""
    pins = load_pins(DEFAULT_PINS_PATH)
    for key in REQUIRED_KEYS:
        assert pins[key], key
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins["UV_VERSION"])
    assert re.fullmatch(r"3\.12\.\d+", pins["PYTHON_VERSION"]), (
        "CI tests 3.10 and 3.12 — the pinned Python must be a CI-proven line"
    )
    checksum_keys = [k for k in pins if k.startswith("UV_SHA256_")]
    assert len(checksum_keys) == 6
    for key in checksum_keys:
        assert is_placeholder_checksum(pins[key]) or re.fullmatch(
            r"[0-9a-fA-F]{64}", pins[key]
        ), key


def test_install_sh_reads_the_one_pins_file() -> None:
    """TEETH (parity): the sh bootstrap reads install_pins.txt and carries no
    version literal of its own."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "install_pins.txt" in text
    assert not _VERSION_LITERAL.search(text), (
        "install.sh hardcodes a uv version — the pins file is the one source"
    )
    assert "UV_SHA256_" in text


def test_install_ps1_reads_the_one_pins_file() -> None:
    """TEETH (parity): the ps1 bootstrap reads install_pins.txt and carries
    no version literal of its own."""
    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert "install_pins.txt" in text
    assert not _VERSION_LITERAL.search(text), (
        "install.ps1 hardcodes a uv version — the pins file is the one source"
    )
    assert "UV_SHA256_" in text


def test_the_python_parser_agrees_with_the_raw_file() -> None:
    """GUARD: load_pins() returns exactly what the file says (no silent
    defaults, no dropped keys beyond comments/blanks)."""
    pins = load_pins(DEFAULT_PINS_PATH)
    raw_keys = set()
    for line in DEFAULT_PINS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            raw_keys.add(line.split("=", 1)[0].strip())
    assert set(pins) == raw_keys
    assert pins["UV_VERSION"] and pins["PYTHON_VERSION"]


def test_no_uv_version_literal_anywhere_in_python() -> None:
    """RATCHET: no .py under src may pin a uv version — the pins file alone
    may (a Python file assigning one is the drift this pin exists to catch)."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if _VERSION_LITERAL.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == []
