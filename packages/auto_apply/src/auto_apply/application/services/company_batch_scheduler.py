"""Company batch scheduler for the application workflow.

Manages the application buffer: receives jobs from the orchestrator,
deduplicates against cross-session history, groups them by company,
and releases batches for processing when a threshold is reached.

Owned by ApplicationsWorkflow; invoked by AgentOrchestrator.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from auto_apply.domain.models.job_key import compute_job_key

if TYPE_CHECKING:
    from auto_apply.domain.models.job import Job

logger = logging.getLogger(__name__)


class CompanyBatchScheduler:
    """Manages the pending application buffer across companies.

    The single authoritative cross‑session deduplication call site.
    Both the “buffer a new application” path and the “flush a ready batch”
    path call :meth:`is_duplicate` — no two copies of the DB query exist.

    Args:
        task_queue:      WorkQueuePort for cross‑session dedup lookups.
        batch_threshold: Number of jobs for a company to trigger a batch process.
    """

    def __init__(self, task_queue, batch_threshold: int = 3) -> None:
        self._task_queue = task_queue
        self._batch_threshold = max(1, batch_threshold)
        # {normalized_company_name: [Job, ...]}
        self._buffer: dict[str, list] = defaultdict(list)

    # ── Cross‑session dedup — single implementation used by all paths ─────

    def is_duplicate(self, job_url: str, job_key: str | None = None) -> bool:
        """Cross-session dedup, fail closed.

        True when a blocking outcome is on record for this URL or job key —
        an outcome AA cannot rule out as received by the site (SUBMITTED,
        PROBABLY_SUBMITTED, AMBIGUOUS, UNKNOWN). When the store cannot answer,
        this returns True: a wrongly blocked job costs a review; a wrongly
        sent one is a duplicate application under the user's name.
        """
        try:
            return self._task_queue.has_applied_previously(
                job_url, job_key=job_key
            )
        except Exception as exc:
            logger.error(
                "Dedup check failed; refusing to buffer | error=%s",
                type(exc).__name__,
            )
            return True

    # ── Buffering ──────────────────────────────────────────────────────────

    def buffer_job(self, job: "Job") -> bool:
        """Attempt to add *job* to the company buffer.

        Cross‑session dedup is performed here.  If the job is a duplicate,
        it is silently skipped and ``False`` is returned.

        Returns:
            ``True`` if the job was accepted into the buffer,
            ``False`` if it was rejected (duplicate).
        """
        if self.is_duplicate(job.url, job_key=compute_job_key(job).as_string):
            logger.info(
                "Scheduler: duplicate (cross‑session) — not buffering | %s @ %s",
                job.title,
                job.company,
            )
            return False

        company_key = job.company.lower().strip()
        self._buffer[company_key].append(job)
        logger.info(
            "Scheduler: buffered | company=%s buffer_size=%d",
            job.company,
            len(self._buffer[company_key]),
        )
        return True

    # ── Readiness queries (used by orchestrator loop) ───────────────────────

    def check_batch_ready(self) -> bool:
        """Return ``True`` if any company bucket has reached the batch threshold."""
        return any(
            len(jobs) >= self._batch_threshold for jobs in self._buffer.values()
        )

    def has_any_buffered(self) -> bool:
        """Return ``True`` if there is at least one pending application."""
        return any(len(jobs) > 0 for jobs in self._buffer.values())

    # ── Draining (called by orchestrator when ready) ────────────────────────

    def pop_best_ready_batch(self) -> tuple[str, list["Job"]]:
        """Remove and return the ready company with the largest buffer.

        Only call when :meth:`check_batch_ready` returns ``True``.

        Returns:
            ``(company_key, jobs)`` tuple where ``jobs`` is the list of
            pending applications for that company.
        """
        target_company = max(
            (
                company
                for company, jobs in self._buffer.items()
                if len(jobs) >= self._batch_threshold
            ),
            key=lambda c: len(self._buffer[c]),
        )
        return target_company, self._buffer.pop(target_company)

    def flush_all_batches(self) -> dict[str, list["Job"]]:
        """Remove and return ALL remaining buffered jobs, clearing the buffer.

        Returns:
            Mapping of company key → list of jobs.
        """
        remaining: dict[str, list] = {}
        # Iterate a snapshot of keys because we are popping inside the loop.
        for company_key in list(self._buffer.keys()):
            jobs = self._buffer.pop(company_key)
            if jobs:
                remaining[company_key] = jobs
        return remaining