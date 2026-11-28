"""Every SQLite connection AA opens, made durable for the medium it is on.

Phase 0 (P0-7/P0-8), AA_ENGINE_MATH.md §10. The one place in ``src`` that
calls ``sqlite3.connect`` (a pin holds that).

**The policy.** ``storage.medium`` (``auto`` | ``removable`` | ``fixed``):

* ``fixed`` → ``journal_mode=WAL``, ``synchronous=NORMAL`` — the desktop
  behaviour AA always had on an internal disk.
* ``removable``, or anything AA cannot tell → ``journal_mode=DELETE``,
  ``synchronous=EXTRA``. WAL is unsafe on removable media (its ``-wal`` and
  ``-shm`` files must travel with the database and its shared memory must
  work); ``EXTRA`` is FULL plus a sync of the directory after the rollback
  journal is unlinked. A database that was in WAL is checkpointed
  (``wal_checkpoint(TRUNCATE)``) before it is switched, so no committed page
  is left behind in a ``-wal`` file.

``auto`` resolves per database file: a portable (frozen) build is treated as
removable; on Windows the drive type (``GetDriveTypeW``); on Linux the
mount's device and ``/sys/block/<dev>/removable`` (vfat/exfat/msdos mounts
count as removable). Anything else — another OS, a network or virtual
mount, a failed probe — is "unknown", which takes the safe mode.

``fsync`` is only as good as the device honours it: a consumer stick that
acknowledges a flush early can still lose the last write (the F1 case of
§2). This module makes the request; it cannot make a device keep it.

``synchronous`` is a per-connection setting, so it is applied on every
connection; the journal mode is set once per database file per process.
Read-only connections (``mode=ro``) change nothing.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any

from auto_apply.domain.config import IS_FROZEN

logger = logging.getLogger(__name__)

__all__ = [
    "DURABLE",
    "FAST",
    "MEDIA",
    "configure_durability",
    "connect",
    "connect_readonly",
    "durability_for",
    "resolve_medium",
]

#: The two modes a database can be put in.
DURABLE = "DELETE+EXTRA"
FAST = "WAL+NORMAL"
MEDIA = ("auto", "removable", "fixed")

_lock = threading.Lock()
_configured = "auto"
#: A portable (frozen) build runs from a stick: removable unless configured.
_frozen = bool(IS_FROZEN)
#: Database files whose journal mode this process already set.
_mode_set: dict[str, str] = {}


def configure_durability(medium: Any, *, frozen: bool | None = None) -> str:
    """Set the session's policy (``storage.medium``); anything unknown reads
    as ``auto``. Returns the policy in force."""
    global _configured, _frozen
    value = str(medium or "auto").strip().lower()
    with _lock:
        _configured = value if value in MEDIA else "auto"
        if frozen is not None:
            _frozen = bool(frozen)
        _mode_set.clear()
        return _configured


def _windows_drive_type(path: Path) -> str:
    if sys.platform != "win32":
        return "unknown"
    try:
        import ctypes  # noqa: PLC0415

        drive = os.path.splitdrive(os.path.abspath(str(path)))[0]
        if not drive:
            return "unknown"
        root = drive + "\\"
        kind = int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    except Exception:  # noqa: BLE001 — a failed probe is "unknown"
        return "unknown"
    # 2 DRIVE_REMOVABLE, 3 DRIVE_FIXED; remote, CD-ROM, RAM disk, unknown → safe.
    return {2: "removable", 3: "fixed"}.get(kind, "unknown")


def _linux_medium(path: Path) -> str:
    try:
        target = os.path.realpath(str(path))
        best: tuple[str, str, str] | None = None
        with open("/proc/mounts", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
                if target == mount or target.startswith(mount.rstrip("/") + "/") or mount == "/":
                    if best is None or len(mount) > len(best[1]):
                        best = (device, mount, fstype)
        if best is None:
            return "unknown"
        device, _mount, fstype = best
        if fstype in ("vfat", "exfat", "msdos"):
            return "removable"
        if not device.startswith("/dev/"):
            return "unknown"
        name = os.path.basename(os.path.realpath(device))
        real = (Path("/sys/class/block") / name).resolve()
        # A partition (sdb1) has no flag of its own; its disk (sdb) does.
        flag = ""
        for candidate in (real / "removable", real.parent / "removable"):
            if candidate.exists():
                flag = candidate.read_text(encoding="ascii").strip()
                break
    except Exception:  # noqa: BLE001 — a failed probe is "unknown"
        return "unknown"
    return "removable" if flag == "1" else "fixed" if flag == "0" else "unknown"


def resolve_medium(path: Path) -> str:
    """``removable`` | ``fixed`` | ``unknown`` for the file system at ``path``."""
    with _lock:
        configured, frozen = _configured, _frozen
    if configured in ("removable", "fixed"):
        return configured
    if frozen:
        return "removable"
    if sys.platform == "win32":
        return _windows_drive_type(path)
    if sys.platform.startswith("linux"):
        return _linux_medium(path)
    return "unknown"


def durability_for(path: Path) -> str:
    """The mode a database at ``path`` is put in (:data:`DURABLE` or :data:`FAST`)."""
    return FAST if resolve_medium(path) == "fixed" else DURABLE


def _apply(conn: sqlite3.Connection, key: str, mode: str) -> None:
    with _lock:
        done = _mode_set.get(key) == mode
    if not done:
        current = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode == DURABLE:
            if current == "wal":
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            got = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        else:
            got = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if got not in ("delete", "wal", "memory"):
            logger.warning("durable_sqlite: journal mode read back as %r for %s", got, key)
        else:
            logger.info("durable_sqlite: %s in %s mode", Path(key).name, got.upper())
        with _lock:
            _mode_set[key] = mode
    conn.execute("PRAGMA synchronous=EXTRA" if mode == DURABLE else "PRAGMA synchronous=NORMAL")


def connect(path: Path | str, *, timeout: float = 10.0,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """A read-write connection to the database at ``path``, durable for its
    medium. ``:memory:`` is passed through unchanged."""
    if str(path) == ":memory:":
        return sqlite3.connect(":memory:", timeout=timeout,
                               check_same_thread=check_same_thread)
    db = Path(path)
    conn = sqlite3.connect(str(db), timeout=timeout, check_same_thread=check_same_thread)
    try:
        _apply(conn, os.path.abspath(str(db)), durability_for(db.parent))
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def connect_readonly(path: Path | str) -> sqlite3.Connection:
    """A read-only connection (``mode=ro``): it can change nothing, so no
    pragma is set. Raises when the file does not exist."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
