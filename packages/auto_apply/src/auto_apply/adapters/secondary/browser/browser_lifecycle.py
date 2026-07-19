"""Provides a robust context manager for the browser driver lifecycle.

This module contains the `BrowserManager`, a crucial component for ensuring that
browser driver instances are always shut down cleanly and reliably, preventing
resource leaks and orphaned browser processes.
"""

import logging

from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)


class BrowserManager:
    """A context manager to handle the lifecycle of any BrowserInterface adapter.

    This class implements the context manager protocol (`__enter__` and `__exit__`).
    When used in a `with` statement, it guarantees that the `close()` method of
    the provided browser adapter is called upon exiting the block, regardless of
    whether the block completes successfully or raises an exception.

    This is the primary mechanism for ensuring application stability and preventing
    zombie browser processes.

    Example:
        browser_adapter = SeleniumAdapter(driver)
        with BrowserManager(browser_adapter) as browser:
            browser.get("https://example.com")
        # browser_adapter.close() is automatically called here.
    """

    def __init__(self, browser_adapter: BrowserInterface):
        """Initializes the manager with a pre-configured browser adapter.

        Args:
            browser_adapter (BrowserInterface): An initialized adapter object
                (e.g., SeleniumAdapter, PlaywrightAdapter) that conforms to the
                BrowserInterface contract.

        Raises:
            TypeError: If the provided object does not implement the BrowserInterface.
        """
        if not isinstance(browser_adapter, BrowserInterface):
            raise TypeError("Provided object must be a valid BrowserInterface adapter.")
        self.adapter = browser_adapter

    def __enter__(self) -> BrowserInterface:
        """Enters the runtime context and returns the managed browser adapter.

        Returns:
            BrowserInterface: The browser adapter instance that was passed to the
                              constructor, ready for use within the `with` block.
        """
        logger.info(
            "BrowserManager is now managing the lifecycle for: %s",
            self.adapter.framework_name
        )
        return self.adapter

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exits the runtime context, ensuring the browser is closed.

        This method is called automatically when the `with` block is exited.
        It safely calls the adapter's `close()` method and logs any potential
        errors that might occur during shutdown, preventing them from crashing
        the main application.

        Args:
            exc_type: The type of the exception that caused the exit, if any.
            exc_val: The exception instance that caused the exit, if any.
            exc_tb: A traceback object associated with the exception, if any.
        """
        logger.info("BrowserManager is shutting down the browser...")
        try:
            self.adapter.close()
            logger.info("Browser shut down successfully.")
        except Exception as e:
            # We log the exception but do not re-raise it. The primary goal
            # of __exit__ is to ensure a clean shutdown, not to crash the app.
            logger.error(
                "BrowserManager: Error while shutting down the '%s' adapter: %s",
                self.adapter.framework_name, e, exc_info=True
            )
            # We suppress the error during shutdown so we don't hide the original exception  # noqa: E501
            # if one occurred inside the 'with' block.