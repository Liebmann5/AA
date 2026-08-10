"""Background daemon thread that monitors browser health and publishes events.

This module provides BrowserHealthMonitor, which runs in a dedicated daemon
thread and performs periodic liveness checks on the active browser driver.
When the browser becomes unresponsive, it publishes to the EventBus so the
orchestrator can tear down and restart the driver via BrowserCascade.

Threading Model:
    BrowserHealthMonitor is designed to run in a daemon thread, NOT as an
    async coroutine. The entry point is run(), which blocks in a standard
    while loop with time.sleep(). The orchestrator starts it like this:

        thread = threading.Thread(target=monitor.run, daemon=True)
        thread.start()

    Daemon threads are automatically killed when the main process exits,
    so no explicit join or cleanup is required on hard termination.

Communication Contract:
    The monitor communicates exclusively through the EventBus. It NEVER
    calls back into the orchestrator directly. This keeps it fully decoupled:
    the monitor knows about events, not about the orchestrator.

    Events published:
        Event.BROWSER_HEALTHY    — periodic confirmation (every N successful checks)
        Event.BROWSER_DEGRADED   — slow response but still functional
        Event.BROWSER_UNHEALTHY  — consecutive failures hit threshold → triggers restart
        Event.BROWSER_DEAD       — max_failures exceeded → unrecoverable, monitor stops

Health Check Mechanism:
    The check calls driver.is_alive() through a timeout-protected wrapper.
    is_alive() probes the wrapped driver with the lightest possible read
    (title → current_url fallback) — no navigation, no DOM interaction, but
    it does require the browser process to be alive and the session to be valid.

    Response time thresholds (configurable):
        < DEGRADED_THRESHOLD_MS  → HEALTHY
        ≥ DEGRADED_THRESHOLD_MS  → DEGRADED (slow but alive)
        Timeout or exception     → failure; counts toward threshold

Example:
    >>> from auto_apply.adapters.secondary.browser.browser_monitor import BrowserHealthMonitor
    >>> from auto_apply.application.agent.event_bus import EventBus
    >>> import threading
    >>>
    >>> bus = EventBus()
    >>> monitor = BrowserHealthMonitor(driver=resilient_driver, event_bus=bus)
    >>>
    >>> thread = threading.Thread(target=monitor.run, name="BrowserHealthMonitor", daemon=True)
    >>> thread.start()
    >>>
    >>> # Later, from the orchestrator teardown:
    >>> monitor.stop()
"""  # noqa: E501

# Layer: adapters/secondary
# Depends on: domain, application

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, auto

from auto_apply.domain.events import Event
from auto_apply.domain.ports.event_publisher_port import EventPublisherPort
from auto_apply.domain.ports.liveness_port import LivenessPort


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Health Status Enum
# ─────────────────────────────────────────────────────────────────────────────

class BrowserHealth(Enum):
    """Current health status of the monitored browser.

    Attributes:
        HEALTHY: Browser is responding within normal latency bounds.
        DEGRADED: Browser is responding but slowly. May indicate memory
            pressure, a heavy page, or early signs of instability.
        UNRESPONSIVE: Browser has stopped responding to commands. The
            orchestrator should tear down and restart the driver.
        CRASHED: Browser process has terminated entirely.
    """
    HEALTHY      = auto()
    DEGRADED     = auto()
    UNRESPONSIVE = auto()
    CRASHED      = auto()


# ─────────────────────────────────────────────────────────────────────────────
# Health Metrics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HealthMetrics:
    """Accumulated statistics for the browser health monitoring session.

    Attributes:
        total_checks: Total health checks performed since initialization.
        successful_checks: Checks that received a timely response.
        failed_checks: Checks that timed out or raised an exception.
        consecutive_failures: Current unbroken streak of failures.
            Resets to 0 on any successful check.
        last_success_time: UTC datetime of the most recent successful check.
        last_failure_time: UTC datetime of the most recent failed check.
        average_response_ms: Exponential moving average of response time.
            Weighted 80% historical, 20% current to smooth spikes.
    """
    total_checks:          int            = 0
    successful_checks:     int            = 0
    failed_checks:         int            = 0
    consecutive_failures:  int            = 0
    last_success_time:     datetime | None = None
    last_failure_time:     datetime | None = None
    average_response_ms:   float          = 0.0

    def record_success(self, response_ms: float) -> None:
        """Records a successful health check.

        Args:
            response_ms: Elapsed milliseconds for this check to complete.
        """
        self.total_checks += 1
        self.successful_checks += 1
        self.consecutive_failures = 0
        self.last_success_time = datetime.now(timezone.utc)

        # Exponential moving average — smooths occasional latency spikes.
        if self.average_response_ms == 0.0:
            self.average_response_ms = response_ms
        else:
            self.average_response_ms = (
                0.8 * self.average_response_ms + 0.2 * response_ms
            )

    def record_failure(self) -> None:
        """Records a failed health check (timeout or exception)."""
        self.total_checks += 1
        self.failed_checks += 1
        self.consecutive_failures += 1
        self.last_failure_time = datetime.now(timezone.utc)

    @property
    def success_rate(self) -> float:
        """Overall success rate as a float between 0.0 and 1.0.

        Returns 1.0 if no checks have been performed yet (optimistic default).
        """
        if self.total_checks == 0:
            return 1.0
        return self.successful_checks / self.total_checks

    @property
    def time_since_last_success(self) -> timedelta | None:
        """Time elapsed since the last successful check.

        Returns:
            A timedelta, or None if no successful check has occurred.
        """
        if self.last_success_time is None:
            return None
        return datetime.now(timezone.utc) - self.last_success_time

    def to_dict(self) -> dict:
        """Serializes metrics to a dict for event payloads and logging.

        Returns:
            A JSON-serializable dict of all metric values.
        """
        return {
            "total_checks":         self.total_checks,
            "successful_checks":    self.successful_checks,
            "failed_checks":        self.failed_checks,
            "consecutive_failures": self.consecutive_failures,
            "success_rate":         round(self.success_rate, 4),
            "average_response_ms":  round(self.average_response_ms, 1),
            "last_success_time":    (
                self.last_success_time.isoformat()
                if self.last_success_time else None
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Browser Health Monitor
# ─────────────────────────────────────────────────────────────────────────────

class BrowserHealthMonitor:
    """Daemon thread monitor that checks browser liveness and publishes events.

    Runs a blocking check loop on its own thread. Communicates exclusively
    via the EventBus — never touches the orchestrator directly.

    Args:
        driver: The ResilientDriver instance to monitor.
        event_bus: The shared EventBus for publishing health events.
        check_interval_seconds: Time between checks. Default 10s.
            Lower values catch failures faster but add minor overhead.
        failure_threshold: Consecutive failures before BROWSER_UNHEALTHY
            is published. Default 3 (30s at default interval).
        check_timeout_seconds: Seconds to wait for a driver response
            before counting it as a failure. Default 5.
        degraded_threshold_ms: Response time above which the browser is
            considered DEGRADED rather than HEALTHY. Default 1500ms.
        healthy_publish_interval: Publish BROWSER_HEALTHY every N successful
            checks rather than every check, to reduce event bus noise.
            Default 6 (once per minute at 10s interval).
        max_failures: Hard ceiling on consecutive failures. When this count
            is reached the monitor publishes BROWSER_DEAD and stops its
            polling loop entirely. Must be ≥ failure_threshold.
            Default 10.

    Example:
        >>> monitor = BrowserHealthMonitor(driver, event_bus)
        >>> t = threading.Thread(target=monitor.run, daemon=True)
        >>> t.start()
        >>> monitor.stop()  # signals the loop to exit on next iteration
    """

    def __init__(
        self,
        driver: LivenessPort,
        event_bus: EventPublisherPort,
        check_interval_seconds: int   = 10,
        failure_threshold: int        = 3,
        check_timeout_seconds: int    = 5,
        degraded_threshold_ms: float  = 1500.0,
        healthy_publish_interval: int = 6,
        max_failures: int             = 10,
    ) -> None:
        self.driver                  = driver
        self.event_bus               = event_bus
        self.check_interval_seconds  = check_interval_seconds
        self.failure_threshold       = failure_threshold
        self.check_timeout_seconds   = check_timeout_seconds
        self.degraded_threshold_ms   = degraded_threshold_ms
        self.healthy_publish_interval = healthy_publish_interval
        # Hard ceiling: once exceeded, the monitor emits BROWSER_DEAD and
        # exits its polling loop. Must be >= failure_threshold or the
        # recoverable signal would never have a chance to fire first.
        self.max_failures = max(max_failures, failure_threshold)

        # Current assessed health status.
        self.health_status: BrowserHealth = BrowserHealth.HEALTHY
        self.metrics: HealthMetrics = HealthMetrics()

        # Loop control — set False by stop() to exit run() cleanly.
        self._running: bool = False
        self._stop_event = threading.Event()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="BrowserProbe"
        )

        # Internal counter for throttling BROWSER_HEALTHY events.
        self._healthy_publish_counter: int = 0

        # Lock protecting health_status and metrics for thread-safe reads
        # from the orchestrator's main thread (e.g. is_healthy()).
        self._lock = threading.Lock()

        logger.info(
            "BrowserHealthMonitor initialized | interval=%ds threshold=%d "
            "timeout=%ds max_failures=%d",
            check_interval_seconds,
            failure_threshold,
            check_timeout_seconds,
            self.max_failures,
        )

    # =========================================================================
    # THREAD ENTRY POINT
    # =========================================================================

    def run(self) -> None:
        """Blocking loop — the target function for the daemon thread.

        Runs until stop() is called. Performs a health check, sleeps for
        check_interval_seconds, then repeats. All exceptions within a check
        are caught and handled internally; this method never propagates.

        Called by the orchestrator as:
            thread = threading.Thread(target=monitor.run, daemon=True)
            thread.start()
        """
        self._running = True
        logger.info("BrowserHealthMonitor started")

        while self._running:
            try:
                self._perform_check()
            except Exception as exc:
                # Unexpected exception from outside the normal failure path.
                # Record and continue — the monitor must never crash.
                logger.error(
                    "BrowserHealthMonitor: unexpected exception in check loop | %s",
                    exc,
                    exc_info=True,
                )
                with self._lock:
                    self.metrics.record_failure()
                self._evaluate_and_publish()

            # Sleep in short increments so stop() is honored quickly.
            # Instead of one long sleep(10), do ten sleep(1) — the loop
            # checks _running between each second.
            self._interruptible_sleep(self.check_interval_seconds)

        logger.info("BrowserHealthMonitor stopped")

    def stop(self) -> None:
        self._executor.shutdown(wait=False)
        self._running = False
        self._stop_event.set()
        logger.info("BrowserHealthMonitor stop requested")

    # =========================================================================
    # HEALTH QUERY (called from orchestrator main thread)
    # =========================================================================

    def is_healthy(self) -> bool:
        """Returns True if the browser is HEALTHY or DEGRADED (still usable).

        Thread-safe. May be called from the orchestrator's main thread while
        the monitor thread is concurrently running a check.

        Returns:
            True if the browser is currently usable.
        """
        with self._lock:
            return self.health_status in (BrowserHealth.HEALTHY, BrowserHealth.DEGRADED)

    def get_metrics(self) -> HealthMetrics:
        """Returns a copy of the current health metrics.

        Thread-safe snapshot. The returned object is not live — it reflects
        the state at the moment of the call.

        Returns:
            A copy of the HealthMetrics dataclass.
        """
        with self._lock:
            import copy  # noqa: PLC0415
            return copy.copy(self.metrics)

    def reset_after_restart(self) -> None:
        """Resets metrics and health status after a successful driver restart.

        Called by the orchestrator after BrowserCascade successfully provides
        a new driver. Clears the failure history so the new driver starts
        with a clean slate.
        """
        with self._lock:
            self.metrics = HealthMetrics()
            self.health_status = BrowserHealth.HEALTHY
            self._healthy_publish_counter = 0
        logger.info("BrowserHealthMonitor: metrics reset after driver restart")

    # =========================================================================
    # INTERNAL CHECK LOGIC
    # =========================================================================

    def _probe(self) -> bool:
        """Performs the cheap liveness read against the driver.

        Runs on the persistent probe executor's single worker thread. Returns
        the driver's is_alive() result; a falsy return signals a dead session.
        Any driver exception propagates to the caller via future.result().

        ResilientDriver wraps both Selenium and Playwright adapters and does
        not expose ``.title`` directly, so is_alive() performs the cheapest
        possible read on the underlying driver.
        """
        return bool(self.driver.is_alive())

    def _perform_check(self) -> None:
        """Executes a single liveness check via the persistent probe executor.

        The probe runs on a reused single-worker ThreadPoolExecutor purely so
        future.result(timeout=...) can bound a hung ChromeDriver call without
        leaking a fresh thread per check — the executor does NOT, by itself,
        affect urllib3 connection pooling.

        Concurrency, not pooling, is what produced the recurring
        "Connection pool is full, discarding connection: localhost" warnings:
        the probe shares one Selenium driver (and its maxsize=1 urllib3 pool)
        with the main agent loop, and a probe overlapping an in-flight command
        (e.g. a SERP scroll) checks out a second connection that is discarded
        on return. To prevent that, the monitor first takes the driver's
        command lock non-blockingly. If a command is in flight the acquire
        fails and this cycle is skipped entirely — a busy driver is, by
        definition, alive, so metrics and events are left untouched. When the
        driver exposes no such lock (e.g. a bare mock), the check proceeds
        unguarded as before.
        """
        acquire = getattr(self.driver, "try_acquire_command_lock", None)
        release = getattr(self.driver, "release_command_lock", None)
        if callable(acquire) and not acquire():
            logger.debug(
                "BrowserHealthMonitor: driver busy with another command — "
                "skipping this check cycle"
            )
            return
        lock_held = callable(acquire)

        try:
            start = time.monotonic()
            # future = self._executor.submit(self._probe)
            # ADD THIS SAFETY CHECK:
            if not self._running:
                return

            try:
                future = self._executor.submit(self._probe)
                alive = future.result(timeout=self.check_timeout_seconds)
                elapsed_ms = (time.monotonic() - start) * 1000.0
            except RuntimeError:
                # Catch the "cannot schedule new futures after shutdown" error cleanly
                return
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "BrowserHealthMonitor: check timed out after %ds",
                    self.check_timeout_seconds,
                )
                with self._lock:
                    self.metrics.record_failure()
                self._evaluate_and_publish()
                return
            except Exception as exc:
                logger.warning("BrowserHealthMonitor: check raised exception | %s", exc)
                with self._lock:
                    self.metrics.record_failure()
                self._evaluate_and_publish()
                return

            if not alive:
                logger.warning("BrowserHealthMonitor: is_alive() returned False")
                with self._lock:
                    self.metrics.record_failure()
                self._evaluate_and_publish()
                return

            # Success path — preserve existing status assessment and publishing.
            with self._lock:
                self.metrics.record_success(elapsed_ms)
                self.metrics.consecutive_failures = 0

                if elapsed_ms >= self.degraded_threshold_ms:
                    new_status = BrowserHealth.DEGRADED
                else:
                    new_status = BrowserHealth.HEALTHY

                self.health_status = new_status

            logger.debug(
                "BrowserHealthMonitor: check passed | elapsed_ms=%.0f status=%s",
                elapsed_ms,
                new_status.name,
            )

            # Publish DEGRADED event every time status becomes or stays degraded.
            if new_status == BrowserHealth.DEGRADED:
                self.event_bus.publish(Event.BROWSER_DEGRADED, {
                    "response_ms":        round(elapsed_ms, 1),
                    "threshold_ms":       self.degraded_threshold_ms,
                    "average_response_ms": round(self.metrics.average_response_ms, 1),
                })

            # Publish BROWSER_HEALTHY at the configured interval to reduce noise.
            elif new_status == BrowserHealth.HEALTHY:
                self._healthy_publish_counter += 1
                if self._healthy_publish_counter >= self.healthy_publish_interval:
                    self._healthy_publish_counter = 0
                    self.event_bus.publish(Event.BROWSER_HEALTHY, {
                        "response_ms":         round(elapsed_ms, 1),
                        "consecutive_successes": self.metrics.successful_checks,
                    })
        finally:
            if lock_held and callable(release):
                release()

    def _evaluate_and_publish(self) -> None:
        """Evaluates failure state and publishes the appropriate event.

        Called after every failed check. Determines whether the failure
        count has crossed the threshold for BROWSER_UNHEALTHY, or the
        hard ceiling for BROWSER_DEAD (terminal — stops the polling loop).
        """
        with self._lock:
            consecutive = self.metrics.consecutive_failures
            metrics_snapshot = self.metrics.to_dict()

        # ── Hard ceiling: terminal, unrecoverable browser state ───────────
        if consecutive >= self.max_failures:
            with self._lock:
                self.health_status = BrowserHealth.CRASHED

            logger.error(
                "BrowserHealthMonitor: BROWSER_DEAD | consecutive_failures=%d "
                "max_failures=%d — stopping monitor",
                consecutive,
                self.max_failures,
            )
            # Stop the polling loop before publishing so the daemon thread
            # terminates promptly regardless of how subscribers react. Wake the
            # interruptible sleep immediately rather than waiting the interval.
            self._running = False
            self._stop_event.set()
            self.event_bus.publish(Event.BROWSER_DEAD, {
                "consecutive_failures": consecutive,
                "max_failures":         self.max_failures,
                "metrics":              metrics_snapshot,
            })
            return

        if consecutive >= self.failure_threshold:
            with self._lock:
                self.health_status = BrowserHealth.UNRESPONSIVE

            logger.error(
                "BrowserHealthMonitor: BROWSER_UNHEALTHY | consecutive_failures=%d",
                consecutive,
            )
            self.event_bus.publish(Event.BROWSER_UNHEALTHY, {
                "consecutive_failures": consecutive,
                "metrics":              metrics_snapshot,
                "last_error":           "timeout or exception during health check",
            })

        elif consecutive >= 2:
            with self._lock:
                self.health_status = BrowserHealth.DEGRADED

            logger.warning(
                "BrowserHealthMonitor: BROWSER_DEGRADED | consecutive_failures=%d",
                consecutive,
            )
            self.event_bus.publish(Event.BROWSER_DEGRADED, {
                "consecutive_failures": consecutive,
                "metrics":              metrics_snapshot,
            })

    def _interruptible_sleep(self, total_seconds: int) -> None:
        """Sleep for up to total_seconds, waking immediately if stop() is called."""
        self._stop_event.wait(timeout=total_seconds)
        self._stop_event.clear()