"""
Manages a pool of proxies for network requests to avoid IP-based detection.
"""
import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyManager:
    """Loads and provides proxies from a user-supplied file."""

    def __init__(self, proxy_file: Path):
        self.proxy_file = proxy_file
        self.proxies: list[str] = []
        self._load_proxies()

    def _load_proxies(self):
        """Loads a list of proxies from a text file, one proxy per line."""
        if not self.proxy_file.exists():
            logger.info("Proxy file not found at '%s'. Proceeding without proxies.", self.proxy_file)
            return

        try:
            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                self.proxies = [line.strip() for line in f if line.strip()]

            if self.proxies:
                logger.info("Successfully loaded %d proxies.", len(self.proxies))
            else:
                logger.warning("Proxy file exists but is empty.")
        except Exception as e:
            logger.error("Failed to load proxies. Error: %s", e)

    def get_proxy(self) -> Optional[str]:
        """
        Returns a random proxy from the loaded list.
        Returns None if no proxies are loaded.
        """
        if not self.proxies:
            return None
        return random.choice(self.proxies)