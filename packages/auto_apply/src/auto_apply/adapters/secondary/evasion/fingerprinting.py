"""Provides mechanisms to harden browser fingerprints against detection.

This module consolidates techniques for Chrome (via CDP) and Firefox (via JS Injection)
to mask automation signals like `navigator.webdriver`, spoof WebGL/Canvas readouts,
and normalize hardware concurrency reporting.
"""

import logging
import random

# We import the raw WebDriver types for type checking, but handle errors if not installed  # noqa: E501
try:
    from selenium.webdriver.remote.webdriver import WebDriver
except ImportError:
    WebDriver = None

logger = logging.getLogger(__name__)


class FingerprintMasker:
    """Applies anti-fingerprinting patches to a running browser instance."""

    def __init__(self, browser_interface):
        """Initializes the masker.

        Args:
            browser_interface: The AutoApply BrowserInterface adapter.
        """
        self.browser = browser_interface

    def apply_static_evasion(self) -> None:
        """Applies modifications to the browser environment.

        This method detects the underlying framework (Selenium/Playwright) and
        browser type (Chrome/Firefox) to apply the most effective patches.
        """
        if self.browser.framework_name == "selenium":
            self._apply_selenium_evasion()
        elif self.browser.framework_name == "playwright":
            self._apply_playwright_evasion()

    def _apply_selenium_evasion(self) -> None:
        """Handles Selenium-specific patching."""
        try:
            raw_driver = self.browser.get_raw_driver()
            browser_name = raw_driver.capabilities.get('browserName', '').lower()

            if 'chrome' in browser_name or 'edge' in browser_name:
                self._patch_chrome_cdp(raw_driver)
            elif 'firefox' in browser_name:
                self._patch_firefox_js(raw_driver)
        except Exception as e:
            logger.warning(f"Failed to apply Selenium evasion: {e}")

    def _apply_playwright_evasion(self) -> None:
        """Handles Playwright-specific patching."""
        # Playwright supports add_init_script which is cleaner than CDP
        try:
            page = self.browser.get_raw_page()
            js_payload = self._get_generic_js_payload()
            page.add_init_script(js_payload)
            logger.info("Applied Playwright Init Scripts for evasion.")
        except Exception as e:
            logger.warning(f"Failed to apply Playwright evasion: {e}")

    def _patch_chrome_cdp(self, driver: WebDriver) -> None:
        """Uses Chrome DevTools Protocol to inject scripts on every new document."""
        logger.info("Applying Chrome CDP Evasion Patches.")

        # 1. Remove navigator.webdriver
        script = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})  # noqa: E501

        # 2. Hardware Concurrency Spoofing
        cores = random.choice([4, 8, 12, 16])
        script = f"Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {cores}}})"  # noqa: E501
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})  # noqa: E501

        # 3. WebGL Spoofing (Basic)
        # Overwrites getParameter to return a common GPU vendor
        webgl_script = """
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            // UNMASKED_VENDOR_WEBGL
            if (parameter === 37445) return 'Google Inc. (NVIDIA)';
            // UNMASKED_RENDERER_WEBGL
            if (parameter === 37446) return 'NVIDIA GeForce RTX 3060 Ti';
            return getParameter.apply(this, arguments);
        };
        """
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": webgl_script})  # noqa: E501

    def _patch_firefox_js(self, driver: WebDriver) -> None:
        """Injects JS into the current page for Firefox."""
        # Firefox (Selenium) doesn't support Page.addScriptToEvaluateOnNewDocument easily.  # noqa: E501
        # We rely mostly on the 'about:config' prefs set in core/options.py.
        # This is a supplementary runtime patch.
        logger.info("Applying Firefox JS Evasion Patches.")
        driver.execute_script(self._get_generic_js_payload())

    def _get_generic_js_payload(self) -> str:
        """Returns a string of JS to neutralize common fingerprint vectors."""
        return """
        // 1. Mask WebDriver
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

        // 2. Add Plugins (Chrome is empty by default in headless)
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});

        // 3. Add Languages
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """
