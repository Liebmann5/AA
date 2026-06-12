"""Provider Watchdog — monitors worker heartbeats and recovers stuck threads.

This module provides ``ProviderWatchdog``, which runs in a background daemon
thread and periodically checks the ``ExecutionContext`` execution map for
workers that have failed to send a heartbeat within the configured timeout.

When a stuck worker is detected, the watchdog:
    1. Logs an error identifying the worker and its last action.
    2. Publishes an ``Event.PROVIDER_TIMED_OUT`` event on the shared EventBus.
    3. Removes the worker from the execution map (it is considered dead).

The orchestrator can subscribe to ``PROVIDER_TIMED_OUT`` and take appropriate
recovery actions (e.g. re‑queuing the task, restarting the provider).

Thread Safety:
    All interactions with ``ExecutionContext`` go through its documented
    thread-safe methods. The watchdog holds no locks beyond what the context
    already provides.

Example:
    >>> from auto_apply.application.agent.watchdog import ProviderWatchdog
    >>> watchdog = ProviderWatchdog(context=ctx, event_bus=bus)
    >>> watchdog.start()
    >>> # ... session runs ...
    >>> watchdog.stop()
"""

import logging
import threading
import time

from auto_apply.application.agent.context import ExecutionContext, WorkerStatus
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.domain.events import Event

logger = logging.getLogger(__name__)


class ProviderWatchdog:
    """Daemon-thread watchdog that recovers silently stuck provider threads.

    Runs an independent polling loop: every 10 seconds it queries the
    execution context for workers that haven't sent a heartbeat within
    *timeout_seconds* (default 30 s) and treats them as stuck.

    Args:
        context: The shared ``ExecutionContext`` for this session.
        event_bus: The session-level ``EventBus`` for publishing events.
        poll_interval: Seconds between checks.  Defaults to 10.
        stuck_timeout: Maximum seconds without a heartbeat before a
            worker is considered stuck.  Defaults to 30.
    """

    def __init__(
        self,
        context: ExecutionContext,
        event_bus: EventBus,
        poll_interval: float = 10.0,
        stuck_timeout: float = 30.0,
    ) -> None:
        self._context = context
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._stuck_timeout = stuck_timeout

        self._running: bool = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        logger.info(
            "ProviderWatchdog initialized | interval=%.1fs timeout=%.1fs",
            poll_interval,
            stuck_timeout,
        )

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def start(self) -> None:
        """Spawn the watchdog daemon thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ProviderWatchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info("ProviderWatchdog started")

    def stop(self) -> None:
        """Signal the daemon loop to exit and join the thread."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning(
                    "ProviderWatchdog thread did not exit within 5s — "
                    "it will be killed when the process exits"
                )

        logger.info("ProviderWatchdog stopped")

    # =========================================================================
    # INTERNAL LOOP
    # =========================================================================

    def _run_loop(self) -> None:
        """Blocking daemon loop — the target for ``threading.Thread``.

        Exits when ``self._running`` becomes ``False`` or the stop event
        is set.
        """
        while self._running:
            try:
                stuck = self._context.get_stuck_workers(self._stuck_timeout)
                for worker in stuck:
                    self._handle_stuck_worker(worker)
            except Exception as exc:
                logger.error(
                    "ProviderWatchdog: unhandled exception in check loop | %s",
                    exc,
                    exc_info=True,
                )

            # Sleep in small increments so stop() is honoured promptly.
            self._stop_event.wait(timeout=self._poll_interval)
            self._stop_event.clear()

    def _handle_stuck_worker(self, worker: WorkerStatus) -> None:
        """Log, publish event, and remove the stuck worker.

        Args:
            worker: The ``WorkerStatus`` for the stuck worker.
        """
        logger.error(
            "ProviderWatchdog: worker stuck | id=%s provider=%s action=%s",
            worker.worker_id,
            worker.provider_name,
            worker.current_action,
        )

        try:
            self._event_bus.publish(
                Event.PROVIDER_TIMED_OUT,
                {
                    "worker_id": worker.worker_id,
                    "provider_name": worker.provider_name,
                    "last_action": worker.current_action,
                },
            )
        except Exception as exc:
            logger.warning(
                "ProviderWatchdog: could not publish PROVIDER_TIMED_OUT | %s", exc
            )

        # Remove from the map so the orchestrator knows it is no longer alive.
        self._context.remove_worker(worker.worker_id)

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"ProviderWatchdog("
            f"running={self._running}, "
            f"interval={self._poll_interval:.1f}s, "
            f"timeout={self._stuck_timeout:.1f}s)"
        )