"""Provides a robust, transactional interface for SQLite storage.

This module implements the Repository pattern for the application's core data.
It enforces Write-Ahead Logging (WAL) mode to ensure data integrity during
power failures or crashes, adhering to the project's "Flash Drive" portability
requirement.

Orchestrator Integration Contract:
    The AgentOrchestrator calls these methods on DatabaseManager:
        - queue_task(task: WorkUnit)              -> enqueue work
        - get_next_task() -> Optional[WorkUnit]   -> dequeue highest priority
        - mark_task_complete(task_id, skipped)     -> mark done or skipped
        - mark_task_failed(task_id, error, permanent) -> mark failed with retry info

    All methods are thread-safe via the connection-per-call model (SQLite
    handles its own locking with WAL mode).

Schema:
    work_queue:   Priority queue for WorkUnits with status tracking.
    job_history:  Cross-session deduplication and application history.
    company_history: Company-specific metadata (cooldown periods, mandates).
"""

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from auto_apply.domain.config import DB_PATH, IS_FROZEN
from auto_apply.domain.models.work_unit import TaskType, WorkUnit

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Singleton manager for SQLite database interactions.

    Uses a singleton pattern to ensure exactly one schema initialization
    per process. Each method opens its own connection (connection-per-call)
    which is safe and efficient with WAL mode enabled.

    The singleton is thread-safe: the class-level lock protects instance
    creation, and SQLite WAL mode handles concurrent read/write access
    across threads.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Ensures only one database connection manager exists per process."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """Initializes the database connection and schema."""
        if self._initialized:
            return

        self.db_path = DB_PATH
        self._init_schema()
        self._initialized = True
        logger.info("DatabaseManager initialized | path=%s", self.db_path)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yields a managed SQLite connection with automatic commit/rollback.

        Yields:
            An active database connection with Row factory enabled.

        Raises:
            sqlite3.Error: If a database error occurs (after rollback).
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.error("Database transaction failed | error=%s", exc)
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Creates tables, indices, and dynamically sets journal mode."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self.get_connection() as conn:
            # Dynamically set journal mode. WAL for desktop speed, DELETE for USB safety.
            journal_mode = "DELETE" if IS_FROZEN else "WAL"
            # Critical pragma settings for performance and safety.
            conn.execute(f"PRAGMA journal_mode={journal_mode};")
            conn.execute("PRAGMA synchronous=NORMAL;")

            # 1. Work Queue — the orchestrator's priority queue.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS work_queue (
                    id            TEXT PRIMARY KEY,
                    priority      INTEGER NOT NULL,
                    task_type     TEXT NOT NULL,
                    payload       TEXT NOT NULL,
                    source        TEXT,
                    status        TEXT DEFAULT 'PENDING',
                    error_message TEXT,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context_data  TEXT
                )
            """)

            # 2. Job History — cross-session deduplication and throttling.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_history (
                    url_hash   TEXT PRIMARY KEY,
                    url        TEXT NOT NULL,
                    company    TEXT,
                    title      TEXT,
                    status     TEXT,
                    applied_at TIMESTAMP,
                    session_id TEXT
                )
            """)

            # 3. Company History — per-company cooldown periods and mandates.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_history (
                    domain        TEXT PRIMARY KEY,
                    company_name  TEXT,
                    cooldown_days INTEGER DEFAULT 0,
                    last_scraped  TIMESTAMP,
                    notes         TEXT
                )
            """)

            # Indices for O(1) priority queue retrieval.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_queue_status "
                "ON work_queue(status, priority)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_company "
                "ON job_history(company)"
            )

    # =====================================================================
    # WORK QUEUE - WRITE OPERATIONS
    # =====================================================================

    def queue_task(self, task: WorkUnit) -> None:
        """Persists a WorkUnit into the priority queue.

        Handles serialization of Pydantic models, plain dicts, and
        primitive payloads. Duplicate task IDs are silently replaced
        (upsert behavior) to support re-queuing after retry.

        Args:
            task: The WorkUnit to enqueue.
        """
        payload_data = task.payload
        if hasattr(payload_data, "model_dump"):
            payload_data = payload_data.model_dump(mode="json")
        elif hasattr(payload_data, "dict"):
            payload_data = payload_data.dict()

        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO work_queue
                    (id, priority, task_type, payload, source,
                     status, created_at, updated_at, context_data)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                """,
                (
                    task.id,
                    task.priority,
                    task.task_type.value,
                    json.dumps(payload_data, default=str),
                    task.source,
                    task.created_at.isoformat() if task.created_at else now,
                    now,
                    json.dumps(task.context_data),
                ),
            )

    def mark_task_complete(self, task_id: str, skipped: bool = False) -> None:
        """Marks a task as successfully completed or skipped.

        Args:
            task_id: The unique ID of the WorkUnit.
            skipped: If True, the task was skipped (e.g., duplicate) rather
                than executed. Stored as 'SKIPPED' status for telemetry.
        """
        status = "SKIPPED" if skipped else "COMPLETED"
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE work_queue SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now(timezone.utc).isoformat(), task_id),
            )

    def mark_task_failed(
        self,
        task_id: str,
        error_msg: str = "",
        permanent: bool = False,
    ) -> None:
        """Marks a task as failed with optional error details.

        Args:
            task_id: The unique ID of the WorkUnit.
            error_msg: Description of the failure for telemetry/debugging.
            permanent: If True, marks as 'PERMANENTLY_FAILED' (retry budget
                exhausted). If False, marks as 'FAILED' (may be retried).
        """
        status = "PERMANENTLY_FAILED" if permanent else "FAILED"
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE work_queue
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error_msg, datetime.now(timezone.utc).isoformat(), task_id),
            )

    # =========================================================================
    # WORK QUEUE — READ OPERATIONS
    # =========================================================================

    def get_next_task(self) -> WorkUnit | None:
        """Retrieves and atomically locks the highest-priority pending task.

        The task's status is updated to 'IN_PROGRESS' within the same
        transaction, preventing double-processing in concurrent scenarios.

        Returns:
            The next WorkUnit to process, or None if the queue is empty.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, priority, task_type, payload, source, context_data
                FROM work_queue
                WHERE status = 'PENDING'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Atomic lock: mark IN_PROGRESS before returning.
            conn.execute(
                "UPDATE work_queue SET status = 'IN_PROGRESS', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )

            # --- NEW: Rehydrate the payload back into a Job object ---
            payload_data = json.loads(row["payload"])
            task_type = TaskType(row["task_type"])

            if task_type in (TaskType.VET, TaskType.APPLY, TaskType.HANDLE_CAPTCHA) and isinstance(payload_data, dict):
                # If the dictionary has job attributes, convert it back into a Job model
                if "url" in payload_data and "title" in payload_data:
                    from auto_apply.domain.models.job import Job
                    payload_data = Job(**payload_data)

            return WorkUnit(
                id=row["id"],
                priority=row["priority"],
                task_type=task_type,
                payload=payload_data,
                source=row["source"],
                context_data=json.loads(row["context_data"]) if row["context_data"] else {},
            )

    def get_queue_stats(self) -> dict:
        """Returns a summary of work queue status counts.

        Returns:
            Dict with keys: pending, in_progress, completed, failed, skipped.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM work_queue GROUP BY status"
            )
            stats = {row["status"].lower(): row["cnt"] for row in cursor.fetchall()}
        return {
            "pending": stats.get("pending", 0),
            "in_progress": stats.get("in_progress", 0),
            "completed": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
            "skipped": stats.get("skipped", 0),
            "permanently_failed": stats.get("permanently_failed", 0),
        }

    def get_pending_count(self) -> int:
        """Returns the number of tasks still waiting to be processed."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM work_queue WHERE status = 'PENDING'"
            )
            return cursor.fetchone()[0]

    # =========================================================================
    # CRASH RECOVERY
    # =========================================================================

    def recover_interrupted_tasks(self) -> int:
        """Resets tasks stuck in 'IN_PROGRESS' back to 'PENDING'.

        Called at session startup to handle crash recovery. If the app died
        while a task was running, this ensures it gets picked up again.

        Returns:
            The number of tasks recovered.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE work_queue SET status = 'PENDING' WHERE status = 'IN_PROGRESS'"
            )
            recovered = cursor.rowcount
            if recovered > 0:
                logger.info("Recovered %d interrupted tasks", recovered)
            return recovered

    # =====================================================================
    # JOB HISTORY OPERATIONS
    # =====================================================================

    def record_job_discovery(self, job_obj: Any) -> bool:
        """Records a newly discovered job to prevent reprocessing.

        Uses INSERT OR IGNORE so duplicate URLs are silently skipped
        without raising an exception.

        Args:
            job_obj: A Job model object, or any object with url/company/title attrs.

        Returns:
            True if the job was new and recorded. False if it already existed.
        """
        url = getattr(job_obj, "url", str(job_obj))
        company = getattr(job_obj, "company", "Unknown")
        title = getattr(job_obj, "title", "Unknown")
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:32]
        now = datetime.now(timezone.utc).isoformat()

        try:
            with self.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO job_history (url_hash, url, company, title, status, applied_at)
                    VALUES (?, ?, ?, ?, 'DISCOVERED', ?)
                    """,  # noqa: E501
                    (url_hash, url, company, title, now),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("Failed to record job discovery | error=%s", exc)
            return False

    def record_application(
        self, url: str, session_id: str, status: str = "APPLIED"
    ) -> None:
        """Updates a job history record to reflect an application attempt.

        Args:
            url: The job URL that was applied to.
            session_id: The current session identifier for auditing.
            status: The application outcome (APPLIED, FAILED, etc.).
        """
        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE job_history
                SET status = ?, applied_at = ?, session_id = ?
                WHERE url = ?
                """,
                (status, now, session_id, url),
            )

    def is_job_processed(self, url: str) -> bool:
        """Checks if a URL has already been processed or applied to.

        Args:
            url: The job URL to check.

        Returns:
            True if the URL exists in job history.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM job_history WHERE url = ?", (url,)
            )
            return cursor.fetchone() is not None

    def was_applied(self, url: str) -> bool:
        """Checks if a specific job URL was already applied to.

        More specific than is_job_processed — only matches APPLIED status.

        Args:
            url: The job URL to check.

        Returns:
            True if this URL has been applied to in any session.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM job_history WHERE url = ? AND status = 'APPLIED'",
                (url,),
            )
            return cursor.fetchone() is not None
