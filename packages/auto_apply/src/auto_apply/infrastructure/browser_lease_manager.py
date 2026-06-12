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

    Args:
        driver: The active BrowserInterface.  May be None when no browser
            is available (static-fallback mode).
        max_concurrent: Maximum number of leases that may be held
            simultaneously.  Default 1.
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