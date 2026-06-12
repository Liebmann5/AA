"""Provides centralized rate limiting and throttling.

This module acts as the 'Traffic Controller'. It enforces delays between
requests to the same domain to respect `robots.txt` and prevent IP bans.
"""

import logging
import time
from urllib.parse import urlparse

from auto_apply.adapters.secondary.network.robots import RobotsPolicy
from auto_apply.domain.models.profile import PolitenessConfig

logger = logging.getLogger(__name__)


class DomainThrottler:
    """Manages delays between requests on a per-domain basis."""

    def __init__(
        self,
        user_politeness: PolitenessConfig | None = None,
        max_delay: float = 10.0,
    ) -> None:
        self.policy = RobotsPolicy(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        # Tracks the timestamp of the last request for each domain
        self._last_access: dict[str, float] = {}

        if user_politeness:
            self.config = user_politeness
        else:
            self.config = PolitenessConfig()  # defaults: respect_robots_txt=True, default_delay=2.0

        self.max_delay = max_delay

    def wait_for_domain(self, url: str) -> None:
        """Blocks execution until the domain is ready for a new request.

        If 'respect_robots_txt' is False, this returns immediately (Light Speed).
        Otherwise, it calculates the required sleep time based on the
        Crawl-Delay or default settings.
        """
        if not self.config.respect_robots_txt:
            return  # Light speed mode active

        domain = urlparse(url).netloc

        # 1. Determine required delay
        delay = self.policy.get_crawl_delay(url)

        default_delay = getattr(
            self.config,
            "default_delay",
            getattr(self.config, "default_delay_seconds", 2.0),
        )
        if delay is None:
            delay = default_delay

        delay = min(delay, self.max_delay)

        # 2. Calculate sleep time
        last_time = self._last_access.get(domain, 0)
        now = time.time()
        time_since_last = now - last_time

        if time_since_last < delay:
            sleep_time = delay - time_since_last
            logger.info(f"Throttling: Waiting {sleep_time:.2f}s for {domain}")
            time.sleep(sleep_time)

        # 3. Update last access
        self._last_access[domain] = time.time()

    def is_allowed(self, url: str) -> bool:
        """Checks if scraping this URL is legally/technically allowed."""
        if not self.config.respect_robots_txt:
            return True

        allowed = self.policy.can_fetch(url)
        if not allowed:
            logger.warning(f"Access to {url} is disallowed by robots.txt")
        return allowed

    def get_configured_delay(self, url: str) -> float:
        """Returns the delay enforced for this URL (Robots.txt or Default)."""
        delay = self.policy.get_crawl_delay(url)
        default_delay = getattr(
            self.config,
            "default_delay",
            getattr(self.config, "default_delay_seconds", 2.0),
        )
        return delay if delay is not None else default_delay