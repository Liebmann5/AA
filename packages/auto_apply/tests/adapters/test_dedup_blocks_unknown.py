"""Fail-closed cross-session dedup (P0-2), now a regression guard.

Teeth: AMBIGUOUS and UNKNOWN must block, skipped/failed/gate-blocked must
not, the job key must join and must be written, legacy rows must keep
blocking, an old-schema database must migrate, and the batch scheduler must
refuse when the store cannot answer.
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from auto_apply.application.services.company_batch_scheduler import CompanyBatchScheduler
from auto_apply.domain.ports.work_queue_port import WorkQueuePort


@pytest.fixture
def db(tmp_path, monkeypatch):
    import auto_apply.adapters.secondary.persistence.database as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "aa_test.db")
    db_module.DatabaseManager._instance = None
    manager = db_module.DatabaseManager()
    try:
        yield manager
    finally:
        db_module.DatabaseManager._instance = None


class _Jobish:
    url = "https://boards.example.io/jobs/9"
    company = "Acme"
    title = "Engineer"
    metadata: dict = {}


def _record(db, url, outcome, key=None):
    db.record_application_permanently(
        job_url=url, company="Acme", outcome=outcome, session_id="s1", job_key=key,
    )


def test_ambiguous_blocks_reapplication(db):
    _record(db, "https://boards.example.io/jobs/1", "AMBIGUOUS")
    assert db.has_applied_previously("https://boards.example.io/jobs/1") is True


def test_unknown_blocks_reapplication(db):
    _record(db, "https://boards.example.io/jobs/2", "UNKNOWN")
    assert db.has_applied_previously("https://boards.example.io/jobs/2") is True


def test_skipped_failed_and_gate_blocked_do_not_block(db):
    _record(db, "https://boards.example.io/jobs/3", "USER_SKIPPED")
    _record(db, "https://boards.example.io/jobs/4", "FAILED_NAVIGATION")
    _record(db, "https://boards.example.io/jobs/5", "SUBMISSION_GATE_BLOCKED")
    assert db.has_applied_previously("https://boards.example.io/jobs/3") is False
    assert db.has_applied_previously("https://boards.example.io/jobs/4") is False
    assert db.has_applied_previously("https://boards.example.io/jobs/5") is False


def test_job_key_blocks_even_when_the_url_differs(db):
    _record(db, "https://boards.example.io/jobs/6", "SUBMITTED", key="boards.example.io|/jobs/6")
    assert db.has_applied_previously(
        "https://other.example.io/redirect?to=6", job_key="boards.example.io|/jobs/6"
    ) is True


def test_a_legacy_row_with_no_key_still_blocks_by_url(db):
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO applied_jobs (job_url, company, outcome, session_id, applied_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("https://boards.example.io/jobs/7", "Acme", "SUBMITTED", "s0", "2026-01-01"),
        )
    assert db.has_applied_previously("https://boards.example.io/jobs/7") is True


def test_the_key_is_written(db):
    _record(db, "https://boards.example.io/jobs/8", "SUBMITTED", key="boards.example.io|/jobs/8")
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT job_key FROM applied_jobs WHERE job_url = ?",
            ("https://boards.example.io/jobs/8",),
        ).fetchone()
    assert row["job_key"] == "boards.example.io|/jobs/8"


def test_job_history_unknown_status_blocks(db):
    db.record_job_discovery(_Jobish(), session_id="s1")
    db.record_application("https://boards.example.io/jobs/9", "s1", "UNKNOWN")
    assert db.has_applied_previously("https://boards.example.io/jobs/9") is True


def test_pre_p02_database_migrates_and_still_blocks(tmp_path, monkeypatch):
    """A database from before the job_key column: the migration must add the
    column, and an AMBIGUOUS row written then must still block."""
    import auto_apply.adapters.secondary.persistence.database as db_module

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE applied_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL UNIQUE,
            company TEXT,
            outcome TEXT,
            session_id TEXT,
            applied_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """INSERT INTO applied_jobs (job_url, company, outcome, session_id, applied_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("https://boards.example.io/jobs/old", "Acme", "AMBIGUOUS", "s0", "2026-01-01"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.DatabaseManager._instance = None
    try:
        manager = db_module.DatabaseManager()
        assert manager.has_applied_previously("https://boards.example.io/jobs/old") is True
        with manager.get_connection() as check_conn:
            columns = {row[1] for row in check_conn.execute("PRAGMA table_info(applied_jobs)")}
        assert "job_key" in columns
    finally:
        db_module.DatabaseManager._instance = None


class _RaisingQueue:
    def has_applied_previously(self, job_url, job_key=None):
        raise RuntimeError("database unavailable")


def test_the_scheduler_fails_closed_on_a_store_error():
    scheduler = CompanyBatchScheduler(task_queue=_RaisingQueue())
    assert scheduler.is_duplicate("https://boards.example.io/jobs/10") is True


def test_the_port_declares_the_job_key_parameter():
    assert "job_key" in inspect.signature(WorkQueuePort.has_applied_previously).parameters
    assert "job_key" in inspect.signature(WorkQueuePort.record_application_permanently).parameters
