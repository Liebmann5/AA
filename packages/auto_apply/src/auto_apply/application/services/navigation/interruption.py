"""Provides robust utilities for handling common page interruptions.

This module is designed to handle interruptions like cookie banners, GDPR
consent forms, and other pop-ups that can block interaction with the main
page content. It centralizes the logic for detecting and dismissing these
elements, allowing the main scraping strategies to remain clean and focused
on their primary tasks.
"""
# Layer: application
# Depends on: domain

import logging

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.ports.interaction_port import InteractionPort
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# A prioritized list of selectors to identify consent buttons.
# We prioritize "Accept" over "Reject" to ensure site functionality remains broken.
CONSENT_HEURISTICS: list[dict[str, str]] = [
    # ID based
    {"by": Locator.XPATH, "selector": "//*[contains(@id, 'cookie') and contains(text(), 'Accept')]"},  # noqa: E501
    {"by": Locator.XPATH, "selector": "//*[contains(@id, 'consent') and contains(text(), 'Accept')]"},  # noqa: E501

    # Text based (Button/Link)
    {"by": Locator.XPATH, "selector": "//button[contains(normalize-space(), 'Accept all')]"},  # noqa: E501
    {"by": Locator.XPATH, "selector": "//button[contains(normalize-space(), 'I agree')]"},  # noqa: E501
    {"by": Locator.XPATH, "selector": "//button[contains(normalize-space(), 'Agree')]"},
    {"by": Locator.XPATH, "selector": "//button[contains(normalize-space(), 'Allow')]"},
    {"by": Locator.XPATH, "selector": "//a[contains(normalize-space(), 'Accept')]"},

    # Modern Frameworks (Test IDs and Aria)
    {"by": Locator.CSS_SELECTOR, "selector": "button[data-testid='accept-button']"},
    {"by": Locator.CSS_SELECTOR, "selector": "button[aria-label*='accept']"},

    # Common 'Close' buttons for popups
    {"by": Locator.CSS_SELECTOR, "selector": "button[aria-label='Close']"},
    {"by": Locator.CSS_SELECTOR, "selector": "div[class*='modal'] button[class*='close']"},  # noqa: E501
]


class InterruptionHandler:
    """Manages the detection and removal of page interruptions."""

    def __init__(self, browser: BrowserInterface):
        """Initializes the handler.

        Args:
            browser: The active browser instance.
        """
        self.browser = browser

    #! dismissing a banner is not a human behavior-sensitive operation
    def handle_interruptions(self) -> None:
        """Scans for and dismisses any active interruption elements.

        This method iterates through known heuristics for popups. If found,
        it attempts to click them using human-like behavior to avoid detection.
        It suppresses errors to ensure the main bot flow is never blocked by
        a failed dismissal.
        """
        for heuristic in CONSENT_HEURISTICS:
            try:
                elements = self.browser.find_elements(heuristic["by"], heuristic["selector"])
                visible_elements = [el for el in elements if self._is_visible(el)]
                for element in visible_elements:
                    logger.info(f"InterruptionHandler: Dismissing overlay via {heuristic['selector']}")
                    try:
                        element.click()   # direct click — no human timing needed for banners
                        return
                    except Exception:
                        logger.debug("Found overlay but failed to click.")
            except Exception:
                continue
        # logger.debug("Scanning for interruption overlays...")

        # for heuristic in CONSENT_HEURISTICS:
        #     try:
        #         elements = self.browser.find_elements(heuristic["by"], heuristic["selector"])  # noqa: E501

        #         # We only interact with visible elements
        #         visible_elements = [el for el in elements if self._is_visible(el)]

        #         for element in visible_elements:
        #             logger.info(f"InterruptionHandler: Dismissing overlay via {heuristic['selector']}")  # noqa: E501
        #             try:
        #                 self._interactor.click(element)
        #                 return  # Usually only one banner per page, return after success
        #             except Exception:
        #                 logger.debug("Found overlay but failed to click. It might be obscured.")  # noqa: E501
        #     except Exception:
        #         continue

    def _is_visible(self, element: ElementInterface) -> bool:
        """Checks if an element is likely visible to the user.

        Args:
            element (ElementInterface): The element to check.

        Returns:
            bool: True if dimensions > 0.
        """
        try:
            size = element.get_size()
            return size[0] > 0 and size[1] > 0
        except Exception:
            return False
