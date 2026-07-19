"""
SqliteAuditRepository — persistence backend for AuditCoordinator.

Implements AuditRepositoryPort from domain/ports/audit_port.py.
Stores paired-submission records in SQLite with WAL mode.

All data is fully anonymized — company identifiers are already hashed and
profile labels are "A" / "B" only.  No PII is ever stored in this database.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from auto_apply.domain.ports.audit_port import (
    AuditRepositoryPort,
    AuditSubmissionRecord,
)

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS audit_submissions (
    pair_id                   TEXT NOT NULL,
    job_fingerprint           TEXT NOT NULL,
    job_url                   TEXT NOT NULL,
    company_id                TEXT,
    platform                  TEXT,
    profile_a_submitted_at    TEXT,
    profile_b_submitted_at    TEXT,
    profile_a_callback        INTEGER,   -- 0/1/NULL
    profile_b_callback        INTEGER,
    profile_a_interview_offered INTEGER DEFAULT 0,
    profile_b_interview_offered INTEGER DEFAULT 0,
    withdrawn                 INTEGER DEFAULT 0,
    PRIMARY KEY (pair_id, job_fingerprint)
);
"""


class SqliteAuditRepository:
    """SQLite-backed repository for correspondence audit submission records.

    Implements AuditRepositoryPort so that AuditCoordinator can persist
    and query paired application records.

    Args:
        db_path: Path to the SQLite database file.  The parent directory is
            created automatically if it does not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.info("SqliteAuditRepository | DB initialized at %s", self._db_path)

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

    # ----------------------------------------------------------------
    # AuditRepositoryPort implementation
    # ----------------------------------------------------------------

    def save_submission(self, record: AuditSubmissionRecord) -> None:
        """Insert or update a paired submission record.

        If a record with the same (pair_id, job_fingerprint) already exists,
        it is updated.
        """
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO audit_submissions
                       (pair_id, job_fingerprint, job_url, company_id, platform,
                        profile_a_submitted_at, profile_b_submitted_at,
                        profile_a_callback, profile_b_callback,
                        profile_a_interview_offered, profile_b_interview_offered,
                        withdrawn)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(pair_id, job_fingerprint) DO UPDATE SET
                         job_url=excluded.job_url,
                         company_id=excluded.company_id,
                         platform=excluded.platform,
                         profile_a_submitted_at=excluded.profile_a_submitted_at,
                         profile_b_submitted_at=excluded.profile_b_submitted_at,
                         profile_a_callback=excluded.profile_a_callback,
                         profile_b_callback=excluded.profile_b_callback,
                         profile_a_interview_offered=excluded.profile_a_interview_offered,
                         profile_b_interview_offered=excluded.profile_b_interview_offered,
                         withdrawn=excluded.withdrawn""",
                    (
                        record.pair_id,
                        record.job_fingerprint,
                        record.job_url,
                        record.company_id,
                        record.platform,
                        record.profile_a_submitted_at.isoformat() if record.profile_a_submitted_at else None,
                        record.profile_b_submitted_at.isoformat() if record.profile_b_submitted_at else None,
                        _bool_to_int(record.profile_a_callback),
                        _bool_to_int(record.profile_b_callback),
                        int(record.profile_a_interview_offered),
                        int(record.profile_b_interview_offered),
                        int(record.withdrawn),
                    ),
                )
        except Exception as exc:
            logger.error("SqliteAuditRepository | save_submission failed: %s", exc)

    def load_submissions(self, pair_id: str) -> list[AuditSubmissionRecord]:
        """Load all submission records for a given audit pair."""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM audit_submissions WHERE pair_id = ?",
                    (pair_id,),
                ).fetchall()
            return [_row_to_record(r) for r in rows]
        except Exception as exc:
            logger.error("SqliteAuditRepository | load_submissions failed: %s", exc)
            return []

    def find_submission(
        self, pair_id: str, job_fingerprint: str
    ) -> AuditSubmissionRecord | None:
        """Return a single submission record if it exists, otherwise None."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM audit_submissions WHERE pair_id = ? AND job_fingerprint = ?",
                    (pair_id, job_fingerprint),
                ).fetchone()
            if row is None:
                return None
            return _row_to_record(row)
        except Exception as exc:
            logger.error("SqliteAuditRepository | find_submission failed: %s", exc)
            return None


# ----------------------------------------------------------------------
# internal helpers
# ----------------------------------------------------------------------

def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _row_to_record(row: sqlite3.Row) -> AuditSubmissionRecord:
    """Convert a sqlite3.Row back into an AuditSubmissionRecord."""
    from datetime import datetime

    def _parse_ts(text: str | None) -> datetime | None:
        if not text:
            return None
        return datetime.fromisoformat(text)

    return AuditSubmissionRecord(
        pair_id=row["pair_id"],
        job_fingerprint=row["job_fingerprint"],
        job_url=row["job_url"],
        company_id=row["company_id"],
        platform=row["platform"],
        profile_a_submitted_at=_parse_ts(row["profile_a_submitted_at"]),
        profile_b_submitted_at=_parse_ts(row["profile_b_submitted_at"]),
        profile_a_callback=_int_to_bool(row["profile_a_callback"]),
        profile_b_callback=_int_to_bool(row["profile_b_callback"]),
        profile_a_interview_offered=bool(row["profile_a_interview_offered"]),
        profile_b_interview_offered=bool(row["profile_b_interview_offered"]),
        withdrawn=bool(row["withdrawn"]),
    )