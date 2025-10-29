"""The public entry point for the framework-agnostic CAPTCHA detection system.

This module provides a clean, high-level interface for challenge detection.
It acts as a facade, hiding the implementation details of the underlying
strategy pattern. The rest of the application should only ever call the
`is_captcha_present` function from this module to perform a check.
"""
import logging
from ..core.browser_interface import BrowserInterface # <-- The key change
from .detection_strategy import DefaultDetectionStrategy, DetectionStrategy, CloudflareDetectionStrategy

logger = logging.getLogger(__name__)

def get_detection_strategy(browser: BrowserInterface) -> DetectionStrategy: # <-- Now accepts any adapter
    """Factory function that selects the most appropriate detection strategy.

    This function inspects the current state of the page (primarily the title)
    to determine if a specialized detection strategy is needed. If it recognizes
    a specific challenge provider like Cloudflare, it returns the specialized
    strategy; otherwise, it falls back to the robust default strategy.

    Args:
        browser: The framework-agnostic browser adapter instance.

    Returns:
        An instantiated detection strategy that conforms to the
        `DetectionStrategy` contract.
    """
    title = browser.title.lower()
    if "just a moment" in title or "checking your browser" in title:
        logger.debug("Cloudflare-like page detected. Using CloudflareDetectionStrategy.")
        return CloudflareDetectionStrategy(browser)

    logger.debug("Using DefaultDetectionStrategy.")
    return DefaultDetectionStrategy(browser)

def is_captcha_present(browser: BrowserInterface) -> bool: # <-- Now accepts any adapter
    """Checks if a bot-detection challenge is present on the current page.

    This is the main public function for the detection system. It orchestrates
    the process of selecting the correct strategy via the factory and then
    executing it to get a definitive answer.

    Args:
        browser: The framework-agnostic browser adapter instance to check.

    Returns:
        True if a challenge is detected, False otherwise.
    """
    strategy = get_detection_strategy(browser)
    return strategy.is_challenge_present()