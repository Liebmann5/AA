"""The central manager for Evasion and Anti-Bot techniques.

This module provides the `EvasionManager`, which acts as a high-level controller
for applying stealth configurations and performing runtime checks (like
validating if the current page is safe to scrape).
"""

import logging
import time

from auto_apply.adapters.secondary.evasion import detection
from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)


class EvasionManager:
    """Orchestrates evasion tactics and safety checks."""

    def __init__(self, browser: BrowserInterface, config: dict | None = None) -> None:
        """Initializes the manager.

        Args:
            browser: The active browser instance.
            config: Optional dictionary containing evasion settings.
                    Keys:
                      - enable_captcha_detection (bool, default True)
                      - on_captcha_detected (str, default "skip")
        """
        self.browser = browser
        cfg = config or {}
        self._enable_captcha_detection = cfg.get("enable_captcha_detection", True)
        self._on_captcha_detected = cfg.get("on_captcha_detected", "skip")

    def check_page_safety(self) -> bool:
        """Determines if the current page is safe to process.

        It checks for CAPTCHAs or blocks. If a block is found, it can optionally
        trigger mitigation strategies (like waiting or alerting).

        Returns:
            bool: True if the page appears safe (no CAPTCHA).
                  False if the page is blocked.
        """
        if self._enable_captcha_detection:
            if detection.is_challenge_present(self.browser):
                logger.warning("EvasionManager: Active challenge detected on page.")
                self._handle_detection()
                return False

        return True

    def _handle_detection(self) -> None:
        """Handles the response when a block is detected."""
        action = self._on_captcha_detected

        if action == "stop":
            logger.warning(
                "CAPTCHA policy is 'stop'. Skipping this provider without retry."
            )
            return  # check_page_safety() returns False; provider fails cleanly.

        elif action == "retry":
            # For now, we just log. In the future, this could trigger a proxy rotation
            # or an automated solver.
            logger.info("Policy is RETRY. Waiting 5 seconds to see if it clears...")
            time.sleep(5)
            # Re-check
            if detection.is_challenge_present(self.browser):
                logger.error("Challenge persisted after wait.")