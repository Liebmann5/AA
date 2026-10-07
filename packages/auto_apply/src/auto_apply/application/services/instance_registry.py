"""The instance registry — how uninstall tells whether AA is running.

Not a lock. A single lock file would go stale on SIGKILL and would forbid
the legitimate case of two AA processes; the registry is a DIRECTORY with
one small JSON record per live instance, written at session build and
removed at clean exit (the atexit hook in composition_root). Liveness is
not the file's presence but the process behind it: the pid must exist AND
its start time must match what the record claims (the PID-reuse guard —
a recycled pid belongs to a younger process and must never be signalled
on AA's say-so). Records whose process is gone are swept on read.

Consumers: composition_root.build_session_controller (register/unregister)
and the uninstall engine (alive()).
"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

import psutil

_START_TOLERANCE_SECONDS = 5.0


@dataclass(frozen=True)
class InstanceRecord:
    """One live AA process."""

    pid: int
    started_at: float
    host: str


def pid_alive(pid: int, started_at: float) -> bool:
    """True when pid exists AND was started when the record claims."""
    if pid <= 0 or not psutil.pid_exists(pid):
        return False
    try:
        created = psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return abs(created - started_at) <= _START_TOLERANCE_SECONDS


class InstanceRegistry:
    """One record per live AA instance inside the data root."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def register(self) -> Path:
        """Record this process. Creates the directory lazily — never at import."""
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            # The PROCESS's start time, not the registration time: pid_alive
            # compares against psutil's create_time with a 5 s tolerance, and
            # AA registers long after it starts, so time.time() made every
            # real instance look stale and be swept.
            "started_at": psutil.Process().create_time(),
            "host": socket.gethostname(),
        }
        target = self._dir / f"{payload['pid']}.instance.json"
        target.write_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return target

    def unregister(self, pid: int | None = None) -> None:
        """Remove this process's record. Idempotent."""
        try:
            (self._dir / f"{pid or os.getpid()}.instance.json").unlink()
        except FileNotFoundError:
            pass

    def alive(self) -> list[InstanceRecord]:
        """Live instances, sweeping records whose process is gone."""
        if not self._dir.exists():
            return []
        found: list[InstanceRecord] = []
        for file in sorted(self._dir.glob("*.instance.json")):
            try:
                record = json.loads(file.read_bytes().decode("utf-8"))
                pid = int(record["pid"])
                started = float(record["started_at"])
            except (OSError, ValueError, KeyError, TypeError):
                file.unlink(missing_ok=True)
                continue
            if pid_alive(pid, started):
                found.append(
                    InstanceRecord(pid=pid, started_at=started, host=str(record.get("host", "")))
                )
            else:
                file.unlink(missing_ok=True)
        return found
