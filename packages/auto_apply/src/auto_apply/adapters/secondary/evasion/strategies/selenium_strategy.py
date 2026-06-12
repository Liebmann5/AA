"""The Evasion Strategy specifically implemented for Selenium-based browsers.

This module contains the concrete implementation of the EvasionStrategyInterface
for browsers controlled by Selenium WebDriver. It is responsible for applying
evasion techniques that are unique to the WebDriver protocol, such as using the
Chrome DevTools Protocol (CDP) for deep browser modification.
"""
import logging

from .. import fingerprint_chrome, fingerprint_firefox
from .base import EvasionStrategyInterface

logger = logging.getLogger(__name__)

class SeleniumEvasionStrategy(EvasionStrategyInterface):
    """Manages all evasion tactics that rely on the Selenium WebDriver protocol.

    This class fulfills the EvasionStrategyInterface contract. Note that the
    `__init__` and `manage_session_startup` methods are inherited from the
    base class, as their logic is framework-agnostic.
    """

    def apply_static_evasion(self) -> None:
        """Applies static fingerprint modifications for Selenium browsers.

        This method acts as a router. It first checks that the provided browser
        is a Selenium-based adapter. It then inspects the browser's capabilities
        to identify the specific browser type (e.g., 'chrome', 'firefox') and
        delegates the application of evasions to the appropriate private helper
        method (`_apply_chrome_evasion` or `_apply_firefox_evasion`).
        """
        try:
            raw_driver = self.browser.get_raw_driver()
        except AttributeError:
            logger.warning("The provided browser adapter does not have 'get_raw_driver' Skipping Selenium evasions")  # noqa: E501

        browser_name = raw_driver.capabilities.get('browserName', '').lower()

        logger.info(f"Applying static Selenium evasion tactics for: {browser_name}")

        if 'chrome' in browser_name or 'edge' in browser_name:
            self._apply_chrome_evasion(raw_driver)
        elif 'firefox' in browser_name:
            self._apply_firefox_evasion(raw_driver)
        else:
            logger.warning(f"No specialized static evasion tactics for browser '{browser_name}'.")  # noqa: E501

    def _apply_chrome_evasion(self, driver) -> None:
        """Orchestrates all evasion tactics for Chrome/Chromium browsers.

        This method leverages the Chrome DevTools Protocol (CDP), which is
        exposed by the Selenium driver. It calls a series of specialized
        functions from the `fingerprint_chrome` module to apply various
        fingerprint-hardening techniques based on the application's settings.

        Args:
            driver: The raw Selenium WebDriver instance for a Chromium-based browser.
        """
        if not self.settings.enable_fingerprint_spoofing:
            logger.warning("Fingerprint spoofing is disabled in settings.")
            return

        fingerprint_chrome.remove_automation_artifacts(driver)

        if self.settings.webgl_spoof_strategy != "off":
            fingerprint_chrome.spoof_webgl(
                driver,
                strategy=self.settings.webgl_spoof_strategy,
                vendor=self.settings.custom_webgl_vendor,
                renderer=self.settings.custom_webgl_renderer
            )

        if self.settings.canvas_spoof_strategy != "off":
            fingerprint_chrome.spoof_canvas(
                driver,
                strategy=self.settings.canvas_spoof_strategy
            )

        if self.settings.spoof_hardware_concurrency:
            fingerprint_chrome.spoof_hardware(
                driver,
                cores=self.settings.spoof_hardware_concurrency
            )

        if self.settings.standardize_fonts:
            fingerprint_chrome.standardize_fonts(driver)

        fingerprint_chrome.harden_permissions_api(driver)
        fingerprint_chrome.spoof_audio_context(driver)

    def _apply_firefox_evasion(self, driver) -> None:
        """Orchestrates all evasion tactics for Firefox browsers.

        Firefox evasion relies heavily on setting specialized `about:config`
        preferences (handled in `browser_options.py`) and injecting JavaScript
        patches after the page loads. This method calls the `fingerprint_firefox`
        module to apply those runtime patches.

        Args:
            driver: The raw Selenium WebDriver instance for Firefox.
        """
        if not self.settings.enable_fingerprint_spoofing:
            logger.warning("Fingerprint spoofing is disabled in settings.")
            return

        fingerprint_firefox.apply_firefox_hardening(driver)
