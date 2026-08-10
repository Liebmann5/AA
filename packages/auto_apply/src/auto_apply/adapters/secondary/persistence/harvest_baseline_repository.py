"""Per-provider harvest-baseline store for the silent-degradation guard.

Modeled on PageFeedbackRepository: own SQLite file, schema created on
construction, connection-per-call, exponential moving average, never raises.
The baseline records what a provider's first harvest normally looks like —
yield count, page bytes, elapsed seconds — so the guard can tell a collapse
from a legitimately sparse result set.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# EMA smoothing factor (matches PageFeedbackRepository — a baseline should
# move slowly; one odd day must not redefine "normal").
_ALPHA: float = 0.2

_SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS provider_harvest_baseline (
    provider            TEXT PRIMARY KEY,
    avg_visible         REAL NOT NULL DEFAULT 0.0,
    avg_page_bytes      REAL NOT NULL DEFAULT 0.0,
    avg_elapsed_seconds REAL NOT NULL DEFAULT 0.0,
    sample_count        INTEGER NOT NULL DEFAULT 0,
    last_updated        TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class HarvestBaseline:
    """One provider's running baseline."""

    avg_visible: float
    avg_page_bytes: float
    avg_elapsed_seconds: float
    sample_count: int


class HarvestBaselineRepository:
    """SQLite-backed store of per-provider first-harvest baselines."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.debug("HarvestBaselineRepository ready | path=%s", db_path)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_baseline(self, provider: str) -> HarvestBaseline | None:
        """Return the provider's baseline, or None if never recorded."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT avg_visible, avg_page_bytes, avg_elapsed_seconds, "
                    "sample_count FROM provider_harvest_baseline "
                    "WHERE provider = ?",
                    (provider,),
                ).fetchone()
            if row is None:
                return None
            return HarvestBaseline(
                avg_visible=row["avg_visible"],
                avg_page_bytes=row["avg_page_bytes"],
                avg_elapsed_seconds=row["avg_elapsed_seconds"],
                sample_count=row["sample_count"],
            )
        except Exception as exc:
            logger.warning("HarvestBaselineRepository.get_baseline failed: %s", exc)
            return None

    def record_harvest(
        self,
        provider: str,
        visible: int,
        page_bytes: int,
        elapsed_seconds: float,
    ) -> None:
        """Fold one first-harvest observation into the provider's EMA."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT avg_visible, avg_page_bytes, avg_elapsed_seconds, "
                    "sample_count FROM provider_harvest_baseline "
                    "WHERE provider = ?",
                    (provider,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        "INSERT INTO provider_harvest_baseline "
                        "(provider, avg_visible, avg_page_bytes, "
                        " avg_elapsed_seconds, sample_count, last_updated) "
                        "VALUES (?, ?, ?, ?, 1, ?)",
                        (provider, float(visible), float(page_bytes),
                         float(elapsed_seconds), now),
                    )
                else:
                    avg_visible = (1 - _ALPHA) * row["avg_visible"] + _ALPHA * visible
                    avg_bytes = (1 - _ALPHA) * row["avg_page_bytes"] + _ALPHA * page_bytes
                    avg_elapsed = (
                        (1 - _ALPHA) * row["avg_elapsed_seconds"]
                        + _ALPHA * elapsed_seconds
                    )
                    conn.execute(
                        "UPDATE provider_harvest_baseline SET avg_visible = ?, "
                        "avg_page_bytes = ?, avg_elapsed_seconds = ?, "
                        "sample_count = ?, last_updated = ? WHERE provider = ?",
                        (avg_visible, avg_bytes, avg_elapsed,
                         row["sample_count"] + 1, now, provider),
                    )
        except Exception as exc:
            logger.warning("HarvestBaselineRepository.record_harvest failed: %s", exc)


__all__ = ["HarvestBaselineRepository", "HarvestBaseline"]
