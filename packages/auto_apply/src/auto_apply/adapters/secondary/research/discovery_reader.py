"""DiscoveryReader — reads the discovery tables, never writes them.

The read side of item 4c's discovery tables (item 2). It opens the research
database READ-ONLY, so a summary can never migrate or alter the database
file, and a missing database is reported as missing rather than created
empty. (SQLite reads a WAL-mode database by creating its -wal and -shm side
files and leaves them in place; they carry no rows, and the withdrawal purge
deletes them with the database.) The analysis itself lives in
domain.services.discovery_taxonomy; this module only moves rows out of
SQLite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["DiscoveryRows", "read_discovery_rows"]

#: The three item-4c tables, in funnel order.
DISCOVERY_TABLES: tuple[str, ...] = (
    "discovery_pages",
    "discovery_cards",
    "discovery_candidates",
)


@dataclass(frozen=True)
class DiscoveryRows:
    """Every row of the three discovery tables, as column-name mappings."""

    pages: tuple[dict[str, Any], ...]
    cards: tuple[dict[str, Any], ...]
    candidates: tuple[dict[str, Any], ...]


def read_discovery_rows(db_path: Path) -> DiscoveryRows:
    """Read the discovery tables from the research database.

    A table the database predates reads as empty (databases written before
    item 4c have none of the three).

    Raises:
        FileNotFoundError: No research database exists at ``db_path``.
        sqlite3.Error: The file exists but cannot be read as a database.
    """
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    # Same read-only URI form as ResearchExporter.export, the precedent for
    # reading this database without the power to change it.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        present = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        loaded: list[tuple[dict[str, Any], ...]] = []
        for table in DISCOVERY_TABLES:
            if table not in present:
                loaded.append(())
                continue
            # Table names come from the constant above, never from input.
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            loaded.append(tuple(dict(row) for row in rows))
    finally:
        conn.close()
    return DiscoveryRows(pages=loaded[0], cards=loaded[1], candidates=loaded[2])
