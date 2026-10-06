---
title: Installing AutoApply
status: reviewed
last_verified: 2026-10-06
verified_against: "install.sh / install.ps1 / application/services/install/engine.py"
audience: users
---

# Installing AutoApply

You need **nothing installed first**: no Python, no developer tools, no
administrator rights. One command does the rest, and everything lands in one
folder (default `~/.auto_apply` on macOS/Linux, `%USERPROFILE%\.auto_apply`
on Windows).

## The one command

=== "Windows"

    ```powershell
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Liebmann5/AA/main/packages/auto_apply/install.ps1 | iex"
    ```

=== "macOS"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/Liebmann5/AA/main/packages/auto_apply/install.sh | sh
    ```

=== "Linux"

    ```bash
    curl -fsSL https://raw.githubusercontent.com/Liebmann5/AA/main/packages/auto_apply/install.sh | sh
    ```

On a Mac this **never** triggers the Command Line Tools prompt: no `git`, no
compiler — prebuilt packages only.

## What the installer asks

Before anything is downloaded you see, and must confirm:

- what will be downloaded (uv, a uv-managed Python, the AA source, the core
  dependencies), with approximate sizes;
- where it will go (always inside the AA folder);
- that nothing is installed system-wide and no administrator rights are used.

uv and Python are verified against pinned checksums (`install_pins.txt` in
the repository), and the source archive is verified against the release's
`SHA256SUMS.txt`. A failed verification deletes the download and stops the
install with a plain explanation — that is the safety property working. A
release without the checksum file makes the installer REFUSE;
`--allow-unverified-source` is the explicit, printed opt-out.

Your **browser is detected, never installed.** Install Chrome, Firefox or
Edge yourself; AA requires one and will say so honestly if none is found.

## Optional extras

`--extra NAME` (repeatable), or tick boxes in the GUI installer. An extra
that cannot install on your machine is **named and skipped**, never offered:

| Extra | macOS Intel | macOS Apple Silicon (< 14) | macOS Apple Silicon (14+) | Windows / Linux |
| --- | --- | --- | --- | --- |
| `semantic` | ✗ no PyTorch wheel | ✗ no PyTorch wheel | ✓ | ✓ |
| `captcha` | ✗ no vosk wheel | ✗ | ✗ | ✓ |
| others (`nlp`, `browser`, `ai`, `stealth`, `research`) | ✓ | ✓ | ✓ | ✓ |

## Offline and USB

```bash
install.sh --root /media/usb/AutoApply --archive AA-src.tar.gz --offline
```

installs from a pre-populated folder with no network. Prepare one copy **per
operating system** — uv and Python builds are per-platform.

## Repairing

Re-running the installer (or `auto-apply --install`, or **File → Install /
Repair…** in the app) checks every component and repairs what is missing.
It never duplicates.

## Where everything lives

```
~/.auto_apply/
├── uv/           the installer/runtime
├── python/       the uv-managed Python (not on PATH, not registered)
├── uv-cache/
├── app/          the AA source
├── bin/          the launcher (auto-apply / auto-apply.bat)
└── data/         your profiles, database, logs, research data
```

Uninstalling is one command away: see [Uninstalling AutoApply](uninstalling.md).
Then continue with [Quick Start](../getting_started/quick_start.md).
