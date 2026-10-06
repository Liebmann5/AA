"""The footprint ledger — AA's record of what it created, and where.

Two jobs:

  ROOTS     Every session start records the run mode, the data root and the
            install root (last record wins). The uninstaller reads this
            instead of guessing how AA arrived — the install route
            determines AA's real setup, and nothing may assume it.
  OUTSIDE   Anything AA must write OUTSIDE the data root is recorded at the
            moment it is written, with its origin: created-by-AA or
            pre-existing. The uninstaller never removes a pre-existing item.

Format: JSON Lines, append-only, one record per line, UTF-8, "\\n"
terminated, written in BINARY mode so the bytes on disk are exactly the
bytes produced here on every platform (the byte-discipline rule). Load is
last-wins per key, so an interrupted append only ever costs its own line.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LEDGER_FORMAT_VERSION = 1

_ORIGINS = frozenset({"aa", "preexisting", "unknown"})
_KINDS = frozenset({"file", "dir"})


@dataclass(frozen=True)
class OutsideItem:
    """One recorded write outside the data root."""

    path: Path
    origin: str  # "aa" | "preexisting" | "unknown"
    kind: str  # "file" | "dir"
    note: str = ""


@dataclass(frozen=True)
class RootsRecord:
    """How this AA arrived. The uninstaller's shape answer."""

    run_mode: str
    data_root: Path
    install_root: Path
    recorded_at: str


@dataclass(frozen=True)
class LedgerSnapshot:
    """The ledger as of load(): the latest roots plus every outside item."""

    exists: bool
    roots: RootsRecord | None
    outside: tuple[OutsideItem, ...]


def _encode(record: dict) -> bytes:
    """The one serialisation — byte-exact by construction (a pin relies on it)."""
    return (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


class FootprintLedger:
    """Appends to and reads one footprint-ledger file.

    Writing creates the parent directory LAZILY (never at import, never at
    construction), so the uninstall path — which suppresses directory
    creation — can read a ledger without recreating its home.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _append(self, record: dict) -> None:
        record = {"v": LEDGER_FORMAT_VERSION, **record}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as fh:
            fh.write(_encode(record))
            fh.flush()
            os.fsync(fh.fileno())

    def record_roots(self, *, run_mode: str, data_root: Path, install_root: Path) -> None:
        """Record how this AA arrived. Last record wins on load."""
        self._append({
            "type": "roots",
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_mode": run_mode,
            "data_root": str(data_root),
            "install_root": str(install_root),
        })

    def record_outside(self, path: Path, *, origin: str, kind: str, note: str = "") -> None:
        """Record one write outside the data root.

        origin="preexisting" is a promise to the uninstaller: never remove.
        """
        if origin not in _ORIGINS:
            raise ValueError(f"origin must be one of {sorted(_ORIGINS)}, got {origin!r}")
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {sorted(_KINDS)}, got {kind!r}")
        self._append({
            "type": "outside",
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "origin": origin,
            "kind": kind,
            "note": note,
        })

    def load(self) -> LedgerSnapshot:
        """Read the ledger. A missing ledger is a valid answer (discovery mode)."""
        if not self.path.exists():
            return LedgerSnapshot(exists=False, roots=None, outside=())
        raw = self.path.read_bytes()
        roots: RootsRecord | None = None
        outside: dict[str, OutsideItem] = {}
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            record = json.loads(line.decode("utf-8"))
            rtype = record.get("type")
            if rtype == "roots":
                roots = RootsRecord(
                    run_mode=str(record["run_mode"]),
                    data_root=Path(record["data_root"]),
                    install_root=Path(record["install_root"]),
                    recorded_at=str(record.get("ts", "")),
                )
            elif rtype == "outside":
                outside[str(record["path"])] = OutsideItem(
                    path=Path(record["path"]),
                    origin=str(record["origin"]),
                    kind=str(record["kind"]),
                    note=str(record.get("note", "")),
                )
        return LedgerSnapshot(exists=True, roots=roots, outside=tuple(outside.values()))
