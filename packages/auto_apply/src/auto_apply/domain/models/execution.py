"""Execution mode and configuration models.

This module defines the ExecutionMode enum and ExecutionConfiguration
dataclass, which together describe HOW a session is configured to run.

These models are consumed by CapabilitiesRegistry during config merging
and by the orchestrator when deciding execution behavior (e.g., whether
to use batch processing, what concurrency level to target).

Design Note:
    ExecutionMode is NOT the same as a domain strategy. ExecutionMode
    describes the session-level execution approach (sequential, batched,
    parallel). Domain strategies (stream vs batch for discovery, field-by-field
    vs full-page for applications) are separate abstractions that live in
    their respective domain strategy directories.

Example:
    >>> from core.models.execution import ExecutionMode, ExecutionConfiguration
    >>>
    >>> config = ExecutionConfiguration(
    ...     mode=ExecutionMode.SEQUENTIAL,
    ...     max_concurrent_tasks=1,
    ...     enable_company_batching=True,
    ... )
"""

from dataclasses import dataclass
from enum import Enum, auto


class ExecutionMode(Enum):
    """Defines the session-level execution approach.

    The mode is selected during session initialization based on hardware
    capabilities (from CapabilitiesRegistry) and user preference. Low-resource
    environments are forced to SEQUENTIAL regardless of preference.
    """

    SEQUENTIAL = auto()
    """Tasks are processed one at a time in priority order.
    This is the default and the only mode guaranteed to work on all hardware.
    Single browser instance, single thread for task dispatch.
    """

    BATCHED = auto()
    """Tasks are grouped by company domain before processing.
    Still single-threaded dispatch, but reduces browser navigation overhead
    by processing multiple jobs at the same ATS domain in sequence.
    Requires: enable_company_batching=True in effective config.
    """

    # Future modes (not yet implemented):
    #
    # PARALLEL = auto()
    # """Multiple browser instances process tasks concurrently.
    # Requires: multi-core CPU, >= 4GB RAM, multiple browser installations.
    # Not recommended for worst-case users.
    # """


@dataclass(frozen=True)
class ExecutionConfiguration:
    """Immutable configuration for a single session's execution behavior.

    Built once during session initialization by CapabilitiesRegistry.build()
    and passed to the orchestrator. Cannot be mutated during a session.

    Frozen=True enforces immutability — any attempt to modify a field after
    construction raises FrozenInstanceError. This prevents subtle bugs where
    mid-session config changes would leave the system in an inconsistent state.

    Attributes:
        mode: The execution approach for this session.
        max_concurrent_tasks: Maximum tasks that can run simultaneously.
            Always 1 for SEQUENTIAL and BATCHED modes.
        enable_company_batching: Whether to group APPLY tasks by company.
        company_batch_threshold: Minimum jobs per company to trigger a batch.
        checkpoint_interval: Save checkpoint every N completed tasks.
        task_retry_limit: Maximum retry attempts for a failed task.
        max_applications_per_session: Session-level application cap.
        max_discovery_results_per_query: Discovery result limit per provider.
    """

    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    max_concurrent_tasks: int = 1
    enable_company_batching: bool = True
    company_batch_threshold: int = 3
    checkpoint_interval: int = 5
    task_retry_limit: int = 3
    max_applications_per_session: int = 50
    max_discovery_results_per_query: int = 30

    def __post_init__(self) -> None:
        """Validates configuration invariants after construction."""
        if self.mode == ExecutionMode.SEQUENTIAL and self.max_concurrent_tasks != 1:
            # Use object.__setattr__ because frozen=True prevents normal assignment.
            object.__setattr__(self, "max_concurrent_tasks", 1)

        if self.company_batch_threshold < 1:
            object.__setattr__(self, "company_batch_threshold", 1)

        if self.checkpoint_interval < 1:
            object.__setattr__(self, "checkpoint_interval", 1)
