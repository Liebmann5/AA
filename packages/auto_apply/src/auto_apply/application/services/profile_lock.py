"""One profile, one submitting process; and where the data actually lives.

Phase 0 (P0-3), AA_ENGINE_MATH.md §2 "One profile, one process" and §10.

**The lock.** An exclusive, non-blocking OS lock on ``<journals>/<profile>.lock``
(``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows). The operating
system releases it when the process dies, however it dies — so a crash can
never leave a profile unable to submit. There is deliberately **no**
claim-file fallback (``O_CREAT|O_EXCL``): a claim file survives SIGKILL and
power loss, which would block submission until someone deletes it by hand.
On a platform with neither OS lock the lock is never acquired, so AA refuses
to submit there (fail closed) and says why.

The lock is taken once, on the first attempt to arm a submission, and held
for the rest of the process. Discovery, vetting and startup never need it: a
second AA on the same profile runs, it just cannot submit.

**Synced folders.** A lock is local to one filesystem; a profile in a synced
folder (or copied to two drives) can be written from two machines. AA
detects the sync roots the vendors document and refuses to *submit* from
inside one unless the person opts in. Detection is best-effort and
incomplete by construction — Google Drive for desktop can mirror arbitrary
local folders and documents no portable way to list them — so AA never
claims a path is *not* synced; it only reports a root it found.

Documented sources used (and nothing else):

* OneDrive: the ``OneDrive``, ``OneDriveConsumer`` and ``OneDriveCommercial``
  environment variables.
* Dropbox: ``info.json`` at ``%APPDATA%\\Dropbox``, ``%LOCALAPPDATA%\\Dropbox``
  (Windows) or ``~/.dropbox`` (macOS/Linux); each of its ``personal`` /
  ``business`` entries carries a ``path``.
* Google Drive for desktop: the default mirror folder ``~/My Drive`` and the
  Windows default streaming location (``G:\\My Drive``) when present.

An unreadable or missing source means "not detected", never an error.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOW_SYNCED_ENV_VAR",
    "ProfileLock",
    "detect_sync_root",
    "lock_supported",
    "synced_override",
]

#: The person's opt-in to submitting from a synced folder, for runs where the
#: user-settings tier cannot carry it (a development checkout). Same effect as
#: ``storage.allow_synced_profile: true``.
ALLOW_SYNCED_ENV_VAR = "AA_ALLOW_SYNCED_PROFILE"

_ONEDRIVE_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def lock_supported() -> bool:
    """Is an OS-level exclusive lock available on this platform?"""
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: F401, PLC0415
        else:
            import fcntl  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


class ProfileLock:
    """An exclusive, process-lifetime lock for one profile's submissions."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._fh: IO[bytes] | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        """Take the lock without waiting. True when this object holds it.

        Idempotent while held. Never raises: a lock that cannot be taken is a
        refusal to submit, not a crash.
        """
        if self._fh is not None:
            return True
        if not lock_supported():
            logger.warning("profile lock: no OS lock on this platform; submission refused")
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self._path, "a+b")  # noqa: SIM115 — held for the process
        except OSError as exc:
            logger.warning("profile lock: cannot open the lock file (%s)", type(exc).__name__)
            return False
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        """Release the lock (the OS also releases it when the process ends)."""
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()


def synced_override(storage_cfg: Any) -> bool:
    """Has the person opted in to submitting from a synced folder?"""
    if str(os.environ.get(ALLOW_SYNCED_ENV_VAR, "")).strip().lower() in ("1", "true", "yes"):
        return True
    if isinstance(storage_cfg, dict):
        return storage_cfg.get("allow_synced_profile") is True
    return False


def _dropbox_roots(env: dict[str, str], home: Path) -> list[Path]:
    candidates: list[Path] = []
    for var in ("APPDATA", "LOCALAPPDATA"):
        base = env.get(var)
        if base:
            candidates.append(Path(base) / "Dropbox" / "info.json")
    candidates.append(home / ".dropbox" / "info.json")
    roots: list[Path] = []
    for info in candidates:
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for account in data.values():
            if isinstance(account, dict) and isinstance(account.get("path"), str):
                roots.append(Path(account["path"]))
    return roots


def _google_drive_roots(home: Path) -> list[Path]:
    roots = [home / "My Drive"]
    if sys.platform == "win32":
        roots.append(Path("G:\\My Drive"))
    return [r for r in roots if _exists(r)]


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _within(path: Path, root: Path) -> bool:
    try:
        p = os.path.normcase(os.path.abspath(str(path)))
        r = os.path.normcase(os.path.abspath(str(root)))
    except (OSError, ValueError):
        return False
    if not r:
        return False
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def detect_sync_root(path: Path, *, env: dict[str, str] | None = None,
                     home: Path | None = None) -> str | None:
    """The documented sync root ``path`` lies in, as ``"<vendor>: <root>"``,
    or None when none was detected (which never means "not synced")."""
    env = dict(os.environ) if env is None else env
    try:
        home = Path.home() if home is None else home
    except (OSError, RuntimeError):
        home = Path(".")
    found: list[tuple[str, Path]] = []
    for var in _ONEDRIVE_VARS:
        val = env.get(var)
        if val:
            found.append(("OneDrive", Path(val)))
    found.extend(("Dropbox", r) for r in _dropbox_roots(env, home))
    found.extend(("Google Drive", r) for r in _google_drive_roots(home))
    for vendor, root in found:
        if _within(path, root):
            return f"{vendor}: {root}"
    return None
