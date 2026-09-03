"""Abstract contract for the agent's persistent priority task queue.

The AgentOrchestrator enqueues and dequeues WorkUnits exclusively through
this port. The concrete implementation (DatabaseManager) lives in
adapters/secondary/persistence/ and is wired up by
infrastructure/composition_root.py.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.work_unit import WorkUnit


class WorkQueuePort(ABC):
    """Port interface for the orchestrator's priority-ordered task queue."""

    @abstractmethod
    def queue_task(self, task: WorkUnit) -> None:
        """Persists a WorkUnit and makes it available for dispatch.

        Args:
            task: The WorkUnit to enqueue.
        """

    @abstractmethod
    def get_next_task(self) -> WorkUnit | None:
        """Returns the highest-priority pending WorkUnit, or None if empty.

        Returns:
            The next WorkUnit to process, or None when the queue is empty.
        """

    @abstractmethod
    def mark_task_complete(self, task_id: str, *, skipped: bool = False) -> None:
        """Marks a WorkUnit as completed or skipped.

        Args:
            task_id: The unique identifier of the WorkUnit to mark.
            skipped: If True, the task was intentionally skipped rather
                than successfully processed.
        """

    @abstractmethod
    def recover_interrupted_tasks(self) -> int:
        """Re-queues tasks that were in-progress when a prior session crashed.

        Called once at orchestrator startup to ensure work is never lost
        due to an unclean shutdown.

        Returns:
            The number of tasks recovered. SessionController reports this
            count at startup; the implementation has always returned it.
        """

    @abstractmethod
    def get_queue_stats(self) -> dict:
        """Returns a summary of work queue status counts.

        Returns:
            Dict with keys: pending, in_progress, completed, failed, skipped.
        """

    @abstractmethod
    def reschedule_for_retry(
        self,
        task_id: str,
        error_message: str,
        backoff_base_seconds: float = 30.0,
    ) -> bool:
        """Marks a failed task for retry with exponential backoff.

        Returns True if rescheduled, False if the retry budget is exhausted.
        Signature mirrors DatabaseManager exactly (parameter names are
        part of the Protocol contract for mypy).
        """

    @abstractmethod
    def mark_task_failed(
        self, task_id: str, error_msg: str = "", permanent: bool = False
    ) -> None:
        """Marks a task failed; permanent=True when retries are exhausted."""

    @abstractmethod
    def record_application_permanently(
        self, job_url: str, company: str, outcome: str, session_id: str
    ) -> None:
        """Persists an application to the permanent cross-session log."""

    @abstractmethod
    def has_applied_previously(self, job_url: str) -> bool:
        """True if this URL was successfully applied in any prior session."""
