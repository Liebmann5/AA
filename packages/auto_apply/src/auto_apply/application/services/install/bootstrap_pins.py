"""Reader for install_pins.txt — the ONE source of truth for bootstrap pins.

uv version and checksums, the pinned Python, the release coordinates and the
download-size estimates live in that one file, read by install.sh,
install.ps1 AND this module. tests/architecture/test_install_pins_parity.py
asserts all three agree and that no version literal lives anywhere else.

Two consumers need more than the raw map: both bootstraps and --install
need the uv target triple for this machine, the download URL derived from
it, and the checksum for it. Those derivations live here, once.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# bootstrap_pins.py → install → services → application → auto_apply → src
# → packages/auto_apply
DEFAULT_PINS_PATH = Path(__file__).resolve().parents[5] / "install_pins.txt"

REQUIRED_KEYS: tuple[str, ...] = (
    "UV_VERSION",
    "PYTHON_VERSION",
    "AA_RELEASE_REPO",
    "AA_ARCHIVE_ASSET",
)

_SYSTEM_NAMES = {"darwin": "Darwin", "linux": "Linux", "win32": "Windows"}
_MACHINE_NAMES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "arm64": "arm64",
    "aarch64": "arm64",
}

_UV_TARGETS: dict[tuple[str, str], str] = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "arm64"): "aarch64-pc-windows-msvc",
}


def load_pins(path: Path = DEFAULT_PINS_PATH) -> dict[str, str]:
    """Parse the KEY=VALUE pins file. Comments (#) and blanks are skipped."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"malformed line in {path}: {raw!r}")
        pins[key.strip()] = value.strip()
    missing = [k for k in REQUIRED_KEYS if k not in pins]
    if missing:
        raise ValueError(f"{path} is missing required keys: {', '.join(missing)}")
    return pins


def uv_target(system: str, machine: str) -> str:
    """The uv release target triple for this machine.

    system: a sys.platform value ("darwin"/"linux"/"win32"). machine: a
    platform.machine() value. Raises ValueError for anything else — the
    bootstrap scripts carry the same table and the parity pin keeps them
    from drifting.
    """
    sys_name = _SYSTEM_NAMES.get(system, system)
    machine_name = _MACHINE_NAMES.get(machine.lower(), machine)
    try:
        return _UV_TARGETS[(sys_name, machine_name)]
    except KeyError:
        raise ValueError(
            f"unsupported platform for a managed uv install: {system}/{machine}"
        ) from None


def uv_download_url(pins: dict[str, str], target: str) -> str:
    ext = ".zip" if "windows" in target else ".tar.gz"
    return (
        "https://github.com/astral-sh/uv/releases/download/"
        f"{pins['UV_VERSION']}/uv-{target}{ext}"
    )


def uv_checksum_key(target: str) -> str:
    return "UV_SHA256_" + target.upper().replace("-", "_")


def is_placeholder_checksum(value: str) -> bool:
    """True for the REPLACE_* placeholders and anything not 64 hex chars.

    A placeholder must stop the install, never verify it: an unverifiable
    executable is never run (the pins file's own comment says so).
    """
    v = value.strip().lower()
    return not (len(v) == 64 and all(c in "0123456789abcdef" for c in v))


def uv_checksum(pins: dict[str, str], target: str) -> str | None:
    """The pinned digest for a target, or None when it is a placeholder."""
    value = pins.get(uv_checksum_key(target), "")
    return None if is_placeholder_checksum(value) else value.strip().lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
