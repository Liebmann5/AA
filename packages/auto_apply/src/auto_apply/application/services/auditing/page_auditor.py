"""Audits the visual and structural content of the current page."""

# Layer: application
# Depends on: domain

import logging

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

class PageAuditor:
    def __init__(self, browser: BrowserInterface):
        self.browser = browser

    def snapshot(self) -> dict:
        """Captures a snapshot of the visible page state."""
        snapshot = {
            "url": self.browser.current_url,
            "title": self.browser.title,
            "snippet": "N/A",
            "link_count": 0
        }

        try:
            # Grab a text snippet (first 200 chars of body)
            body = self.browser.find_element(Locator.TAG_NAME, "body")
            if body:
                snapshot["snippet"] = body.text[:200].replace("\n", " ")

            # Count links (Good indicator of a SERP vs Empty Page)
            links = self.browser.find_elements(Locator.TAG_NAME, "a")
            snapshot["link_count"] = len(links)

        except Exception as e:
            logger.warning(f"Page audit partial failure: {e}")

        return snapshot
