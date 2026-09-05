"""Volatile working memory for an active agent session.

This module provides ExecutionContext, which is the single shared state
container passed through the entire orchestration pipeline. Every domain
engine, health monitor, and service that needs to know "what is happening
right now in this session" reads from the context.

Design Philosophy:
    The context is the session's nervous system — not a god object.
    It holds facts about the session (who, when, how far along) and
    provides safe mutation methods for updating stats. It does NOT hold
    references to infrastructure (no browser driver, no DB connection).
    Those live in the orchestrator and are injected per-call.

    Keeping infrastructure out of the context is what makes it safely
    serializable for checkpointing and safely passable to domain engines
    that should not have access to the browser directly.

Thread Safety:
    update_stats() is protected by a lock. Health monitors and research
    collectors running on daemon threads may call this method concurrently
    with the main orchestrator loop. All other attributes are written only
    from the main orchestrator thread.

Checkpoint Integration:
    to_dict() produces a JSON-serializable snapshot for CheckpointManager.
    restore_from_checkpoint() applies a previously saved snapshot to a
    fresh ExecutionContext, restoring progress counters after a crash.

Example:
    >>> from auto_apply.application.agent.context import ExecutionContext
    >>> from auto_apply.domain.models.profile import UserProfile
    >>>
    >>> profile = UserProfile.load()
    >>> context = ExecutionContext(profile=profile, session_id="session_1234")
    >>> context.update_stats("discovered", 15)
    >>> context.update_stats("applied", 3)
    >>> print(context.stats.summary_line())
    Discovered: 15 | Vetted: 0 | Applied: 3 | Failed: 0 | Duration: 00:00:02
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.resources import RuntimeProfile
from auto_apply.domain.models.work_unit import WorkUnit

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Session Statistics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionStatistics:
    """Accumulated metrics for one agent session.

    All counters are incremented via ExecutionContext.update_stats() which
    is thread-safe. Do not mutate fields directly from outside that method.

    Attributes:
        jobs_discovered: Total job listings found by DiscoveryEngine.
        jobs_vetted: Jobs that passed all VettingEngine filters.
        applications_submitted: Applications successfully submitted.
        applications_failed: Applications that raised errors or were rejected
            by the form itself (e.g., missing required field with no answer).
        applications_skipped: Applications skipped due to prior-session
            history (already applied). Not a failure — informational.
        captchas_escalated: CAPTCHA challenges escalated to a human via the
            HITL gate. Detection signal, kept distinct from generic approvals.
        provider_timeouts: Provider workers reported stuck by the watchdog.
        start_time: UTC datetime when this session began.
    """
    jobs_discovered:        int = 0
    jobs_vetted:            int = 0
    applications_submitted: int = 0
    applications_failed:    int = 0
    applications_skipped:   int = 0
    captchas_escalated:     int = 0
    provider_timeouts:      int = 0
    start_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def duration(self) -> timedelta:
        """Elapsed time since the session started."""
        return datetime.now(timezone.utc) - self.start_time

    @property
    def duration_str(self) -> str:
        """Elapsed time formatted as HH:MM:SS."""
        total_seconds = int(self.duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @property
    def success_rate(self) -> float:
        """Fraction of attempted applications that succeeded."""
        total_attempts = self.applications_submitted + self.applications_failed
        if total_attempts == 0:
            return 0.0
        return self.applications_submitted / total_attempts

    def summary_line(self) -> str:
        """One-line summary for logging and UI status bar."""
        return (
            f"Discovered: {self.jobs_discovered} | "
            f"Vetted: {self.jobs_vetted} | "
            f"Applied: {self.applications_submitted} | "
            f"Failed: {self.applications_failed} | "
            f"{self.duration_str}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializes statistics to a JSON-serializable dict."""
        return {
            "jobs_discovered":        self.jobs_discovered,
            "jobs_vetted":            self.jobs_vetted,
            "applications_submitted": self.applications_submitted,
            "applications_failed":    self.applications_failed,
            "applications_skipped":   self.applications_skipped,
            "captchas_escalated":     self.captchas_escalated,
            "provider_timeouts":      self.provider_timeouts,
            "duration_seconds":       round(self.duration.total_seconds(), 1),
            "duration_str":           self.duration_str,
            "success_rate":           round(self.success_rate, 4),
            "start_time":             self.start_time.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionStatistics":
        """Restores a SessionStatistics instance from a serialized dict."""
        stats = cls()
        stats.jobs_discovered        = data.get("jobs_discovered", 0)
        stats.jobs_vetted            = data.get("jobs_vetted", 0)
        stats.applications_submitted = data.get("applications_submitted", 0)
        stats.applications_failed    = data.get("applications_failed", 0)
        stats.applications_skipped   = data.get("applications_skipped", 0)
        stats.captchas_escalated     = data.get("captchas_escalated", 0)
        stats.provider_timeouts      = data.get("provider_timeouts", 0)

        raw_start = data.get("start_time")
        if raw_start:
            try:
                parsed = datetime.fromisoformat(raw_start)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                stats.start_time = parsed
            except (ValueError, TypeError):
                pass

        return stats


# ─────────────────────────────────────────────────────────────────────────────
# Worker Status (Execution Observability — Phase 5)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WorkerStatus:
    """Describes the current state of a single worker (provider, engine, etc.).

    Immutable snapshot updated through ExecutionContext methods.
    Each worker must periodically call heartbeat() to prove it is still alive.

    Attributes:
        worker_id: Unique identifier for this worker (e.g. thread name).
        provider_name: Human-readable name of the provider or engine.
        started_at: Monotonic timestamp when the worker was registered.
        last_heartbeat: Most recent heartbeat timestamp (monotonic).
        current_action: Description of what the worker is doing right now.
        status: ``running``, ``waiting``, ``completed``, or ``failed``.
    """
    worker_id: str
    provider_name: str
    started_at: float
    last_heartbeat: float
    current_action: str
    status: Literal["running", "waiting", "completed", "failed"]

    def is_stuck(self, timeout_seconds: float, now: float | None = None) -> bool:
        """Return True if the worker has not sent a heartbeat within the timeout.

        Args:
            timeout_seconds: Maximum allowed silence in seconds.
            now: Optional current time for testing; defaults to ``time.monotonic()``.

        Returns:
            True if ``last_heartbeat`` is older than *timeout_seconds*.
        """
        if now is None:
            now = time.monotonic()
        return (now - self.last_heartbeat) > timeout_seconds


# ─────────────────────────────────────────────────────────────────────────────
# Execution Context
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionContext:
    """The volatile working memory of the agent for a single session.

    Passed to every domain engine and service that needs session awareness.
    Holds the user profile, runtime resources, live session statistics,
    the current work unit being processed, pending application batches,
    and (since Phase 5) an execution map for real‑time observability.

    Args:
        profile: The loaded user profile for this session.
        session_id: Unique identifier for this run (used in logs and DB).
    """

    def __init__(self, profile: UserProfile, session_id: str) -> None:
        # ── Immutable session identity ────────────────────────────────────
        self.profile:     UserProfile = profile
        self.session_id:  str         = session_id

        # ── Runtime resources (set by orchestrator post-construction) ─────
        self.resources: RuntimeProfile | None = None

        # ── State machine reference (set by orchestrator post-construction)
        self.state_machine: Any | None = None

        # ── Live statistics ───────────────────────────────────────────────
        self.stats = SessionStatistics()

        # ── Lock for thread-safe stat updates ────────────────────────────
        self._stats_lock = threading.Lock()

        # ── Current dispatch target ───────────────────────────────────────
        self.current_work_unit: WorkUnit | None = None

        # ── Application batch buffers ─────────────────────────────────────
        self.pending_batches: dict[str, list[Job]] = defaultdict(list)

        # ── Execution observability (Phase 5) ─────────────────────────────
        self._execution_map: dict[str, WorkerStatus] = {}
        self._map_lock = threading.Lock()

        logger.info(
            "ExecutionContext created | session=%s profile=%s",
            session_id,
            getattr(profile, "profile_name", "unknown"),
        )

    # =========================================================================
    # STAT UPDATES (thread-safe)
    # =========================================================================

    def update_stats(self, category: str, count: int = 1) -> None:
        """Increments a session statistic counter. Thread-safe.

        Args:
            category: One of "discovered", "vetted", "applied", "failed",
                "skipped", "captcha_escalated", "provider_timeout".
            count: Amount to add. Defaults to 1.
        """
        with self._stats_lock:
            if category == "discovered":
                self.stats.jobs_discovered += count
            elif category == "vetted":
                self.stats.jobs_vetted += count
            elif category == "applied":
                self.stats.applications_submitted += count
            elif category == "failed":
                self.stats.applications_failed += count
            elif category == "skipped":
                self.stats.applications_skipped += count
            elif category == "captcha_escalated":
                self.stats.captchas_escalated += count
            elif category == "provider_timeout":
                self.stats.provider_timeouts += count
            else:
                logger.warning(
                    "ExecutionContext.update_stats: unknown category '%s'", category
                )

    # =========================================================================
    # CHECKPOINT INTEGRATION
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        """Serializes the context to a JSON-serializable dict for checkpointing."""
        return {
            "session_id":   self.session_id,
            "profile_name": getattr(self.profile, "profile_name", "unknown"),
            "stats":        self.stats.to_dict(),
            "state_name":   self._current_state_name(),
        }

    def restore_from_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        """Restores session progress from a checkpoint dict."""
        stats_data = checkpoint.get("stats", {})
        if stats_data:
            self.stats = SessionStatistics.from_dict(stats_data)
            logger.info(
                "Context restored from checkpoint | "
                "discovered=%d vetted=%d applied=%d",
                self.stats.jobs_discovered,
                self.stats.jobs_vetted,
                self.stats.applications_submitted,
            )

    # =========================================================================
    # CONVENIENCE ACCESSORS
    # =========================================================================

    def get_profile_name(self) -> str:
        """Returns the profile name for logging and reporting."""
        return getattr(self.profile, "profile_name", "unknown")

    def is_low_resource(self) -> bool:
        """Returns True if the session is running in low-resource mode."""
        if self.resources is None:
            return False
        return getattr(self.resources, "is_low_resource", False)

    def elapsed_seconds(self) -> float:
        """Returns the number of seconds since this session started."""
        return self.stats.duration.total_seconds()

    # =========================================================================
    # EXECUTION OBSERVABILITY — Worker Map (Phase 5)
    # =========================================================================

    def register_worker(
        self,
        worker_id: str,
        provider_name: str,
        current_action: str = "starting",
    ) -> None:
        """Register a new worker in the execution map.

        Must be called at the beginning of a worker's life.  If *worker_id*
        already exists, the entry is overwritten with a fresh heartbeat.

        Args:
            worker_id: Unique identifier (e.g. thread name, UUID).
            provider_name: Human-readable provider or engine name.
            current_action: What the worker is doing right now.
        """
        now = time.monotonic()
        with self._map_lock:
            self._execution_map[worker_id] = WorkerStatus(
                worker_id=worker_id,
                provider_name=provider_name,
                started_at=now,
                last_heartbeat=now,
                current_action=current_action,
                status="running",
            )

    def heartbeat(self, worker_id: str, current_action: str | None = None) -> None:
        """Record a heartbeat for a registered worker.

        If *worker_id* is not in the map, the call is silently ignored
        (the worker may have been cleaned up after a timeout).

        Args:
            worker_id: The worker to update.
            current_action: New action description (if omitted, unchanged).
        """
        now = time.monotonic()
        with self._map_lock:
            ws = self._execution_map.get(worker_id)
            if ws is None:
                return
            # Build a new frozen-ish dataclass (copy + update)
            new_action = current_action if current_action is not None else ws.current_action
            self._execution_map[worker_id] = WorkerStatus(
                worker_id=ws.worker_id,
                provider_name=ws.provider_name,
                started_at=ws.started_at,
                last_heartbeat=now,
                current_action=new_action,
                status=ws.status,
            )

    def complete_worker(self, worker_id: str) -> None:
        """Mark a registered worker as successfully completed.

        If *worker_id* is not found, logs a warning and returns.

        Args:
            worker_id: The worker to mark as complete.
        """
        with self._map_lock:
            ws = self._execution_map.get(worker_id)
            if ws is None:
                logger.warning(
                    "complete_worker: worker_id=%r not found in execution map",
                    worker_id,
                )
                return
            self._execution_map[worker_id] = WorkerStatus(
                worker_id=ws.worker_id,
                provider_name=ws.provider_name,
                started_at=ws.started_at,
                last_heartbeat=time.monotonic(),
                current_action=ws.current_action,
                status="completed",
            )

    def get_stuck_workers(self, timeout_seconds: float = 30.0) -> list[WorkerStatus]:
        """Return all registered workers whose heartbeat is older than *timeout_seconds*.

        Only workers with status ``"running"`` or ``"waiting"`` are considered
        (completed/failed workers are not expected to send heartbeats).

        Args:
            timeout_seconds: Maximum allowed silence in seconds.

        Returns:
            A list of WorkerStatus objects for workers that appear stuck.
        """
        now = time.monotonic()
        stuck: list[WorkerStatus] = []
        with self._map_lock:
            for ws in self._execution_map.values():
                if ws.status in ("running", "waiting") and ws.is_stuck(timeout_seconds, now):
                    stuck.append(ws)
        return stuck

    def remove_worker(self, worker_id: str) -> None:
        """Remove a worker from the execution map entirely.

        Typically called after a stuck worker has been handled.

        Args:
            worker_id: The worker to remove.
        """
        with self._map_lock:
            self._execution_map.pop(worker_id, None)

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _current_state_name(self) -> str:
        """Safely extracts the current state name from the StateMachine."""
        if self.state_machine is None:
            return "UNKNOWN"
        current = getattr(self.state_machine, "current_state", None)
        if current is None:
            return "UNKNOWN"
        return getattr(current, "name", str(current))

    def __repr__(self) -> str:
        return (
            f"ExecutionContext("
            f"session={self.session_id}, "
            f"profile={self.get_profile_name()}, "
            f"{self.stats.summary_line()})"
        )
