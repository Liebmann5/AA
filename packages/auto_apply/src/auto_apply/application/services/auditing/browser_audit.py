"""Audits the browser instance for fingerprinting consistency.

This module inspects the active browser to ensure that evasion techniques
(like User-Agent spoofing and WebDriver masking) are successfully applied
and detectable within the JavaScript environment.
"""

# Layer: application
# Depends on: domain

import logging
from typing import Any

from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)


class BrowserAuditor:
    """Inspects the browser's runtime environment."""

    def __init__(self, browser: BrowserInterface):
        """Initializes the auditor.

        Args:
            browser (BrowserInterface): The active browser to inspect.
        """
        self.browser = browser

    def snapshot(self) -> dict[str, Any]:
        """Captures a snapshot of the browser's fingerprint.

        It executes JavaScript to read properties that websites use to detect bots.

        Returns:
            Dict[str, Any]: A dictionary containing critical fingerprint data.
        """
        snapshot = {
            "framework": self.browser.framework_name,
            "user_agent": "Unknown",
            "webdriver_flag": "Unknown",
            "window_size": "Unknown",
            "cookies_count": 0
        }

        try:
            # 1. Check User Agent (JS vs HTTP)
            snapshot["user_agent"] = self.browser.execute_script("return navigator.userAgent;")  # noqa: E501

            # 2. Check WebDriver Flag (The most common bot signal)
            # If evasion is working, this should be False or Undefined
            wd_flag = self.browser.execute_script("return navigator.webdriver;")
            snapshot["webdriver_flag"] = str(wd_flag)

            # 3. Check Window Geometry
            width = self.browser.execute_script("return window.innerWidth;")
            height = self.browser.execute_script("return window.innerHeight;")
            snapshot["window_size"] = f"{width}x{height}"

            # 4. Check Cookies
            cookies = self.browser.get_cookies()
            snapshot["cookies_count"] = len(cookies)

        except Exception as e:
            logger.warning(f"Browser audit partial failure: {e}")

        return snapshot
