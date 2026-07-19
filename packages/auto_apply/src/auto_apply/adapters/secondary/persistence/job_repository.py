"""Provides a high-level abstraction for Job data persistence.

This module acts as an Adapter between the Domain Layer (Job Objects) and the
Infrastructure Layer (DatabaseManager/SQLite). It ensures that business logic
does not need to write raw SQL queries.

It replaces the legacy `JobStateManager` and `AppliedJobsManager`.
"""

import logging
from datetime import datetime, timezone

from auto_apply.adapters.secondary.persistence.database import DatabaseManager
from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.repository_port import JobRepositoryPort

logger = logging.getLogger(__name__)


class JobRepository(JobRepositoryPort):
    """Repository pattern implementation for Job entities.

    This class provides semantic methods to store, retrieve, and update job
    states, backed by the robust SQLite persistence layer.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def add_job(self, job: Job) -> bool:
        """Records a newly discovered job.

        Args:
            job: The job entity to persist.

        Returns:
            True if the job was new and added, False if it already existed.
        """
        return self.db.record_job_discovery(job)

    def count_applications_for_company(self, company_name: str) -> int:
        """Counts completed applications submitted to a specific company.

        Args:
            company_name: The name of the company.

        Returns:
            The number of APPLIED entries for that company.
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM job_history WHERE company = ? AND status = 'APPLIED'",  # noqa: E501
                (company_name,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_last_applied_date(self, company_name: str) -> datetime | None:
        """Returns the timestamp of the most recent completed application.

        Args:
            company_name: The company to query.

        Returns:
            Datetime of the most recent application, or None if no history exists.
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT MAX(applied_at) FROM job_history WHERE company = ? AND status = 'APPLIED'",  # noqa: E501
                (company_name,)
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return None
            try:
                return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return None

    def get_company_mandate_cooldown(self, company_name: str) -> int:
        """Returns the cooldown period scraped from the company's application page.

        Args:
            company_name: The company to query.

        Returns:
            Required cooldown in days, or 0 if no mandate was ever recorded.
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT cooldown_days FROM company_history WHERE company_name = ?",
                (company_name,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def was_applied(self, url: str) -> bool:
        """Checks if a specific job URL was already applied to.

        Args:
            url: The unique job URL.

        Returns:
            True if this URL has been applied to in any session.
        """
        return self.db.was_applied(url)

    def mark_applied(self, job: Job, session_id: str, status: str = "APPLIED") -> None:
        """Updates a job's status after an application attempt.

        Args:
            job: The job entity.
            session_id: The current session ID.
            status: The outcome ('APPLIED', 'FAILED', 'REJECTED').
        """
        self.db.record_job_discovery(job)
        self.db.record_application(job.url, session_id, status)
        logger.info("Job marked as %s: %s @ %s", status, job.title, job.company)

    def get_recent_jobs(self, limit: int = 50) -> list[Job]:
        """Retrieves a list of recently processed jobs for reporting.

        Returns:
            A list of Job objects rehydrated from the DB.
        """
        jobs = []
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM job_history ORDER BY last_updated DESC LIMIT ?",
                (limit,)
            ).fetchall()

            for row in rows:
                jobs.append(Job(
                    title=row['title'],
                    company=row['company'] or "Unknown",
                    url=row['url'],
                    source="history",
                ))
        return jobs