"""Browser Leasing for Concurrency Safety.

Provides a lease-based mechanism to ensure only one code path at a time
holds a reference to the single browser driver.  All navigation or DOM
interaction that requires the browser must acquire a lease first.
"""

import threading
from contextlib import contextmanager
from typing import Optional

from auto_apply.domain.ports.browser_port import BrowserInterface


class BrowserLeaseManager:
    """Enforces a maximum concurrency limit on browser usage.

    In a single-browser session (max_concurrent=1) this is a simple mutual-
    exclusion lock that prevents overlapping driver commands from different
    threads / workers.

    **Important design note — single shared driver**  
    The current AA architecture shares exactly one browser driver (Selenium
    or Playwright) across all providers, engines, and the health monitor.
    This lease serialises access to that shared instance.  Both Selenium
    and Playwright's core objects (WebDriver, Page) are **not** thread‑safe,
    so serialisation is required for correctness.

    **True parallel execution is a future capability**  
    Running multiple providers concurrently with separate Playwright
    ``BrowserContext`` objects (or multiple Selenium windows) would require
    each worker to hold a *separate* driver instance, not just a lease on a
    shared one.  The current ``BrowserLeaseManager`` does **not** enable
    that — a single driver with max_concurrent=1 will always serialise.
    A multi‑driver architecture is a separate feature and is not a gap
    in this implementation of single‑driver concurrency safety.

    Args:
        driver: The active BrowserInterface.  May be None when no browser
            is available (static-fallback mode).
        max_concurrent: Maximum number of leases that may be held
            simultaneously.  Default 1.  **Must be 1 for single‑driver
            sessions.**
    """

    def __init__(
        self,
        driver: Optional[BrowserInterface],
        max_concurrent: int = 1,
    ) -> None:
        self._driver = driver
        self._semaphore = threading.Semaphore(max_concurrent)

    @contextmanager
    def acquire(self):
        """Acquire a lease, yield the driver, and release it."""
        self._semaphore.acquire()
        try:
            yield self._driver
        finally:
            self._semaphore.release()