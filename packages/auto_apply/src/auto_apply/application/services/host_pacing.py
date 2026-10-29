"""Per-host navigation pacing — one owner for every contact AA makes.

Several sessions can hammer one host: engines during discovery, and one ATS
host when a site-restricted search concentrates postings on it. This service
spaces consecutive contacts to any single host by a configured floor with
seeded jitter, so "how fast AA talks to a site" is config-driven, seeded, and
measured in one place instead of scattered literals.

Thread safety: reservations are taken under a lock. A second caller for the
same host reserves the slot AFTER the first caller's, so interleaving cannot
violate the floor even when discovery fans out across worker threads.

Determinism: jitter comes from the injected RNG (BehaviorParameters.make_rng
namespace "discovery.host_pacing"). When the floor equals the ceiling no
draw is made at all, and an unseeded RNG simply widens the range.

Not consulted here: robots.txt. Interactive browsing is not bulk crawling;
a robots fetch would itself be a request. The throttler/robots machinery
remains available for a future bulk-fetch path where that question applies.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class HostPacer:
    """Spaces consecutive contacts to one host by a configured floor.

    Args:
        min_interval_s: Floor in seconds between two contacts to the same host.
        max_interval_s: Ceiling; the jitter range is [floor, ceiling].
        rng: Seeded RNG for the jitter draw. None means the floor is used
            whenever a wait is needed beyond the first contact.
        sleeper: Injected sleep (tests pass a recorder).
        clock: Injected monotonic clock (tests pass a controllable one).
    """

    def __init__(
        self,
        min_interval_s: float,
        max_interval_s: float,
        *,
        rng=None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min = max(0.0, float(min_interval_s))
        self._max = max(self._min, float(max_interval_s))
        self._rng = rng
        self._sleep = sleeper
        self._now = clock
        self._ledger: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait_for_url(self, url: str) -> float:
        """Reserve the next contact slot for *url*'s host and wait it out.

        Returns the seconds waited (0.0 for a first contact or a fresh host).
        Never raises on a malformed URL — an unparseable URL is not paced.
        """
        host = _host_of(url)
        if not host:
            return 0.0
        interval = self._interval()
        now = self._now()
        with self._lock:
            last = self._ledger.get(host)
            if last is None:
                self._ledger[host] = now
                return 0.0
            earliest = last + interval
            wait = earliest - now
            if wait <= 0.0:
                self._ledger[host] = now
                return 0.0
            # Reserve BEFORE sleeping, so a concurrent caller queues behind.
            self._ledger[host] = earliest
        self._sleep(wait)
        logger.debug("HostPacer: waited %.2fs before contacting %s again", wait, host)
        return wait

    def _interval(self) -> float:
        """This contact's spacing: the floor plus a seeded jitter draw."""
        if self._max <= self._min:
            return self._min
        if self._rng is None:
            return self._min
        return self._min + self._rng.uniform(0.0, self._max - self._min)


def _host_of(url: str) -> str:
    """The contact key for a URL: lowercased host, userinfo and port stripped."""
    try:
        netloc = urlparse(url or "").netloc.lower()
    except Exception:
        return ""
    if not netloc:
        return ""
    return netloc.split("@")[-1].split(":")[0]
