"""Session state persistence for crash recovery and resumption.

This module provides CheckpointManager, which saves volatile session state
to disk at regular intervals so execution can resume after a crash, power
failure, or unexpected process termination.

What Gets Checkpointed vs. What Stays in the Database:
    The database (DatabaseManager) owns persistent facts: the work queue,
    job records, application history. These survive crashes automatically
    because the DB uses WAL (Write-Ahead Logging).

    The CheckpointManager owns volatile runtime state that the database
    does not know about: session statistics, current execution context,
    and any in-memory information that would be lost on a crash. Together
    they provide complete recovery.

Atomic Write Guarantee:
    All checkpoint saves use a write-to-temp + atomic-rename pattern.
    If the process crashes mid-write, the previous checkpoint is intact.
    The temp file is either complete or absent — never partial.

Threading Model:
    All methods are synchronous. This is intentional — the orchestrator
    runs on a single thread and calls record_action_and_maybe_save() after
    each completed task. There is no async I/O and no background thread
    needed. The write is fast (small JSON file) and acceptable in the
    main loop without blocking for meaningful durations.

Example:
    >>> manager = CheckpointManager(
    ...     storage_path=Path("/home/user/.auto_apply/checkpoints"),
    ...     checkpoint_interval=5,
    ... )
    >>>
    >>> # Call this after every task completes in the orchestrator loop.
    >>> manager.record_action_and_maybe_save(context)
    >>>
    >>> # On next startup, before run():
    >>> checkpoint = manager.load_latest(session_id="session_12345")
    >>> if checkpoint:
    ...     context.restore_from_checkpoint(checkpoint)
"""

# Layer: application
# Depends on: domain

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CheckpointMetadata:
    """Summary of a checkpoint's identity and age. Used for recovery decisions.

    Attributes:
        checkpoint_id: Unique ID for this specific save.
        timestamp: UTC datetime when the checkpoint was written.
        session_id: The session this checkpoint belongs to.
        action_count: Number of orchestrator actions completed at save time.
        state_name: The AgentState name at save time (e.g. "RUNNING").
        file_size_bytes: Size of the checkpoint file on disk.
    """
    checkpoint_id: str
    timestamp: datetime
    session_id: str
    action_count: int
    state_name: str
    file_size_bytes: int

    @property
    def age(self) -> timedelta:
        """Elapsed time since this checkpoint was written.

        Returns:
            A timedelta representing how old this checkpoint is.
        """
        return datetime.now(timezone.utc) - self.timestamp

    def is_stale(self, max_age_hours: int = 24) -> bool:
        """Returns True if this checkpoint is older than max_age_hours.

        Stale checkpoints are still loaded — it is the caller's responsibility
        to decide whether to use them. This flag is informational.

        Args:
            max_age_hours: The threshold in hours. Default is 24.

        Returns:
            True if the checkpoint is older than the threshold.
        """
        return self.age > timedelta(hours=max_age_hours)


class CheckpointManager:
    """Saves and restores volatile session state for crash recovery.

    Writes a JSON checkpoint file to disk after every N completed orchestrator
    actions. On session startup, SessionController calls load_latest() to
    check for a recoverable checkpoint and restores state if one is found.

    The checkpoint file is small (< 10KB typically) and the write is atomic,
    so calling this on the main orchestrator thread is safe and fast.

    Args:
        storage_path: Directory where checkpoint files are stored. Created
            automatically if it does not exist.
        checkpoint_interval: Number of completed actions between saves.
            Default is 5. Lower values increase recovery granularity at
            the cost of more frequent disk writes.
        max_checkpoints: Maximum number of checkpoint files to keep on disk.
            Older files beyond this count are automatically deleted.

    Attributes:
        _action_counter: Actions completed since the last save.
        _last_save_time: UTC datetime of the most recent successful save.

    Example:
        >>> manager = CheckpointManager(Path("~/.auto_apply/checkpoints"))
        >>> manager.record_action_and_maybe_save(context)  # Called per task
        >>> checkpoint = manager.load_latest("session_abc")
    """

    # Filename prefix for checkpoint files. Pattern: checkpoint_<session_id>.json
    _FILE_PREFIX = "checkpoint_"
    _FILE_SUFFIX = ".json"
    _TEMP_FILE_NAME = "checkpoint.tmp"

    def __init__(
        self,
        storage_path: Path,
        checkpoint_interval: int = 5,
        max_checkpoints: int = 3,
    ) -> None:
        """Initializes the checkpoint manager and ensures the storage directory exists.

        Args:
            storage_path: Directory for checkpoint files. May be a string path;
                will be converted to Path automatically.
            checkpoint_interval: Completed actions between auto-saves.
            max_checkpoints: Maximum files retained. Oldest are deleted first.
        """
        self.storage_path = Path(storage_path)
        self.checkpoint_interval = checkpoint_interval
        self.max_checkpoints = max_checkpoints

        self._action_counter: int = 0
        self._last_save_time: datetime | None = None

        # Ensure directory exists. parents=True handles nested paths.
        # exist_ok=True is safe on concurrent startup (rare but possible).
        self.storage_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            "CheckpointManager ready | path=%s interval=%d",
            self.storage_path,
            self.checkpoint_interval,
        )

    # =========================================================================
    # PRIMARY INTERFACE — called by AgentOrchestrator
    # =========================================================================

    def record_action_and_maybe_save(self, context: Any) -> None:
        """Increments the action counter and saves a checkpoint if the interval is met.

        This is the method the orchestrator calls after every successfully
        completed task. It is intentionally lightweight: it increments a
        counter and only performs disk I/O when the threshold is reached.

        Args:
            context: The ExecutionContext for the current session. Used to
                extract stats and state for serialization.

        Example:
            >>> # At the end of each successful loop iteration in orchestrator:
            >>> checkpoint_manager.record_action_and_maybe_save(self.context)
        """
        self._action_counter += 1

        if self._action_counter >= self.checkpoint_interval:
            logger.debug(
                "Checkpoint interval reached | actions=%d — saving",
                self._action_counter,
            )
            self.save(context)
            self._action_counter = 0

    def save(self, context: Any) -> bool:
        """Saves a checkpoint of the current session state.

        Serializes the execution context to JSON and writes it atomically
        using a temp-file + rename pattern. If the write fails for any
        reason, the previous checkpoint is preserved and the error is logged.

        Args:
            context: The ExecutionContext to serialize.

        Returns:
            True if the checkpoint was saved successfully, False on error.

        Example:
            >>> success = manager.save(context)
        """
        try:
            checkpoint_data = self._serialize_context(context)

            temp_path = self.storage_path / self._TEMP_FILE_NAME
            final_path = self._checkpoint_path(context.session_id)

            # Write to temp file first.
            temp_path.write_text(
                json.dumps(checkpoint_data, indent=2, default=str),
                encoding="utf-8",
            )

            # Atomic rename: either the full file appears or the old one remains.
            # os.replace() is atomic on POSIX; on Windows it is best-effort
            # but still far safer than a direct overwrite.
            os.replace(temp_path, final_path)

            self._last_save_time = datetime.now(timezone.utc)

            logger.info(
                "Checkpoint saved | session=%s file=%s",
                context.session_id,
                final_path.name,
            )

            self._prune_old_checkpoints()
            return True

        except Exception as exc:
            logger.error(
                "Checkpoint save failed | error=%s",
                exc,
                exc_info=True,
            )
            return False

    def save_final(self, context: Any) -> None:
        """Saves a final checkpoint on clean session exit.

        Called by AgentOrchestrator._teardown() regardless of whether the
        checkpoint interval was met. Ensures the session report is always
        complete even if the session ended mid-interval.

        This method swallows exceptions intentionally — a failure here
        should never prevent the session from shutting down cleanly.

        Args:
            context: The ExecutionContext at session end.
        """
        try:
            self.save(context)
            logger.info("Final checkpoint saved | session=%s", context.session_id)
        except Exception as exc:
            logger.warning(
                "Final checkpoint save failed (non-fatal) | error=%s", exc
            )

    # =========================================================================
    # RECOVERY — called by AgentOrchestrator._attempt_checkpoint_recovery()
    # =========================================================================

    def load(self) -> dict | None:
        """Loads the most recent checkpoint, regardless of session.

        Convenience wrapper used by ``AgentOrchestrator._attempt_checkpoint_recovery``
        on startup, when the prior session's ID may not be known. Delegates to
        ``load_latest()`` with no session filter, so files from any session are
        considered. Returns ``None`` if no checkpoint file exists or the file
        cannot be parsed — never raises.

        Returns:
            The checkpoint data dict (same shape as written by ``save()``), or
            ``None`` when nothing is available.
        """
        return self.load_latest(session_id=None)

    def load_latest(self, session_id: str | None = None) -> dict | None:
        """Loads the most recent checkpoint, optionally filtered by session ID.

        If session_id is provided, looks for exactly that session's checkpoint.
        If None, loads the most recently modified checkpoint file regardless
        of session (useful when session IDs differ between runs).

        Args:
            session_id: The session ID to look for, or None for most recent.

        Returns:
            The checkpoint data dict, or None if no checkpoint exists or
            loading fails.

        Example:
            >>> checkpoint = manager.load_latest("session_1234567890")
            >>> if checkpoint:
            ...     stats = checkpoint["context"]["stats"]
        """
        try:
            target_file = self._find_checkpoint_file(session_id)

            if target_file is None:
                logger.info("No checkpoint found | session=%s", session_id or "any")
                return None

            data = json.loads(target_file.read_text(encoding="utf-8"))

            # Parse and log the checkpoint age as a courtesy warning.
            raw_ts = data.get("metadata", {}).get("timestamp")
            if raw_ts:
                timestamp = datetime.fromisoformat(raw_ts)
                # Make timezone-aware if naive.
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age_minutes = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60  # noqa: E501
                if age_minutes > 60 * 24:
                    logger.warning(
                        "Checkpoint is %.0f hours old — data may be stale",
                        age_minutes / 60,
                    )
                else:
                    logger.info(
                        "Checkpoint loaded | age=%.0f minutes file=%s",
                        age_minutes,
                        target_file.name,
                    )

            return data

        except Exception as exc:
            logger.error(
                "Checkpoint load failed | error=%s",
                exc,
                exc_info=True,
            )
            return None

    def get_metadata(
        self, session_id: str | None = None
    ) -> CheckpointMetadata | None:
        """Returns metadata about a checkpoint without loading the full payload.

        Useful for SessionController to check whether a usable checkpoint
        exists before deciding whether to offer recovery to the user.

        Args:
            session_id: The session ID to inspect, or None for most recent.

        Returns:
            A CheckpointMetadata object, or None if no checkpoint is found.

        Example:
            >>> meta = manager.get_metadata()
            >>> if meta and not meta.is_stale():
            ...     offer_recovery_prompt()
        """
        try:
            target_file = self._find_checkpoint_file(session_id)
            if target_file is None:
                return None

            data = json.loads(target_file.read_text(encoding="utf-8"))
            meta = data.get("metadata", {})
            stat = target_file.stat()

            raw_ts = meta.get("timestamp", datetime.now(timezone.utc).isoformat())
            timestamp = datetime.fromisoformat(raw_ts)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            return CheckpointMetadata(
                checkpoint_id=meta.get("checkpoint_id", "unknown"),
                timestamp=timestamp,
                session_id=meta.get("session_id", "unknown"),
                action_count=meta.get("action_count", 0),
                state_name=meta.get("state_name", "UNKNOWN"),
                file_size_bytes=stat.st_size,
            )

        except Exception as exc:
            logger.error("get_metadata failed | error=%s", exc)
            return None

    def delete(self, session_id: str) -> bool:
        """Deletes a specific session's checkpoint file.

        Called when the user explicitly declines recovery, or after a
        session completes successfully and recovery is no longer needed.

        Args:
            session_id: The session whose checkpoint should be deleted.

        Returns:
            True if the file was deleted or did not exist, False on error.

        Example:
            >>> manager.delete("session_1234567890")
        """
        try:
            path = self._checkpoint_path(session_id)
            if path.exists():
                path.unlink()
                logger.info("Checkpoint deleted | session=%s", session_id)
            return True
        except Exception as exc:
            logger.error("Checkpoint delete failed | error=%s", exc)
            return False

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def _serialize_context(self, context: Any) -> dict:
        """Builds the checkpoint payload dict from an ExecutionContext.

        Captures only what is needed to restore a session: statistics,
        session identity, and pending batch state. Does NOT capture browser
        cookies or raw driver state — those are not reliably portable.

        Args:
            context: The ExecutionContext to serialize.

        Returns:
            A JSON-serializable dict representing the checkpoint.
        """
        # Safely extract stats — gracefully handles any missing attributes
        # so a partial ExecutionContext doesn't prevent saving.
        stats = getattr(context, "stats", None)

        return {
            "metadata": {
                "checkpoint_id": f"ckpt_{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": getattr(context, "session_id", "unknown"),
                "action_count": self._action_counter,
                # State name from the state machine if available.
                "state_name": self._extract_state_name(context),
            },
            "context": {
                "session_id": getattr(context, "session_id", "unknown"),
                "profile_name": self._extract_profile_name(context),
                "stats": {
                    "jobs_discovered": getattr(stats, "jobs_discovered", 0),
                    "jobs_vetted": getattr(stats, "jobs_vetted", 0),
                    "applications_submitted": getattr(stats, "applications_submitted", 0),  # noqa: E501
                    "applications_failed": getattr(stats, "applications_failed", 0),
                },
            },
            # Pending batch buffers: serialized so partially-collected company
            # buckets survive a crash and don't lose buffered jobs.
            "buffers": {
                "pending_batches": {
                    company: [self._serialize_job(job) for job in jobs]
                    for company, jobs in getattr(context, "pending_batches", {}).items()
                },
            },
        }

    @staticmethod
    def _serialize_job(job: Any) -> dict:
        """Serializes a Job to its minimal checkpoint representation.

        Only the fields needed to reconstruct a WorkUnit on recovery are
        saved. Full job objects are not serialized — they will be re-fetched
        or re-queued from the database on recovery.

        Args:
            job: A Job model object.

        Returns:
            A minimal dict with the job's identity fields.
        """
        return {
            "job_id":  getattr(job, "job_id",  None),
            "url":     getattr(job, "url",     None),
            "title":   getattr(job, "title",   None),
            "company": getattr(job, "company", None),
        }

    @staticmethod
    def _extract_state_name(context: Any) -> str:
        """Safely extracts the current state name from the context.

        Args:
            context: The ExecutionContext.

        Returns:
            The state name string, or "UNKNOWN" if not available.
        """
        state_machine = getattr(context, "state_machine", None)
        if state_machine is not None:
            current = getattr(state_machine, "current_state", None)
            if current is not None:
                return getattr(current, "name", str(current))
        return "UNKNOWN"

    @staticmethod
    def _extract_profile_name(context: Any) -> str:
        """Safely extracts the profile name from the context.

        Args:
            context: The ExecutionContext.

        Returns:
            The profile name string, or "unknown" if not available.
        """
        profile = getattr(context, "profile", None)
        if profile is not None:
            return getattr(profile, "profile_name", "unknown")
        return "unknown"

    # =========================================================================
    # FILE MANAGEMENT
    # =========================================================================

    def _checkpoint_path(self, session_id: str) -> Path:
        """Returns the expected file path for a session's checkpoint.

        Args:
            session_id: The session identifier.

        Returns:
            A Path object for the checkpoint file.
        """
        return self.storage_path / f"{self._FILE_PREFIX}{session_id}{self._FILE_SUFFIX}"

    def _find_checkpoint_file(self, session_id: str | None) -> Path | None:
        """Finds the checkpoint file to load.

        If session_id is provided, looks for that specific file.
        If None, returns the most recently modified checkpoint file.

        Args:
            session_id: Target session ID, or None for most recent.

        Returns:
            A Path to the checkpoint file, or None if not found.
        """
        if session_id is not None:
            path = self._checkpoint_path(session_id)
            return path if path.exists() else None

        # Find most recently modified checkpoint file.
        candidates = sorted(
            self.storage_path.glob(f"{self._FILE_PREFIX}*{self._FILE_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _prune_old_checkpoints(self) -> None:
        """Deletes checkpoint files beyond the max_checkpoints retention limit.

        Keeps the N most recently modified files and deletes the rest.
        Errors during pruning are logged but never raised — a failed prune
        is not a reason to fail a checkpoint save.
        """
        try:
            all_files = sorted(
                self.storage_path.glob(f"{self._FILE_PREFIX}*{self._FILE_SUFFIX}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            # Slice off the files we want to keep; delete the remainder.
            for old_file in all_files[self.max_checkpoints:]:
                old_file.unlink()
                logger.debug("Pruned old checkpoint | file=%s", old_file.name)

        except Exception as exc:
            logger.warning("Checkpoint pruning failed (non-fatal) | error=%s", exc)