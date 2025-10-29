"""Factory for creating Selenium-based browser adapter instances.

This module is responsible for the concrete implementation of creating
Selenium WebDriver instances. It handles the complexities of selecting the
correct driver (e.g., undetected_chromedriver for Chrome), applying
hardened browser options, and includes a robust fallback mechanism to find
any supported browser installed on the user's system.
"""
import logging
from selenium import webdriver
import undetected_chromedriver as uc

from .base_factory import BaseFactory
from ..adapters.selenium_adapter import SeleniumAdapter
from ..core.browser_interface import BrowserInterface
from .proxy_manager import ProxyManager
from ..exceptions import BrowserSetupError
from ..utils.os_browser_detector import get_installed_browsers
from . import browser_options

logger = logging.getLogger(__name__)

class SeleniumFactory(BaseFactory):
    """Implements the BaseFactory contract to produce SeleniumAdapter instances.

    This factory contains the core logic for browser auto-detection and
    initialization, ensuring a resilient startup process.
    """

    def __init__(self, proxy_manager: ProxyManager = None):
        """Initializes the SeleniumFactory.

        This sets up the mapping between browser names and their corresponding
        Selenium driver classes and option-generating functions.

        Args:
            proxy_manager: An optional ProxyManager to configure proxies.
        """
        super().__init__(proxy_manager)
        self.browser_map = {
            "chrome": (uc.Chrome, browser_options.get_chrome_options),
            "firefox": (webdriver.Firefox, browser_options.get_firefox_options),
            "edge": (webdriver.Edge, browser_options.get_edge_options),
            "safari": (webdriver.Safari, browser_options.get_safari_options),
        }

    def get_driver(self, preferred_browser: str = "any") -> BrowserInterface:
        """Creates and returns a Selenium-based browser adapter.

        This method orchestrates the browser creation process with a two-stage
        approach for maximum robustness:
        1.  It first attempts to launch the user's `preferred_browser`.
        2.  If the preferred browser fails or is not specified, it falls back
            to a powerful auto-detection mechanism. It scans the local system
            for any supported installed browsers and attempts to launch them in
            a prioritized order.

        Args:
            preferred_browser: The lowercase name of the desired browser
                (e.g., "chrome", "firefox") or "any".

        Returns:
            An initialized SeleniumAdapter instance ready for use.

        Raises:
            BrowserSetupError: If all attempts to initialize both the preferred
                and any detected fallback browsers fail.
        """
        proxy = self.proxy_manager.get_proxy() if self.proxy_manager else None

        if preferred_browser and preferred_browser not in ["any", "playwright"]:
            logger.info("User prefers Selenium browser '%s'. Attempting to launch.", preferred_browser)
            if preferred_browser in self.browser_map:
                try:
                    driver_class, options_func = self.browser_map[preferred_browser]
                    options = options_func(proxy)
                    if options is not None:
                        driver = driver_class(options=options, use_subprocess=True) if preferred_browser == "chrome" else driver_class(options=options)
                        return SeleniumAdapter(driver)
                except Exception:
                    logger.warning("Preferred Selenium browser '%s' failed. Scanning for alternatives.", preferred_browser, exc_info=True)
            else:
                logger.warning("Preferred browser '%s' is not a supported Selenium browser.", preferred_browser)

        available_browsers = get_installed_browsers()
        if not available_browsers:
            raise BrowserSetupError("No supported Selenium browsers found on this system.")

        logger.info("Scanning for installed Selenium browsers. Attempting launch in order: %s", available_browsers)
        for browser_name in available_browsers:
            if browser_name in self.browser_map:
                try:
                    driver_class, options_func = self.browser_map[browser_name]
                    options = options_func(proxy)
                    if options is not None:
                        logger.info("Attempting to launch fallback browser: '%s'", browser_name)
                        driver = driver_class(options=options, use_subprocess=True) if browser_name == "chrome" else driver_class(options=options)
                        return SeleniumAdapter(driver)
                except Exception:
                    logger.warning("Could not initialize %s. Trying next browser.", browser_name, exc_info=True)

        raise BrowserSetupError(f"All detected Selenium browsers failed to initialize: {available_browsers}")