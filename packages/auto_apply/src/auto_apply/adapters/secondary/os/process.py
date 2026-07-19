"""Provides a fail-safe registry for managing child processes.

This module tracks processes created by the application (Browsers, Subprocesses).
It ensures safety by verifying Process IDs (PID) AND Creation Timestamps
to prevent accidental termination of unrelated system processes (PID Reuse)
in the event of a crash.
"""

import json
import logging
from typing import Any

import psutil

from auto_apply.domain.config import USER_DATA_DIR

logger = logging.getLogger(__name__)

REGISTRY_FILE = USER_DATA_DIR / "active_processes.json"

class ProcessManager:
    """A singleton registry to track and clean up child processes."""

    @staticmethod
    def register(process_id: int) -> None:
        """Registers a process for safe cleanup.

        Args:
            process_id (int): The PID of the process to track.
        """
        try:
            if not psutil.pid_exists(process_id):
                return

            proc = psutil.Process(process_id)
            create_time = proc.create_time()

            # Load existing registry
            data = ProcessManager._load()

            # Add new entry: Tuple of (PID, Timestamp)
            entry = {
                "pid": process_id,
                "time": create_time,
                "name": proc.name()
            }
            data.append(entry)

            ProcessManager._save(data)
            logger.debug(f"Registered process: {entry['name']} (PID: {process_id})")

        except Exception as e:
            logger.warning(f"Failed to register process {process_id}: {e}")

    @staticmethod
    def cleanup_all() -> None:
        """Terminates all registered processes that are still running.

        This should be called during application shutdown.
        """
        if not REGISTRY_FILE.exists():
            return

        data = ProcessManager._load()
        remaining_data = []

        for entry in data:
            pid = entry.get("pid")
            saved_time = entry.get("time")
            name = entry.get("name", "Unknown")

            try:
                if not psutil.pid_exists(pid):
                    continue # Already gone

                proc = psutil.Process(pid)

                # --- THE SAFETY CHECK ---
                # If create_time differs, the PID was recycled by the OS.
                # Do NOT kill it.
                if abs(proc.create_time() - saved_time) > 1.0:
                    logger.warning(f"PID {pid} reused by '{proc.name()}'. Skipping safety kill.")  # noqa: E501
                    continue

                # If matches, kill it
                logger.info(f"Cleaning up orphan process: {name} (PID: {pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except psutil.TimeoutExpired:
                    proc.kill()

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as e:
                logger.error(f"Error cleaning PID {pid}: {e}")
                remaining_data.append(entry)

        # Update file (clear cleaned entries)
        if remaining_data:
            ProcessManager._save(remaining_data)
        elif REGISTRY_FILE.exists():
            REGISTRY_FILE.unlink()

    @staticmethod
    def _load() -> list[dict[str, Any]]:
        try:
            if REGISTRY_FILE.exists():
                with open(REGISTRY_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    @staticmethod
    def _save(data: list[dict[str, Any]]) -> None:
        try:
            REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(REGISTRY_FILE, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass