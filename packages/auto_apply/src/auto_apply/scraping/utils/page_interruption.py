"""Provides robust utilities for handling common page interruptions.

This module is designed to handle interruptions like cookie banners, GDPR
consent forms, and other pop-ups that can block interaction with the main
page content. It centralizes the logic for detecting and dismissing these
elements, allowing the main scraping strategies to remain clean and focused on
their primary tasks.
"""
import logging
from typing import List, Dict, Any
from selenium.webdriver.common.by import By
from ...core.browser_interface import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)

CONSENT_HEURISTICS: List[Dict[str, Any]] = [
    {"by": By.XPATH, "selector": "//*[contains(@id, 'cookie') and contains(text(), 'Accept')]", "description": "ID with 'cookie' and text 'Accept'"},
    {"by": By.XPATH, "selector": "//*[contains(@id, 'consent') and contains(text(), 'Accept')]", "description": "ID with 'consent' and text 'Accept'"},
    {"by": By.CSS_SELECTOR, "selector": "button[data-testid='accept-button']", "description": "Button with test ID 'accept-button'"},
    {"by": By.XPATH, "selector": "//button[contains(normalize-space(), 'Accept all')]", "description": "Button with text 'Accept all'"},
    {"by": By.XPATH, "selector": "//button[contains(normalize-space(), 'I agree')]", "description": "Button with text 'I agree'"},
    {"by": By.XPATH, "selector": "//button[contains(normalize-space(), 'Agree')]", "description": "Button with text 'Agree'"},
    {"by": By.XPATH, "selector": "//button[contains(normalize-space(), 'Got it')]", "description": "Button with text 'Got it'"},
]

def ensure_page_is_ready(browser: BrowserInterface, timeout_seconds: int = 3) -> None:
    """Attempts to find and dismiss common consent banners and pop-ups.

    This function iterates through a predefined list of common selectors and
    text keywords (`CONSENT_HEURISTICS`) to identify potential interruption
    elements. If an element is found, it attempts to click it to dismiss it.

    It is designed as a "fire-and-forget" utility that fails gracefully. It uses
    a short timeout and suppresses exceptions, as the absence of a banner is
    the most common (and desired) outcome.

    Args:
        browser: The framework-agnostic browser adapter instance.
        timeout_seconds: A deliberately SHORT timeout to prevent long waits on
            pages that do not have any banners.
    """
    logger.debug("Checking for common consent banners and pop-ups...")

    for heuristic in CONSENT_HEURISTICS:
        try:
            elements: List[ElementInterface] = browser.find_elements(heuristic["by"], heuristic["selector"])

            for element in elements:
                logger.info(f"Found potential consent element via '{heuristic['description']}'. Attempting to click.")
                try:
                    element.click()
                    logger.info("Successfully clicked consent element.")
                    return
                except Exception:
                    logger.debug("Element found but could not be clicked. It may be obscured.")
        except Exception:
            continue