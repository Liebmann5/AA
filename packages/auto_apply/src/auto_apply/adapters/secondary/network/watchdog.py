"""Provides network stability monitoring.

This module acts as a circuit breaker for internet connectivity. It allows
the application to pause execution during network outages rather than crashing.
"""

import logging
import socket
import time

logger = logging.getLogger(__name__)

class ConnectionWatchdog:
    """Monitors internet connectivity and manages wait-loops."""

    def __init__(self, host="8.8.8.8", port=53, timeout=3):
        self.host = host
        self.port = port
        self.timeout = timeout

    def check_connection(self) -> bool:
        """Pings a reliable host (Google DNS) to verify connectivity."""
        try:
            socket.setdefaulttimeout(self.timeout)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.host, self.port))
            return True
        except OSError:
            return False

    def ensure_connected(self) -> None:
        """Blocks execution until the internet connection is active.

        If connection is lost, this enters a sleep loop, logging updates
        to the user. It effectively 'pauses' the bot during outages.
        """
        if self.check_connection():
            return

        logger.warning("⚠️ Internet connection lost! Pausing Agent...")

        start_time = time.time()
        while not self.check_connection():
            logger.info("Waiting for network to recover...")
            time.sleep(10) # Check every 10 seconds

            # Optional: Timeout after 1 hour to prevent infinite zombie process
            if time.time() - start_time > 3600:
                raise ConnectionError("Network down for over 1 hour. Shutting down safety.")  # noqa: E501

        logger.info("✅ Internet connection restored. Resuming Agent.")