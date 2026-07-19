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
        - reschedule_for_retry(task_id, error)     -> exponential backoff retry
        - has_applied_previously(job_url) -> bool  -> cross-session dedup check
        - record_application_permanently(...)       -> persist application to log

    All methods are thread-safe via the connection-per-call model (SQLite
    handles its own locking with WAL mode).

Schema:
    work_queue:   Priority queue for WorkUnits with status tracking.
    job_history:  Cross-session deduplication and application history.
    applied_jobs: Permanent application log — never cleared between sessions.
    company_history: Company-specific metadata (cooldown periods, mandates).
"""

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from auto_apply.domain.config import DB_PATH, IS_FROZEN
from auto_apply.domain.models.work_unit import TaskType, WorkUnit

if TYPE_CHECKING:
    from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile

logger = logging.getLogger(__name__)

# Maximum retry attempts for failed tasks before permanent failure.
MAX_RETRY_ATTEMPTS: int = 3


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
        self._capability_profile: "ResolvedCapabilityProfile | None" = None
        self._init_schema()
        self._initialized = True
        logger.info("DatabaseManager initialized | path=%s", self.db_path)

    def set_capability_profile(
        self, profile: "ResolvedCapabilityProfile"
    ) -> None:
        """Store the session capability profile for queue-task validation.

        Called once by the composition root after the driver cascade completes.
        When set, queue_task() will reject tasks whose TaskType requires
        capabilities that are not available in this session (e.g. APPLY task
        when no browser driver was acquired).

        Args:
            profile: The frozen ResolvedCapabilityProfile for this session.
        """
        self._capability_profile = profile
        logger.debug(
            "DatabaseManager: capability profile set | mode=%s",
            profile.mode_name,
        )

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
                    context_data  TEXT,
                    retry_count   INTEGER DEFAULT 0,
                    retry_after   TEXT DEFAULT NULL
                )
            """)

            # ── Migration: add retry columns if upgrading from older schema ──
            try:
                conn.execute("SELECT retry_count FROM work_queue LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE work_queue ADD COLUMN retry_count INTEGER DEFAULT 0")
                logger.info("DatabaseManager: added retry_count column to work_queue")

            try:
                conn.execute("SELECT retry_after FROM work_queue LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE work_queue ADD COLUMN retry_after TEXT DEFAULT NULL")
                logger.info("DatabaseManager: added retry_after column to work_queue")

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

            # 3. Applied Jobs — permanent application log; NEVER cleared.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applied_jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_url     TEXT    NOT NULL UNIQUE,
                    company     TEXT,
                    outcome     TEXT,
                    session_id  TEXT,
                    applied_at  TEXT    NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_applied_jobs_url ON applied_jobs(job_url)"
            )

            # 4. Company History — per-company cooldown periods and mandates.
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

        Validates the payload type against TASK_PAYLOAD_REGISTRY before
        inserting. This is the queue's last line of defense against malformed
        tasks. A ValueError here surfaces at task-creation time rather than
        at task-execution time (where it would be a confusing AttributeError).

        When a capability profile is active, additionally rejects tasks whose
        TaskType requires capabilities not available in this session (e.g.
        APPLY task when no browser driver was acquired).

        Handles serialization of Pydantic models, plain dicts, and
        primitive payloads. Duplicate task IDs are silently replaced
        (upsert behavior) to support re-queuing after retry.

        Args:
            task: The WorkUnit to enqueue.

        Raises:
            ValueError: If the payload type does not match the task type contract,
                or if the task type is not allowed by the capability profile.
        """
        # ── Capability gating ────────────────────────────────────────────────
        if self._capability_profile is not None:
            if not self._capability_profile.can_run_task(task.task_type.value):
                raise ValueError(
                    f"Cannot queue {task.task_type.name} task: "
                    f"current capability profile "
                    f"({self._capability_profile.mode_name}) "
                    f"does not support this task type. "
                    f"Allowed types: {self._capability_profile.allowed_task_types}"
                )

        # ── Payload type validation (TTK contract enforcement) ────────────────
        try:
            from auto_apply.domain.models.task_payloads import validate_work_unit_payload
            validate_work_unit_payload(task.task_type.value, task.payload)
        except ValueError as exc:
            logger.error(
                "PAYLOAD VALIDATION FAILED | task_type=%s error=%s | "
                "Task rejected — this is a programming error, not a runtime error.",
                task.task_type.name, exc,
            )
            raise

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
    # RETRY WITH EXPONENTIAL BACKOFF
    # =========================================================================

    def reschedule_for_retry(
        self,
        task_id: str,
        error_message: str,
        backoff_base_seconds: float = 30.0,
    ) -> bool:
        """Mark a failed task for retry with exponential backoff.

        Returns True if rescheduled, False if max retries exceeded
        (permanently failed). Tasks with retry_after in the future are
        skipped by get_next_task().

        Backoff schedule:
            Attempt 1 → wait 30s
            Attempt 2 → wait 60s
            Attempt 3 → wait 120s
            Attempt 4+ → PERMANENTLY_FAILED

        Args:
            task_id: The unique ID of the WorkUnit.
            error_message: Human-readable description of the failure.
            backoff_base_seconds: Base wait time in seconds (doubles each retry).

        Returns:
            True if rescheduled, False if permanently failed.
        """
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT retry_count FROM work_queue WHERE id = ?", (task_id,)
            ).fetchone()

            if row is None:
                logger.warning(
                    "reschedule_for_retry: task %s not found", task_id[:8]
                )
                return False

            retry_count = (row["retry_count"] or 0) + 1

            if retry_count > MAX_RETRY_ATTEMPTS:
                conn.execute(
                    """UPDATE work_queue
                       SET status = 'PERMANENTLY_FAILED',
                           error_message = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (
                        f"Max retries ({MAX_RETRY_ATTEMPTS}) exceeded. "
                        f"Last error: {error_message[:200]}",
                        datetime.now(timezone.utc).isoformat(),
                        task_id,
                    ),
                )
                logger.warning(
                    "Task permanently failed after %d attempts | id=%s",
                    retry_count - 1, task_id[:8],
                )
                return False

            backoff_seconds = backoff_base_seconds * (2 ** (retry_count - 1))
            retry_after = datetime.now(timezone.utc) + timedelta(
                seconds=backoff_seconds
            )

            conn.execute(
                """UPDATE work_queue
                   SET status = 'PENDING',
                       retry_count = ?,
                       retry_after = ?,
                       error_message = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    retry_count,
                    retry_after.isoformat(),
                    error_message[:200],
                    datetime.now(timezone.utc).isoformat(),
                    task_id,
                ),
            )
            logger.info(
                "Task rescheduled for retry %d/%d | wait=%.0fs | id=%s",
                retry_count,
                MAX_RETRY_ATTEMPTS,
                backoff_seconds,
                task_id[:8],
            )
            return True

    # =========================================================================
    # WORK QUEUE — READ OPERATIONS
    # =========================================================================

    def get_next_task(self) -> WorkUnit | None:
        """Retrieves and atomically locks the highest-priority pending task.

        Uses an atomic UPDATE...RETURNING (SQLite 3.35+) to claim the task
        in a single database operation, eliminating the TOCTOU race between
        SELECT and UPDATE in multi-threaded or multi-process scenarios.

        The task's status is updated to 'IN_PROGRESS' within the same
        transaction, preventing double-processing.

        Respects retry_after — tasks whose retry_after timestamp is in the
        future are skipped until the backoff elapses.

        Returns:
            The next WorkUnit to process, or None if the queue is empty.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            # Atomic claim: UPDATE ... RETURNING locks the row in one step.
            # Falls back gracefully to SELECT+UPDATE if SQLite < 3.35.
            try:
                cursor = conn.execute(
                    """
                    UPDATE work_queue
                    SET status = 'IN_PROGRESS', updated_at = ?
                    WHERE id = (
                        SELECT id FROM work_queue
                        WHERE status = 'PENDING'
                          AND (retry_after IS NULL OR retry_after <= ?)
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1
                    )
                    RETURNING id, priority, task_type, payload, source, context_data
                    """,
                    (now_iso, now_iso),
                )
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                # SQLite < 3.35 — fall back to SELECT + UPDATE
                cursor = conn.execute(
                    """
                    SELECT id, priority, task_type, payload, source, context_data
                    FROM work_queue
                    WHERE status = 'PENDING'
                      AND (retry_after IS NULL OR retry_after <= ?)
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (now_iso,),
                )
                row = cursor.fetchone()

                if row:
                    conn.execute(
                        "UPDATE work_queue SET status = 'IN_PROGRESS', updated_at = ? WHERE id = ?",
                        (now_iso, row["id"]),
                    )

            if not row:
                return None

            payload_data = json.loads(row["payload"])
            task_type = TaskType(row["task_type"])

            if task_type in (TaskType.VET, TaskType.APPLY, TaskType.HANDLE_CAPTCHA) and isinstance(payload_data, dict):
                # If the dictionary has job attributes, convert it back into a Job model
                if "url" in payload_data and "title" in payload_data:
                    from auto_apply.domain.models.job import Job
                    payload_data = Job(**payload_data)

            # ── Validate recovered payload ────────────────────────────────────
            try:
                from auto_apply.domain.models.task_payloads import validate_work_unit_payload
                validate_work_unit_payload(task_type.value, payload_data)
            except ValueError as exc:
                logger.error(
                    "Skipping corrupt WorkUnit from DB | id=%s error=%s",
                    row["id"], exc,
                )
                conn.execute(
                    "UPDATE work_queue SET status = 'PERMANENTLY_FAILED', error_message = ? WHERE id = ?",
                    (str(exc)[:500], row["id"]),
                )
                return None

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
    # CROSS-SESSION DUPLICATE APPLICATION PREVENTION
    # =========================================================================

    def has_applied_previously(self, job_url: str) -> bool:
        """Check if AA has ever submitted an application to this job URL.

        Checks the applied_jobs table across all past sessions.  Returns
        True only for outcomes that represent a real submission (SUBMITTED,
        PROBABLY_SUBMITTED).  Failed, skipped, and blocked jobs are not
        counted as previously applied — they can be retried.

        Args:
            job_url: The job posting URL to check.

        Returns:
            True if this URL has been successfully submitted in any session.
        """
        with self.get_connection() as conn:
            row = conn.execute(
                """SELECT id FROM applied_jobs
                    WHERE job_url = ?
                      AND outcome IN ('SUBMITTED', 'PROBABLY_SUBMITTED')
                    LIMIT 1""",
                (job_url,),
            ).fetchone()
            return row is not None

    def record_application_permanently(
        self,
        job_url: str,
        company: str,
        outcome: str,
        session_id: str,
    ) -> None:
        """Persist an application to the permanent applied_jobs log.

        This table is the cross-session deduplication record.  It is NEVER
        cleared between sessions (unlike work_queue).  Uses INSERT OR REPLACE
        on the UNIQUE job_url column so re-submissions are idempotent.

        Args:
            job_url: The job posting URL that was applied to.
            company: Company name for reporting.
            outcome: The ApplicationEvidence outcome string.
            session_id: Current session identifier.
        """
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO applied_jobs
                   (job_url, company, outcome, session_id, applied_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    job_url,
                    company,
                    outcome,
                    session_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        logger.debug(
            "Applied jobs log updated | url=%.60s outcome=%s", job_url, outcome,
        )

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