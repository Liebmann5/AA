"""Which Python AA's environment is built on — the host's, or AA's own.

AA accommodates the computer it lands on (ENGINEERING_PHILOSOPHY principle
1): a suitable Python that is already installed is used as found, recorded
as pre-existing and never touched by uninstall. AA downloads its own
(uv-managed, inside the AA root, tkinter bundled) only when the computer has
no suitable one — and only with the consent the install plan already asked
for.

"Suitable" is feature detection, not a version guess: each candidate is RUN
once with a tiny probe and must report CPython >= 3.10 on this machine's
architecture with working ssl and sqlite3. A candidate without tkinter can
still run AA (the CLI needs no GUI toolkit), so it is chosen only when no
better option exists, and the report says what that costs.

Order of preference, first match wins:
  1. what the person asked for (--python managed | --python PATH);
  2. the Python an earlier install chose, while it still passes the probe
     (a repair never silently switches interpreters);
  3. a host Python with tkinter — CI-proven minors (3.12, 3.10) first,
     then the newest;
  4. AA's own Python, already present in the root;
  5. AA's own Python, downloaded (refused when offline);
  6. offline only: a host Python without tkinter, CLI-only, said plainly.

macOS: /usr/bin/python3 is a stub until Apple's Command Line Tools are
installed, and merely running it opens a system install dialog. Without
the tools, host discovery is skipped entirely (uv is asked for managed
Pythons only), so AA never triggers that dialog.

Pure decision + one injected runner: the pins run without a real Python.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any

#: Minors CI exercises on all three operating systems (ci.yml matrix).
CI_PROVEN_MINORS: tuple[tuple[int, int], ...] = ((3, 12), (3, 10))
MIN_VERSION: tuple[int, int] = (3, 10)

#: Run inside each candidate. Prints one JSON line; never raises.
PROBE_SOURCE = (
    "import json,platform,sys\n"
    "r={'v':list(sys.version_info[:3]),'impl':platform.python_implementation(),"
    "'bits':64 if sys.maxsize>2**32 else 32}\n"
    "for m in ('ssl','sqlite3','tkinter'):\n"
    "    try:\n"
    "        __import__(m);r[m]=True\n"
    "    except Exception:\n"
    "        r[m]=False\n"
    "print(json.dumps(r))\n"
)


@dataclass(frozen=True)
class Candidate:
    path: Path
    version: tuple[int, int, int]
    has_tk: bool
    managed: bool  # inside the AA root's python/ folder


@dataclass(frozen=True)
class PythonChoice:
    kind: str  # "host" | "managed"
    path: Path | None  # host: the interpreter; managed: None (uv resolves it)
    version: str  # "3.12.15"
    has_tk: bool
    download: bool  # managed and not yet present
    notes: tuple[str, ...] = ()

    @property
    def origin(self) -> str:
        return "aa" if self.kind == "managed" else "preexisting"


class PythonChoiceError(RuntimeError):
    """No usable Python, said in plain words."""


def macos_tools_present(runner: Callable[..., Any]) -> bool:
    """True when Apple's developer tools are installed (xcode-select -p
    prints a directory that exists). xcode-select -p itself never prompts."""
    try:
        result = runner(["xcode-select", "-p"])
    except (OSError, ValueError):
        return False
    out = str(getattr(result, "stdout", "") or "").strip()
    return getattr(result, "returncode", 1) == 0 and bool(out) and Path(out).exists()


def _probe(runner: Callable[..., Any], path: Path) -> dict | None:
    try:
        # -I: ignore the person's environment and site-packages; -B: never
        # write bytecode into that Python's own folders.
        result = runner([str(path), "-I", "-B", "-c", PROBE_SOURCE], timeout=60)
    except Exception:  # noqa: BLE001 — a probe must not crash the install
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    for raw_line in str(getattr(result, "stdout", "") or "").splitlines():
        line = raw_line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
    return None


def _in_a_venv(path: Path) -> bool:
    """An interpreter inside some virtual environment is never a base: it
    disappears when that environment is deleted."""
    return (path.parent / "pyvenv.cfg").exists() or (path.parent.parent / "pyvenv.cfg").exists()


def _within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
        return True
    except ValueError:
        return False


def discover(
    *,
    uv: Path,
    uv_env: dict[str, str],
    runner: Callable[..., Any],
    managed_dir: Path,
    host_discovery: bool,
    expected_bits: int = 64,
) -> list[Candidate]:
    """Every installed CPython uv can see, probed. Host Pythons are listed
    only when host_discovery is True (see the macOS note above)."""
    env = dict(uv_env)
    if not host_discovery:
        env["UV_PYTHON_PREFERENCE"] = "only-managed"
    # uv prints a path relative to its working directory when the path lies
    # beneath it (measured 2026-10-10) - so run it from a known directory and
    # resolve every path against that same directory.
    cwd = managed_dir.parent if managed_dir.parent.is_dir() else Path(os.getcwd())
    try:
        result = runner(
            [str(uv), "python", "list", "--only-installed", "--output-format", "json"],
            env=env,
            cwd=str(cwd),
        )
        rows = json.loads(str(getattr(result, "stdout", "") or "[]") or "[]")
    except Exception:  # noqa: BLE001 — discovery failing means "none found"
        return []
    if not isinstance(rows, list):
        return []
    seen: set[str] = set()
    out: list[Candidate] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("implementation") != "cpython":
            continue
        if row.get("variant", "default") != "default":
            continue  # free-threaded and debug builds are untested
        raw = row.get("path")
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = Path(os.path.abspath(cwd / path))
        key = os.path.normcase(os.path.realpath(path))
        if key in seen or _in_a_venv(path):
            continue
        seen.add(key)
        data = _probe(runner, path)
        if data is None or data.get("impl") != "CPython":
            continue
        version = tuple(int(x) for x in data.get("v", [0, 0, 0])[:3])
        if len(version) != 3 or version[:2] < MIN_VERSION:
            continue
        if not (data.get("ssl") and data.get("sqlite3")):
            continue
        if int(data.get("bits", 0)) != expected_bits:
            continue
        out.append(
            Candidate(
                path=path,
                version=(version[0], version[1], version[2]),
                has_tk=bool(data.get("tkinter")),
                managed=_within(path, managed_dir),
            )
        )
    return out


def _rank(c: Candidate) -> tuple[int, int, tuple[int, int, int]]:
    proven = len(CI_PROVEN_MINORS) - CI_PROVEN_MINORS.index(c.version[:2]) if c.version[:2] in CI_PROVEN_MINORS else 0
    return (1 if c.has_tk else 0, proven, c.version)


def _vtext(v: tuple[int, int, int]) -> str:
    return ".".join(str(p) for p in v)


def choose(
    candidates: list[Candidate],
    *,
    pinned_version: str,
    requested: str | None,
    previous: str | None,
    offline: bool,
    host_discovery: bool,
    managed_present: bool = False,
) -> PythonChoice:
    """The decision. Pure: same inputs, same answer."""
    hosts = sorted((c for c in candidates if not c.managed), key=_rank, reverse=True)
    managed = [c for c in candidates if c.managed]
    managed_here = managed_present or any(_vtext(c.version) == pinned_version for c in managed)
    notes: list[str] = []
    if not host_discovery:
        notes.append(
            "Pythons already on this Mac were not checked: Apple's Command Line "
            "Tools are not installed, and checking /usr/bin/python3 would open "
            "Apple's install dialog. AutoApply uses its own Python instead."
        )

    def _managed() -> PythonChoice:
        if managed_here:
            return PythonChoice("managed", None, pinned_version, True, False, tuple(notes))
        if offline:
            raise PythonChoiceError(
                f"offline, and AutoApply's own Python {pinned_version} is not in the "
                "AA folder yet — run the installer once with a network connection"
            )
        return PythonChoice("managed", None, pinned_version, True, True, tuple(notes))

    def _host(c: Candidate, why: str = "") -> PythonChoice:
        n = list(notes)
        if why:
            n.append(why)
        if c.version[:2] not in CI_PROVEN_MINORS:
            n.append(
                f"Python {_vtext(c.version)} is not one of the versions AutoApply's "
                "tests run on (3.10, 3.12); it is expected to work."
            )
        if not c.has_tk:
            n.append(
                "This Python has no tkinter, so the window (GUI) cannot open; "
                "the terminal mode (--cli) works fully."
            )
        return PythonChoice("host", c.path, _vtext(c.version), c.has_tk, False, tuple(n))

    # 1. what the person asked for
    if requested:
        if requested.lower() == "managed":
            return _managed()
        wanted = os.path.normcase(os.path.realpath(requested))
        for c in candidates:
            if os.path.normcase(os.path.realpath(c.path)) == wanted:
                return _managed() if c.managed else _host(c, "Using the Python you chose.")
        raise PythonChoiceError(
            f"the Python you chose ({requested}) is not usable: AutoApply needs "
            "CPython 3.10 or newer, 64-bit, with ssl and sqlite3"
        )
    # 2. a repair keeps what the last install chose, while it still works
    if previous == "managed" and (managed_here or not offline):
        return _managed()
    if previous and previous != "managed":
        prev = os.path.normcase(os.path.realpath(previous))
        for c in candidates:
            if os.path.normcase(os.path.realpath(c.path)) == prev:
                return _managed() if c.managed else _host(c)
    # 3. a host Python with tkinter
    if hosts and hosts[0].has_tk:
        return _host(hosts[0], f"Using the Python already on this computer ({hosts[0].path}); nothing to download.")
    # 4./5. AA's own Python
    if managed_here or not offline:
        if hosts:
            notes.append(
                f"The Python on this computer ({hosts[0].path}) has no tkinter, so "
                "AutoApply uses its own Python, which includes it."
            )
        return _managed()
    # 6. offline: a host Python without tkinter beats nothing
    if hosts:
        return _host(hosts[0])
    raise PythonChoiceError(
        "offline, and there is no usable Python on this computer or in the AA folder"
    )
