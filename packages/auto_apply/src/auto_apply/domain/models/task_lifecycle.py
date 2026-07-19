"""Task-level lifecycle state machine for the Typed Task Runtime Kernel.

Separate from AgentState (which tracks the overall session state).
Every WorkUnit moves through these states as it executes.
These states live in the database's work_queue.status column.

Current database statuses:
    PENDING       — queued, waiting to be claimed
    IN_PROGRESS   — claimed, currently executing
    COMPLETED     — finished successfully
    FAILED        — failed, may retry
    PERMANENTLY_FAILED — retry budget exhausted
    SKIPPED       — intentionally skipped (duplicate, policy)

Future statuses (Phase 5+):
    WAITING_RESOURCE  — waiting for a browser/model/human lease
    WAITING_HUMAN     — blocked on HITL approval
    WAITING_EXTERNAL  — blocked on CAPTCHA, network, or other external
    RETRY_SCHEDULED   — scheduled for retry after backoff
    CANCELLED         — cancelled by user or policy
    COMPENSATED       — side effects reversed (advanced idempotency)
"""

from enum import Enum


class TaskLifecycleState(str, Enum):
    """All valid states a WorkUnit can occupy in the database."""

    # Current states (already in database schema)
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PERMANENTLY_FAILED = "PERMANENTLY_FAILED"
    SKIPPED = "SKIPPED"

    # Future states (Phase 5 — add to schema when needed)
    WAITING_RESOURCE = "WAITING_RESOURCE"
    WAITING_HUMAN = "WAITING_HUMAN"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CANCELLED = "CANCELLED"


# Legal state transitions for the current implementation.
# Extended in Phase 5 to include WAITING_* transitions.
VALID_TRANSITIONS: dict[TaskLifecycleState, set[TaskLifecycleState]] = {
    TaskLifecycleState.PENDING: {
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.SKIPPED,
    },
    TaskLifecycleState.IN_PROGRESS: {
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.PERMANENTLY_FAILED,
        TaskLifecycleState.SKIPPED,
        TaskLifecycleState.WAITING_HUMAN,    # Phase 5
        TaskLifecycleState.WAITING_EXTERNAL, # Phase 5
    },
    TaskLifecycleState.FAILED: {
        TaskLifecycleState.PENDING,          # Re-queued for retry
        TaskLifecycleState.PERMANENTLY_FAILED,
        TaskLifecycleState.CANCELLED,
    },
    TaskLifecycleState.WAITING_HUMAN: {
        TaskLifecycleState.IN_PROGRESS,      # User approved
        TaskLifecycleState.CANCELLED,        # User declined
        TaskLifecycleState.SKIPPED,
    },
    TaskLifecycleState.WAITING_EXTERNAL: {
        TaskLifecycleState.IN_PROGRESS,      # External resolved
        TaskLifecycleState.FAILED,           # Timed out
    },
    # Terminal states — no outbound transitions
    TaskLifecycleState.COMPLETED: set(),
    TaskLifecycleState.PERMANENTLY_FAILED: set(),
    TaskLifecycleState.SKIPPED: set(),
    TaskLifecycleState.CANCELLED: set(),
}