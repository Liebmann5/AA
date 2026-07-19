"""SQLite-backed implementation of FeedbackRepositoryPort.

Uses an exponential moving average (EMA) with a configurable smoothing
factor to ensure old observations decay naturally over time.

Schema:
    page_feedback (
        page_signature TEXT NOT NULL,
        tier           TEXT NOT NULL,
        avg_success    REAL NOT NULL DEFAULT 0.0,
        count          INTEGER NOT NULL DEFAULT 0,
        last_updated   TEXT NOT NULL,
        PRIMARY KEY (page_signature, tier)
    )
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from auto_apply.domain.ports.feedback_repository_port import FeedbackRepositoryPort

logger = logging.getLogger(__name__)

# Smoothing factor for the exponential moving average.
# 0.2 means the new observation contributes 20 % weight to the running avg.
_ALPHA: float = 0.2

# Schema creation SQL — idempotent.
_SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS page_feedback (
    page_signature TEXT NOT NULL,
    tier           TEXT NOT NULL,
    avg_success    REAL NOT NULL DEFAULT 0.0,
    count          INTEGER NOT NULL DEFAULT 0,
    last_updated   TEXT NOT NULL,
    PRIMARY KEY (page_signature, tier)
);
"""


class PageFeedbackRepository:
    """Persists per‑(page_signature, tier) success statistics using EMA.

    Thread‑safe by way of connection‑per‑call (SQLite WAL handles
    concurrent read/write access).  Never raises — errors are logged
    and the caller receives safe defaults.

    Args:
        db_path: Path to the SQLite database file.  The parent directory
            is created automatically if it does not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.debug("PageFeedbackRepository ready | path=%s", db_path)

    @contextmanager
    def _get_connection(self):
        """Yield a managed SQLite connection with auto‑commit/rollback."""
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

    # ------------------------------------------------------------------
    # FeedbackRepositoryPort implementation
    # ------------------------------------------------------------------

    def get_scores(
        self, page_signature: str
    ) -> dict[str, tuple[float, int]]:
        """Return all (tier → (avg_success, count)) entries for a signature.

        Returns an empty dict when no data exists.
        """
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT tier, avg_success, count FROM page_feedback "
                    "WHERE page_signature = ?",
                    (page_signature,),
                ).fetchall()
            return {
                row["tier"]: (row["avg_success"], row["count"]) for row in rows
            }
        except Exception as exc:
            logger.warning(
                "PageFeedbackRepository.get_scores failed | signature=%s error=%s",
                page_signature,
                exc,
            )
            return {}

    def record_outcome(
        self,
        page_signature: str,
        tier: str,
        success: bool,
    ) -> None:
        """Update the EMA for a single (page_signature, tier) combo.

        If the row does not exist it is created with the first observation.
        """
        now = datetime.now(timezone.utc).isoformat()
        outcome = 1.0 if success else 0.0

        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT avg_success, count FROM page_feedback "
                    "WHERE page_signature = ? AND tier = ?",
                    (page_signature, tier),
                ).fetchone()

                if row is None:
                    # First observation — seed the EMA.
                    conn.execute(
                        "INSERT INTO page_feedback "
                        "(page_signature, tier, avg_success, count, last_updated) "
                        "VALUES (?, ?, ?, 1, ?)",
                        (page_signature, tier, outcome, now),
                    )
                else:
                    old_avg, old_count = row["avg_success"], row["count"]
                    # EMA update: new = (1-α) * old + α * outcome
                    new_avg = (1.0 - _ALPHA) * old_avg + _ALPHA * outcome
                    new_count = old_count + 1
                    conn.execute(
                        "UPDATE page_feedback SET avg_success = ?, count = ?, "
                        "last_updated = ? WHERE page_signature = ? AND tier = ?",
                        (new_avg, new_count, now, page_signature, tier),
                    )
        except Exception as exc:
            logger.warning(
                "PageFeedbackRepository.record_outcome failed | "
                "signature=%s tier=%s success=%s error=%s",
                page_signature,
                tier,
                success,
                exc,
            )


__all__ = ["PageFeedbackRepository"]