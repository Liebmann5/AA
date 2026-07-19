"""Provides parsing of robots.txt files for compliance.

This module acts as the 'Legal Counsel' for the bot. It checks if the target
website allows automated access to specific paths and retrieves the requested
Crawl-Delay to prevent server overload.
"""

import logging
import urllib.robotparser
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RobotsPolicy:
    """Manages robots.txt rules for multiple domains."""

    def __init__(self, user_agent: str = "*"):
        """Initializes the policy manager.

        Args:
            user_agent (str): The UA string we are identifying as.
                              Default is '*' (generic bot), but should match
                              the browser's UA for accuracy.
        """
        self.user_agent = user_agent
        # Cache parsers by domain so we don't re-download robots.txt every time
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        """Checks if the URL is allowed by robots.txt."""
        parser = self._get_parser(url)
        if not parser:
            return True # If we can't parse robots.txt, assume allowed (fail open)

        return parser.can_fetch(self.user_agent, url)

    def get_crawl_delay(self, url: str) -> float | None:
        """Gets the requested delay from robots.txt."""
        parser = self._get_parser(url)
        if not parser:
            return None

        return parser.crawl_delay(self.user_agent)

    def _get_parser(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """Retrieves or creates a parser for the domain of the given URL."""
        domain = urlparse(url).netloc
        if domain in self._parsers:
            return self._parsers[domain]

        robots_url = f"https://{domain}/robots.txt"
        logger.debug(f"Fetching robots.txt from: {robots_url}")

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
            self._parsers[domain] = parser
            return parser
        except Exception as e:
            logger.warning(f"Could not fetch/parse robots.txt for {domain}: {e}")
            # Cache None so we don't retry failed fetches constantly
            self._parsers[domain] = None
            return None