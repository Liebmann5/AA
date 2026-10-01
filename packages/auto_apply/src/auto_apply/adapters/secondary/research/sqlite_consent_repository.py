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

from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.ports.consent_repository_port import ConsentRepositoryPort

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
        provenance_key_path: Path to the private research signing key, also
            deleted by purge_research_data() so a purge rotates the
            installation's research identity. composition_root injects
            domain.config.PROVENANCE_KEY_PATH; None disables key handling
            (tests that never signed anything).
    """

    def __init__(
        self,
        consent_db_path: Path,
        research_db_path: Path,
        provenance_key_path: Path | None = None,
    ) -> None:
        self._consent_db_path = consent_db_path
        self._research_db_path = research_db_path
        self._provenance_key_path = provenance_key_path
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

    @staticmethod
    def _research_tables(conn: sqlite3.Connection) -> list[str]:
        """Every real table in the research database, derived live.

        Schema-derived, never a literal list: the consent dialog promises
        ALL data is deleted, and a hard-coded list is exactly how six tables
        (discovery_*, detector_*, research_provenance) silently survived the
        old purge. A table added to the schema cannot escape this query.
        """
        return [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]

    def _count_research_rows(self) -> int:
        try:
            with self._get_connection(self._research_db_path) as conn:
                return sum(
                    conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 — names from sqlite_master
                    for t in self._research_tables(conn)
                )
        except Exception as exc:
            logger.warning(
                "SqliteConsentRepository | row count before purge failed: %s", exc
            )
            return 0

    def _delete_db_files(self) -> bool:
        """Unlink the database and its WAL sidecars. True when all are gone.

        Complete by construction: no row, WAL page or freelist remnant can
        survive, and no future table can escape. Sidecars first, main file
        last — on Windows a locked sidecar means a locked main file, so the
        row-deletion fallback then finds a coherent database. The sidecars
        may hold the only copy of recent rows; deleting them is the point of
        a purge, and it is user data the user asked to delete, not a repo
        file (the never-delete rule governs the repository, not this).
        """
        ok = True
        for suffix in ("-shm", "-wal", ""):
            target = Path(str(self._research_db_path) + suffix)
            if not target.exists():
                continue
            try:
                target.unlink()
            except OSError as exc:
                logger.warning(
                    "SqliteConsentRepository | could not delete %s (%s) — "
                    "falling back to row deletion",
                    target, exc,
                )
                ok = False
        return ok

    def _delete_db_rows(self) -> None:
        """Fallback: erase every row, fold the WAL back, then VACUUM.

        Used when file deletion failed (another handle open — a Windows AV
        or indexer, a concurrent flush). The deleting connection turns
        secure_delete ON first, so deleted rows are overwritten with zeros
        rather than left in free space: SQLite's default is OFF (it is OFF
        in the SQLite bundled with Windows CPython), and without it the
        checkpoint below copies the purged bytes into the main file, where
        they stay for as long as any other connection is open (measured on
        Windows 2026-10-01). DELETEs run in one transaction and are
        committed explicitly; wal_checkpoint(TRUNCATE) then writes the
        zeroed pages into the main file and truncates the WAL; VACUUM
        compacts in a separate autocommit connection (SQLite forbids VACUUM
        inside a transaction). Weaker than file deletion in exactly one
        way: a reader holding an open read transaction can stop the
        checkpoint from completing, and the WAL is truncated only when it
        finishes. Every use of this path is logged by _delete_db_files.
        """
        try:
            with self._get_connection(self._research_db_path) as conn:
                # Per-connection, so it is set on the connection that deletes.
                conn.execute("PRAGMA secure_delete = ON")
                for table in self._research_tables(conn):
                    conn.execute(f"DELETE FROM {table}")  # noqa: S608 — names from sqlite_master
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info(
                "SqliteConsentRepository | purge fallback: all rows deleted"
            )
        except Exception as exc:
            logger.error(
                "SqliteConsentRepository | purge row deletion failed: %s", exc
            )
            return
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

    def _delete_provenance_key(self) -> None:
        """Rotate the installation's research identity: delete the key.

        A purge that kept the key would let a recipient of two contributions
        link the post-withdrawal one to the purged one — defeating the
        withdrawal. The next consented session generates a fresh key lazily
        (ProvenanceSigner) and re-stores its public half. Deleting user data
        at the user's explicit request is this method's job. A delete that
        fails (locked file) leaves the old identity intact; that is logged,
        and the next purge tries again.
        """
        key = self._provenance_key_path
        if key is None or not key.exists():
            return
        try:
            key.unlink()
            logger.info(
                "SqliteConsentRepository | provenance key deleted — research "
                "identity rotated"
            )
        except OSError as exc:
            logger.warning(
                "SqliteConsentRepository | could not delete provenance key "
                "%s (%s); the installation's research identity is unchanged",
                key, exc,
            )

    def purge_research_data(self) -> int:
        """Delete ALL research data: every row, the database files, the key.

        Primary path — file deletion: the .db and its -wal/-shm sidecars
        are unlinked. Fallback — row deletion: if any unlink fails (another
        handle open), every table found in sqlite_master is DELETEd, the WAL
        is checkpointed and truncated, and the file is VACUUMed. The table
        list is derived from the live schema in both paths, so the schema
        can never outgrow the purge (the old five-table literal let six
        tables survive). research_provenance goes with the rest, and the
        private provenance key is deleted so the purge also rotates the
        installation's research identity.

        Not touched: the consent record itself (it lives in its own
        database and is the record that the user withdrew), and export
        bundles already written under the reports directory — they left the
        data home when the user exported them; the consent dialog says so.

        Returns:
            Total number of rows deleted across all research tables
            (0 when no database exists).
        """
        total_deleted = 0
        if self._research_db_path.exists():
            total_deleted = self._count_research_rows()
            if not self._delete_db_files():
                self._delete_db_rows()
            else:
                logger.info(
                    "SqliteConsentRepository | Purged %d rows (database files "
                    "deleted)",
                    total_deleted,
                )
        self._delete_provenance_key()
        return total_deleted