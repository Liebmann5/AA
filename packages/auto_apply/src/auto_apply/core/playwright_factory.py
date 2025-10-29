"""Factory for creating Playwright-based browser adapter instances.

This module is responsible for the concrete implementation of creating a
Playwright browser session. It handles the unique lifecycle of Playwright,
which includes ensuring the necessary browser binaries are installed, starting
the main Playwright process, and configuring a browser context and page
before wrapping them in the unified PlaywrightAdapter.
"""
import logging
from playwright.sync_api import sync_playwright

from .base_factory import BaseFactory
from ..adapters.playwright_adapter import PlaywrightAdapter
from ..core.browser_interface import BrowserInterface
from . import playwright_manager
from ..config import settings
from .proxy_manager import ProxyManager
from ..exceptions import BrowserSetupError

logger = logging.getLogger(__name__)

class PlaywrightFactory(BaseFactory):
    """Implements the BaseFactory contract to produce PlaywrightAdapter instances."""

    def __init__(self, proxy_manager: ProxyManager = None):
        """Initializes the PlaywrightFactory.

        Args:
            proxy_manager: An optional ProxyManager to configure proxies.
        """
        super().__init__(proxy_manager)
        self._playwright_instance = None

    def get_driver(self, preferred_browser: str = "chromium") -> BrowserInterface:
        """
        (Me: Creates a Playwright browser Page and wraps it in a unified adapter.)
        Creates and returns a Playwright-based browser adapter.

        This method orchestrates the entire Playwright startup sequence:
        1.  It ensures the required browser binaries are installed on the host
            system by calling the `playwright_manager`.
        2.  It starts the main `sync_playwright` process.
        3.  It launches a browser instance (currently Chromium by default).
        4.  It creates a new browser context and page, applying the user agent.
        5.  Finally, it wraps all the Playwright objects in the unified
            `PlaywrightAdapter` to conform to the application's interface.

        Args:
            preferred_browser: The lowercase name of the desired browser.
                Currently defaults to "chromium".

        Returns:
            An initialized PlaywrightAdapter instance ready for use.

        Raises:
            BrowserSetupError: If the Playwright browser binaries cannot be
                installed or if the browser fails to launch.
        """
        proxy = self.proxy_manager.get_proxy() if self.proxy_manager else None

        if not playwright_manager.install_browsers():
            raise BrowserSetupError("Playwright browsers could not be installed.")

        try:
            logger.info("Launching Playwright...")
            self._playwright_instance = sync_playwright().start()

            proxy_dict = {"server": f"http://{proxy}"} if proxy else None

            browser = self._playwright_instance.chromium.launch(headless=False, proxy=proxy_dict)

            context = browser.new_context(user_agent=settings.scraping.user_agent)
            page = context.new_page()

            logger.info("Playwright browser launched successfully.")
            return PlaywrightAdapter(page, browser, self._playwright_instance)

        except Exception as e:
            logger.critical("Failed to launch Playwright browser.", exc_info=True)
            if self._playwright_instance:
                self._playwright_instance.stop()
            raise BrowserSetupError("Failed to initialize Playwright.") from e