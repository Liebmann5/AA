"""
Factory for creating WebDriver instances for mobile platforms using Appium.
"""
import logging
from appium import webdriver as appium_webdriver
from ..exceptions import BrowserSetupError
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

class MobileBrowserFactory:
    def __init__(self, proxy_manager: ProxyManager = None):
        pass

    def get_driver(self, preferred_browser: str = None):
        """
        Connects to a running Appium server and creates a mobile browser session.
        """
        logger.info("Attempting to connect to Appium server for mobile browser.")

        desired_caps = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:deviceName": "Android Emulator",
            "browserName": "Chrome",
            "appium:nativeWebScreenshot": True,
        }

        try:
            driver = appium_webdriver.Remote('http://localhost:4723/wd/hub', desired_caps)
            logger.info("Successfully connected to Appium and started mobile Chrome.")
            return driver
        except Exception as e:
            logger.critical(
                "Failed to connect to Appium server. Please ensure Appium is installed, "
                "running, and configured correctly. Error: %s", e
            )
            raise BrowserSetupError(
                "Could not initialize mobile browser via Appium. This is an advanced "
                "feature that requires manual setup."
            ) from e