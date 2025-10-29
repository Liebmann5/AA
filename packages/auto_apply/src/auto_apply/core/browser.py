"""
Provides a robust, universal context manager for any BrowserInterface instance.
"""
import logging
from ..core.browser_interface import BrowserInterface

logger = logging.getLogger(__name__)

class BrowserManager:
    """
    A context manager to handle the lifecycle of any browser adapter.
    This guarantees that the browser is always closed cleanly.
    """

    def __init__(self, browser_adapter: BrowserInterface):
        """
        Initializes the manager with a pre-configured browser adapter.

        Args:
            browser_adapter: An initialized adapter (e.g., SeleniumAdapter, PlaywrightAdapter).
        """
        if not isinstance(browser_adapter, BrowserInterface):
            raise TypeError("Provided object must be a valid BrowserInterface adapter.")
        self.adapter = browser_adapter

    def __enter__(self) -> BrowserInterface:
        """Returns the browser adapter when entering the 'with' block."""
        logger.info("BrowserManager is now managing the browser lifecycle for '%s'.", 
                    self.adapter.__class__.__name__)
        return self.adapter

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleans up and closes the browser when exiting the 'with' block."""
        logger.info("Shutting down browser via BrowserManager...")
        try:
            self.adapter.close()
            logger.info("Browser shut down successfully.")
        except Exception:
            logger.exception("An error occurred while shutting down the browser adapter.")