"""Background daemon thread that monitors network connectivity and publishes events.

This module provides NetworkHealthMonitor, which runs in a dedicated daemon
thread and performs periodic connectivity checks using only the Python standard
library. When the network goes down, it publishes NETWORK_UNHEALTHY so the
orchestrator can pause. When it comes back, it publishes NETWORK_RESTORED so
execution resumes automatically.

Zero External Dependencies:
    The original implementation used aiohttp. This version uses only
    urllib.request and socket — both part of Python's standard library.
    This is deliberate: network monitoring must work on the absolute
    worst-case hardware and environment, including machines with no pip
    access or with restricted outbound ports beyond 80/443.

Threading Model:
    Identical to BrowserHealthMonitor — run() is a blocking loop called
    from a daemon thread. stop() sets a flag to exit on the next iteration.
    The orchestrator subscribes to NETWORK_UNHEALTHY / NETWORK_RESTORED
    and pauses/resumes execution accordingly.

Connectivity Check Strategy:
    Each check attempts an HTTP HEAD request (not GET — no body downloaded)
    to a list of reliable external endpoints. A single success from any
    endpoint within the timeout window counts as "connected."

    Primary endpoints:
        1.1.1.1:80     — Cloudflare DNS (TCP only, no DNS lookup needed)
        8.8.8.8:80     — Google DNS (TCP only, fallback)
        connectivitycheck.gstatic.com — Google's dedicated check URL

    The TCP socket check to 1.1.1.1:80 is the fastest and most reliable —
    it doesn't perform a DNS lookup, doesn't download anything, and is
    blocked by virtually no firewalls since port 80 is universally allowed.

Downtime Tracking:
    The monitor tracks when connectivity was lost so it can include
    downtime_seconds in the NETWORK_RESTORED payload. This data is useful
    for session reports and future research telemetry.

Example:
    >>> from auto_apply.adapters.secondary.network.network_monitor import NetworkHealthMonitor
    >>> from auto_apply.application.agent.event_bus import EventBus
    >>> import threading
    >>>
    >>> bus = EventBus()
    >>> monitor = NetworkHealthMonitor(event_bus=bus)
    >>>
    >>> thread = threading.Thread(target=monitor.run, name="NetworkHealthMonitor", daemon=True)
    >>> thread.start()
    >>>
    >>> monitor.is_connected()
    True
    >>>
    >>> monitor.stop()
"""  # noqa: E501

# Layer: adapters/secondary
# Depends on: domain, application

import logging
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone

from auto_apply.domain.events import Event

if False:  # TYPE_CHECKING guard — avoids circular import at runtime
    from auto_apply.application.agent.event_bus import EventBus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Default check endpoints (TCP socket checks — no DNS, no download)
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULT_TCP_ENDPOINTS: list[tuple[str, int]] = [
    ("1.1.1.1",   80),   # Cloudflare DNS
    ("8.8.8.8",   80),   # Google DNS
    ("9.9.9.9",   80),   # Quad9 DNS
]

# HTTP HEAD fallback used if all TCP checks fail.
# HEAD downloads no body — just verifies the endpoint is reachable.
_DEFAULT_HTTP_URL = "http://connectivitycheck.gstatic.com/generate_204"


class NetworkHealthMonitor:
    """Daemon thread monitor for network connectivity.

    Performs lightweight TCP socket checks at regular intervals. Publishes
    NETWORK_UNHEALTHY when connectivity is lost and NETWORK_RESTORED when
    it comes back. Communicates exclusively through the EventBus.

    Args:
        event_bus: The shared EventBus. Receives NETWORK_UNHEALTHY and
            NETWORK_RESTORED events published by this monitor.
        check_interval_seconds: Seconds between connectivity probes.
            Default 30. Lower values detect outages faster but add minor
            overhead.
        failure_threshold: Consecutive failed checks before NETWORK_UNHEALTHY
            is published. Default 2. At 30s interval this means a network
            outage is declared after 60 seconds of silence.
        check_timeout_seconds: Seconds to wait for each TCP connection
            attempt. Default 5. Keep this lower than check_interval.
        tcp_endpoints: Override the default list of (host, port) pairs to
            probe. Must provide at least one entry.
        http_fallback_url: URL used for HTTP HEAD fallback if all TCP checks
            fail. Defaults to Google's connectivity check endpoint.

    Attributes:
        _connected: Current connectivity state. Thread-safe via _lock.
        _consecutive_failures: Unbroken failure streak.
        _outage_start: UTC datetime when the current outage began, or None.

    Example:
        >>> monitor = NetworkHealthMonitor(event_bus)
        >>> t = threading.Thread(target=monitor.run, daemon=True)
        >>> t.start()
        >>> monitor.is_connected()
        True
    """

    def __init__(
        self,
        event_bus: "EventBus",
        check_interval_seconds: int    = 30,
        failure_threshold: int         = 2,
        check_timeout_seconds: int     = 5,
        tcp_endpoints: list[tuple[str, int]] | None = None,
        http_fallback_url: str         = _DEFAULT_HTTP_URL,
    ) -> None:
        self.event_bus              = event_bus
        self.check_interval_seconds = check_interval_seconds
        self.failure_threshold      = failure_threshold
        self.check_timeout_seconds  = check_timeout_seconds
        self.tcp_endpoints          = tcp_endpoints or _DEFAULT_TCP_ENDPOINTS
        self.http_fallback_url      = http_fallback_url

        # State — protected by _lock for thread-safe reads from main thread.
        self._connected: bool             = True
        self._consecutive_failures: int   = 0
        self._total_checks: int           = 0
        self._total_failures: int         = 0
        self._outage_start: datetime | None = None

        self._running: bool = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        logger.info(
            "NetworkHealthMonitor initialized | interval=%ds threshold=%d timeout=%ds",
            check_interval_seconds,
            failure_threshold,
            check_timeout_seconds,
        )

    # =========================================================================
    # THREAD ENTRY POINT
    # =========================================================================

    def run(self) -> None:
        """Blocking loop — the target function for the daemon thread.

        Performs connectivity checks at check_interval_seconds intervals.
        Exits cleanly when stop() is called. Never propagates exceptions.

        Called by the orchestrator as:
            thread = threading.Thread(target=monitor.run, daemon=True)
            thread.start()
        """
        self._running = True
        logger.info("NetworkHealthMonitor started")

        while self._running:
            try:
                self._perform_check()
            except Exception as exc:
                # Belt-and-suspenders: _perform_check() catches its own
                # exceptions, but anything unexpected here must not kill
                # the monitor thread.
                logger.error(
                    "NetworkHealthMonitor: unexpected exception | %s",
                    exc,
                    exc_info=True,
                )

            self._interruptible_sleep(self.check_interval_seconds)

        logger.info("NetworkHealthMonitor stopped")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        logger.info("NetworkHealthMonitor stop requested")

    # =========================================================================
    # CONNECTIVITY QUERY (called from orchestrator main thread)
    # =========================================================================

    def is_connected(self) -> bool:
        """Returns the current connectivity state.

        Thread-safe. May be polled from the orchestrator's main thread
        while the monitor thread is concurrently running a check.

        Returns:
            True if the network is currently considered connected.
        """
        with self._lock:
            return self._connected

    def is_healthy(self) -> bool:
        """Satisfies the HealthMonitor protocol — delegates to is_connected()."""
        return self.is_connected()

    def get_stats(self) -> dict:
        """Returns a snapshot of monitoring statistics.

        Returns:
            Dict with total_checks, total_failures, consecutive_failures,
            connected, and outage_started_at.
        """
        with self._lock:
            return {
                "total_checks":         self._total_checks,
                "total_failures":       self._total_failures,
                "consecutive_failures": self._consecutive_failures,
                "connected":            self._connected,
                "outage_started_at": (
                    self._outage_start.isoformat()
                    if self._outage_start else None
                ),
            }

    # =========================================================================
    # INTERNAL CHECK LOGIC
    # =========================================================================

    def _perform_check(self) -> None:
        """Executes one full connectivity probe cycle.

        Tries each TCP endpoint in order. On the first success, marks the
        network as connected (or restored if it was down) and returns.

        If all TCP checks fail, attempts an HTTP HEAD request as a final
        fallback before declaring the check failed.
        """
        with self._lock:
            self._total_checks += 1

        success, latency_ms = self._probe_tcp()

        if not success:
            # TCP checks all failed — try HTTP HEAD as a last resort.
            # This catches environments where outbound TCP to port 80 is
            # blocked but HTTP proxies are configured.
            success, latency_ms = self._probe_http()

        if success:
            self._on_check_success(latency_ms)
        else:
            self._on_check_failure()

    def _probe_tcp(self) -> tuple[bool, float]:
        """Attempts a TCP socket connection to each configured endpoint.

        Uses a raw socket connect — no DNS lookup for IP-based endpoints,
        no data transmitted. This is the fastest possible network check.

        Returns:
            (success: bool, latency_ms: float). latency_ms is 0.0 on failure.
        """
        for host, port in self.tcp_endpoints:
            start = time.monotonic()
            try:
                sock = socket.create_connection(
                    (host, port),
                    timeout=self.check_timeout_seconds,
                )
                sock.close()
                latency_ms = (time.monotonic() - start) * 1000.0
                logger.debug(
                    "NetworkHealthMonitor: TCP probe OK | %s:%d latency=%.0fms",
                    host, port, latency_ms,
                )
                return True, latency_ms
            except OSError:
                # Connection refused, timeout, or unreachable — try next.
                logger.debug(
                    "NetworkHealthMonitor: TCP probe failed | %s:%d", host, port
                )
                continue

        return False, 0.0

    def _probe_http(self) -> tuple[bool, float]:
        """Attempts an HTTP HEAD request to the fallback URL.

        Used only when all TCP checks have failed. Handles environments
        where direct IP:port is blocked but HTTP proxies route traffic.

        Returns:
            (success: bool, latency_ms: float). latency_ms is 0.0 on failure.
        """
        start = time.monotonic()
        try:
            req = urllib.request.Request(
                self.http_fallback_url,
                method="HEAD",
                headers={"User-Agent": "connectivity-check/1.0"},
            )
            with urllib.request.urlopen(req, timeout=self.check_timeout_seconds):
                pass
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.debug(
                "NetworkHealthMonitor: HTTP fallback probe OK | latency=%.0fms",
                latency_ms,
            )
            return True, latency_ms
        except Exception as exc:
            logger.debug(
                "NetworkHealthMonitor: HTTP fallback probe failed | %s", exc
            )
            return False, 0.0

    # =========================================================================
    # STATE TRANSITION HANDLERS
    # =========================================================================

    def _on_check_success(self, latency_ms: float) -> None:
        """Handles a successful connectivity check.

        If the network was previously down, calculates downtime and publishes
        NETWORK_RESTORED. Otherwise updates internal counters silently.

        Args:
            latency_ms: Observed round-trip latency for this check.
        """
        with self._lock:
            was_connected = self._connected
            outage_start = self._outage_start

            self._connected = True
            self._consecutive_failures = 0
            self._outage_start = None

        if not was_connected:
            # Transition: disconnected → connected.
            downtime_seconds = 0.0
            if outage_start is not None:
                downtime_seconds = (
                    datetime.now(timezone.utc) - outage_start
                ).total_seconds()

            logger.info(
                "NetworkHealthMonitor: connectivity RESTORED | downtime=%.0fs latency=%.0fms",  # noqa: E501
                downtime_seconds,
                latency_ms,
            )
            self.event_bus.publish(Event.NETWORK_RESTORED, {
                "downtime_seconds": round(downtime_seconds, 1),
                "latency_ms":       round(latency_ms, 1),
            })
        else:
            logger.debug(
                "NetworkHealthMonitor: connected | latency=%.0fms", latency_ms
            )

    def _on_check_failure(self) -> None:
        """Handles a failed connectivity check.

        Increments the failure counter. If the threshold is crossed and
        the network was previously considered up, publishes NETWORK_UNHEALTHY.
        """
        with self._lock:
            self._total_failures += 1
            self._consecutive_failures += 1
            consecutive = self._consecutive_failures
            was_connected = self._connected

        logger.warning(
            "NetworkHealthMonitor: connectivity check failed | "
            "consecutive=%d threshold=%d",
            consecutive,
            self.failure_threshold,
        )

        if consecutive >= self.failure_threshold and was_connected:
            # Transition: connected → disconnected.
            outage_start = datetime.now(timezone.utc)

            with self._lock:
                self._connected = False
                self._outage_start = outage_start

            logger.error(
                "NetworkHealthMonitor: connectivity LOST after %d consecutive failures",
                consecutive,
            )
            self.event_bus.publish(Event.NETWORK_UNHEALTHY, {
                "consecutive_failures": consecutive,
                "last_successful_check": (
                    # Approximate — the last success was at least one interval ago.
                    datetime.now(timezone.utc).isoformat()
                ),
            })

    # =========================================================================
    # SLEEP HELPER
    # =========================================================================

    def _interruptible_sleep(self, total_seconds: int) -> None:
        """Sleep for up to total_seconds, waking immediately if stop() is called."""
        self._stop_event.wait(timeout=total_seconds)
        self._stop_event.clear()