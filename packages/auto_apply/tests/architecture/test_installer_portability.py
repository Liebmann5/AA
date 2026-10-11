"""Portability pins for the installers a non-technical person runs.

Measured 2026-10-07 on a stock Windows 11 PC: install.ps1 was UTF-8 without a
byte-order mark and contained em dashes. Windows PowerShell 5.1 reads such a
file as ANSI, so each em dash became three characters, one of them a curly
quote that closed a string early, and the whole script failed to parse. The
documented one-command install could not run on any stock Windows machine.

These pins keep every installer file readable by the oldest interpreter that
will ever open it, keep the double-click wrappers wired to the real
bootstraps, and keep the install contained to AA's own Python.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
REPO = PKG.parents[1]
INSTALL_PS1 = PKG / "install.ps1"
INSTALL_SH = PKG / "install.sh"
WIN_WRAPPER = REPO / "INSTALL-WINDOWS.bat"
MAC_WRAPPER = REPO / "INSTALL-MAC.command"
LINUX_WRAPPER = REPO / "INSTALL-LINUX.sh"

INSTALLER_FILES = (INSTALL_PS1, INSTALL_SH, WIN_WRAPPER, MAC_WRAPPER, LINUX_WRAPPER)
POSIX_FILES = (INSTALL_SH, MAC_WRAPPER, LINUX_WRAPPER)


@pytest.mark.parametrize("path", INSTALLER_FILES, ids=lambda p: p.name)
def test_installer_files_are_pure_ascii(path: Path) -> None:
    """TEETH: one non-ASCII byte breaks install.ps1 under Windows PowerShell
    5.1 and cmd.exe's reading of a .bat; the shell scripts follow the same
    rule so they read identically in every locale."""
    data = path.read_bytes()
    bad = sorted({(i, b) for i, b in enumerate(data) if b > 0x7F})
    assert not bad, (
        f"{path.name} contains non-ASCII bytes (first at offset {bad[0][0]}). "
        "Replace them with ASCII (an em dash becomes -, an arrow becomes ->)."
    )


def test_windows_wrapper_uses_crlf_only() -> None:
    """GUARD: cmd.exe mis-parses labels and gotos in a .bat with bare LF."""
    data = WIN_WRAPPER.read_bytes()
    assert b"\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n"), "bare LF in INSTALL-WINDOWS.bat"


@pytest.mark.parametrize("path", POSIX_FILES, ids=lambda p: p.name)
def test_posix_scripts_use_lf_only(path: Path) -> None:
    """GUARD: a CR in a shell script becomes part of every command name."""
    data = path.read_bytes()
    assert b"\r" not in data, f"{path.name} has CR line endings"
    assert data.startswith(b"#!/bin/sh\n")


def test_wrappers_start_the_real_bootstraps() -> None:
    """TEETH: each double-click wrapper runs the package bootstrap, from the
    folder it sits in, and asks for the shortcut so a person can find AA
    again without a terminal."""
    win = WIN_WRAPPER.read_text(encoding="ascii")
    assert r"packages\auto_apply\install.ps1" in win
    assert "-ExecutionPolicy Bypass" in win and "-Shortcut" in win
    assert "%~dp0" in win
    for wrapper in (MAC_WRAPPER, LINUX_WRAPPER):
        text = wrapper.read_text(encoding="ascii")
        assert "packages/auto_apply/install.sh" in text, wrapper.name
        assert "--shortcut" in text, wrapper.name
    assert (PKG / "install.ps1").exists() and (PKG / "install.sh").exists()


@pytest.mark.parametrize(
    ("path", "marker"),
    [(INSTALL_PS1, "$localRepo"), (INSTALL_SH, "LOCAL_REPO")],
    ids=["install.ps1", "install.sh"],
)
def test_bootstraps_install_from_the_folder_they_sit_in(path: Path, marker: str) -> None:
    """TEETH: run from an extracted download, the bootstrap installs that copy
    instead of demanding a release asset that may not exist."""
    text = path.read_text(encoding="ascii")
    assert marker in text
    assert "__main__.py" in text


@pytest.mark.parametrize("path", [INSTALL_PS1, INSTALL_SH], ids=lambda p: p.name)
def test_bootstraps_accommodate_the_computers_python(path: Path) -> None:
    """TEETH: a Python already on the computer runs the installer; uv
    downloads one (the pinned version) only when none exists; the installer
    runs from its own throwaway environment so AA's environment can be built
    on whichever Python python_choice.py picks; developer tools never ship."""
    text = path.read_text(encoding="ascii")
    assert "python find" in text and ">=3.10" in text
    assert "bootstrap-env" in text and "UV_PROJECT_ENVIRONMENT" in text
    assert "run --no-dev" in text


def test_macos_bootstrap_never_runs_the_developer_tools_stub() -> None:
    """GUARD: on a Mac without Apple's Command Line Tools, /usr/bin/python3
    and /usr/bin/git open a system install dialog when run. The bootstrap
    checks xcode-select first and then looks only at uv-managed Pythons."""
    text = INSTALL_SH.read_text(encoding="ascii")
    assert text.count("xcode-select -p") >= 2
    assert "UV_PYTHON_PREFERENCE=only-managed" in text


def test_posix_wrappers_are_executable_in_git() -> None:
    """GUARD: a .command without the executable bit cannot be double-clicked
    on macOS. Checked against the index, which is what a ZIP download gets."""
    git = shutil.which("git") or ""
    if not git or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(
        [git, "ls-files", "-s", "--", MAC_WRAPPER.name, LINUX_WRAPPER.name],
        cwd=REPO, capture_output=True, text=True, check=False,
    ).stdout
    modes = {line.split("\t")[1]: line.split()[0] for line in out.splitlines() if "\t" in line}
    if not modes:
        pytest.skip("wrappers not yet tracked")
    for name, mode in modes.items():
        assert mode == "100755", f"{name} is {mode} in git; run: git add --chmod=+x {name}"
