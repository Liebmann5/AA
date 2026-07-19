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
    def recover_interrupted_tasks(self) -> None:
        """Re-queues tasks that were in-progress when a prior session crashed.

        Called once at orchestrator startup to ensure work is never lost
        due to an unclean shutdown.
        """

    @abstractmethod
    def get_queue_stats(self) -> dict:
        """Returns a summary of work queue status counts.

        Returns:
            Dict with keys: pending, in_progress, completed, failed, skipped.
        """