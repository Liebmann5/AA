"""
SqliteConsentRepository — persistence for ResearchConsentManager.

Stores the user's consent decision in a small dedicated SQLite table —
separate from the research signals DB. This means consent state survives
even if a user purges their research data, and purging research data
doesn't accidentally also erase the record that they withdrew consent
(which would cause re-prompting).
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from auto_apply.application.services.research_consent import (
    ConsentRecord,
    ConsentRepositoryPort,
)

logger = logging.getLogger(__name__)

_CONSENT_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS research_consent (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- single row
    granted         INTEGER NOT NULL DEFAULT 0,
    consent_version TEXT,
    granted_at      TEXT,
    withdrawn_at    TEXT
);
"""


class SqliteConsentRepository(ConsentRepositoryPort):
    """SQLite-backed ConsentRepositoryPort implementation.

    Args:
        consent_db_path: Path to a small SQLite file dedicated to consent state.
        research_db_path: Path to the main research signals database, used
            by purge_research_data() to delete the user's contribution.
    """

    def __init__(self, consent_db_path: Path, research_db_path: Path) -> None:
        self._consent_db_path = consent_db_path
        self._research_db_path = research_db_path
        self._consent_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection(self._consent_db_path) as conn:
            conn.executescript(_CONSENT_SCHEMA_SQL)

    @contextmanager
    def _get_connection(self, path: Path):
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_consent(self) -> ConsentRecord:
        """Load the current consent record. Returns default (not granted) if none exists."""
        try:
            with self._get_connection(self._consent_db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM research_consent WHERE id = 1"
                ).fetchone()
            if row is None:
                return ConsentRecord()
            return ConsentRecord(
                granted=bool(row["granted"]),
                consent_version=row["consent_version"],
                granted_at=(
                    datetime.fromisoformat(row["granted_at"])
                    if row["granted_at"] else None
                ),
                withdrawn_at=(
                    datetime.fromisoformat(row["withdrawn_at"])
                    if row["withdrawn_at"] else None
                ),
            )
        except Exception as exc:
            logger.error("SqliteConsentRepository | load_consent failed: %s", exc)
            return ConsentRecord()

    def save_consent(self, record: ConsentRecord) -> None:
        """Persist a consent record (single-row upsert)."""
        try:
            with self._get_connection(self._consent_db_path) as conn:
                conn.execute(
                    """INSERT INTO research_consent
                       (id, granted, consent_version, granted_at, withdrawn_at)
                       VALUES (1, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         granted=excluded.granted,
                         consent_version=excluded.consent_version,
                         granted_at=excluded.granted_at,
                         withdrawn_at=excluded.withdrawn_at""",
                    (
                        int(record.granted), record.consent_version,
                        record.granted_at.isoformat() if record.granted_at else None,
                        record.withdrawn_at.isoformat() if record.withdrawn_at else None,
                    ),
                )
        except Exception as exc:
            logger.error("SqliteConsentRepository | save_consent failed: %s", exc)

    def purge_research_data(self) -> int:
        """Delete all research signal data from the research database.

        Two-phase: DELETEs run inside a normal transaction (committed via
        _get_connection). VACUUM then runs in a SEPARATE autocommit
        connection — SQLite forbids VACUUM inside a transaction, and
        attempting it inside the same `with` block as the DELETEs would
        raise, triggering a rollback that silently undoes the deletions.
        VACUUM failure is non-fatal (reclaiming disk space is an
        optimization, not correctness-critical) and is logged but does
        not affect the returned count.

        Returns:
            Total number of rows deleted across all research tables.
        """
        if not self._research_db_path.exists():
            return 0

        tables = (
            "research_signals", "job_lifecycles", "salary_observations",
            "form_observations", "application_outcomes",
        )
        total_deleted = 0
        try:
            with self._get_connection(self._research_db_path) as conn:
                for table in tables:
                    cursor = conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list above
                    total_deleted += cursor.rowcount if cursor.rowcount > 0 else 0
            logger.info(
                "SqliteConsentRepository | Purged %d rows across %d tables",
                total_deleted, len(tables),
            )
        except Exception as exc:
            logger.error("SqliteConsentRepository | purge_research_data failed: %s", exc)
            return total_deleted

        # Phase 2: VACUUM in its own autocommit connection (separate from the
        # transactional DELETE phase above — see docstring).
        try:
            vacuum_conn = sqlite3.connect(str(self._research_db_path), timeout=10.0)
            vacuum_conn.isolation_level = None  # autocommit mode required for VACUUM
            try:
                vacuum_conn.execute("VACUUM")
            finally:
                vacuum_conn.close()
        except Exception as exc:
            logger.warning(
                "SqliteConsentRepository | VACUUM after purge failed (non-fatal): %s", exc
            )
        return total_deleted
