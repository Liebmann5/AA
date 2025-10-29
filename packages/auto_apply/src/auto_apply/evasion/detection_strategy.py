"""Defines a framework-agnostic strategy pattern for detecting bot challenges.

This module provides the abstract base class `DetectionStrategy` and several
concrete implementations. This pattern allows the application to select the
most appropriate set of detection rules at runtime (e.g., a general-purpose
strategy vs. one specialized for Cloudflare) and apply them without the core
logic needing to know the specific details of the checks being performed.

All strategies operate on the generic `BrowserInterface`, ensuring they are
completely framework-agnostic.
"""
import json
import logging
from abc import ABC, abstractmethod
from importlib import resources

from selenium.webdriver.common.by import By
from ..core.browser_interface import BrowserInterface

logger = logging.getLogger(__name__)

class DetectionStrategy(ABC):
    """Abstract base class (contract) for a challenge detection strategy."""

    def __init__(self, browser: BrowserInterface):
        """Initializes the strategy with a browser instance.

        Args:
            browser: A browser adapter that conforms to the BrowserInterface.
        """
        self.browser = browser

    @abstractmethod
    def is_challenge_present(self) -> bool:
        """Executes all checks to determine if a challenge is on the page.

        Returns:
            True if a bot-detection challenge is found, False otherwise.
        """
        pass

class DefaultDetectionStrategy(DetectionStrategy):
    """A comprehensive, multi-vector detection strategy for common CAPTCHAs.

    This strategy uses a series of checks across different vectors (URL, title,
    iframes, JavaScript variables, and page text) to identify the presence of
    common challenge providers like reCAPTCHA and hCaptcha. The keywords and
    selectors for these checks are loaded from `detection_config.json`.
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the default strategy.

        This constructor loads the 'default' configuration from the JSON file
        and defines the sequence of checks to be executed.

        Args:
            browser: A browser adapter that conforms to the BrowserInterface.
        """
        super().__init__(browser)
        self.config = self._load_config("default")
        self.checks = [
            self._check_url_and_title,
            self._check_js_variables,
            self._check_iframes,
            self._perform_deep_scan
        ]

    def _load_config(self, strategy_name: str) -> dict:
        """Loads detection keywords from the central JSON configuration file.

        Args:
            strategy_name: The key for the specific strategy in the JSON config.

        Returns:
            A dictionary of keywords and selectors. Returns an empty structure
            if the file cannot be loaded, allowing for graceful failure.
        """
        try:
            with resources.open_text('auto_apply.evasion', 'detection_config.json') as f:
                return json.load(f)["strategies"][strategy_name]
        except (IOError, KeyError, json.JSONDecodeError):
            logger.error("Could not load detection_config.json. Detection will be unreliable.")
            return {"url_keywords": [], "title_keywords": [], "iframe_keywords": [], "text_keywords": [], "js_variables": []}

    def _check_url_and_title(self) -> bool:
        """Checks the page URL and title for known challenge-related keywords."""
        current_url = self.browser.current_url.lower()
        for keyword in self.config['url_keywords']:
            if keyword in current_url:
                logger.warning(f"Challenge Detected! Reason: URL keyword '{keyword}' found.")
                return True
        title = self.browser.title.lower()
        for keyword in self.config['title_keywords']:
            if keyword in title:
                logger.warning(f"Challenge Detected! Reason: Title keyword '{keyword}' found.")
                return True
        return False

    def _check_js_variables(self) -> bool:
        """Checks for tell-tale JavaScript variables created by CAPTCHA scripts."""
        for var in self.config['js_variables']:
            try:
                if self.browser.execute_script(f"return window.{var} ? true : false;"):
                    logger.warning(f"Challenge Detected! Reason: JavaScript variable 'window.{var}' found.")
                    return True
            except Exception:
                continue
        return False

    def _check_iframes(self) -> bool:
        """Checks for the presence of iframes from common CAPTCHA providers."""
        for keyword in self.config['iframe_keywords']:
            if self.browser.find_elements(By.XPATH, f"//iframe[contains(@src, '{keyword}')]"):
                logger.warning(f"Challenge Detected! Reason: iFrame with src containing '{keyword}' found.")
                return True
        return False

    def _perform_deep_scan(self) -> bool:
        """Performs a single, efficient XPath query to scan all visible text."""
        text_conditions = " or ".join([f"contains(., '{kw}')" for kw in self.config['text_keywords']])
        deep_scan_xpath = f"//body//*[not(self::script or self::style)][text()[{text_conditions}]]"
        try:
            if found_elements := self.browser.find_elements(By.XPATH, deep_scan_xpath):
                logger.warning(f"Challenge Detected! Reason: Found text on page matching keywords (e.g., '{found_elements[0].text[:50]}...').")
                return True
        except Exception:
            return False
        return False

    def is_challenge_present(self) -> bool:
        """Runs all configured checks in sequence.

        This method iterates through the list of check methods and returns
        True on the first positive detection (short-circuiting). This ensures
        efficiency by not running unnecessary checks.

        Returns:
            True if a challenge is detected, False otherwise.
        """
        logger.debug("Running DefaultDetectionStrategy...")
        try:
            for check_method in self.checks:
                if check_method():
                    return True
        except Exception as e:
            logger.warning(f"Error during challenge detection, assuming challenge is present: {e}")
            return True
        logger.debug("DefaultDetectionStrategy finished. No challenges detected.")
        return False

class CloudflareDetectionStrategy(DetectionStrategy):
    """A specialized strategy to detect Cloudflare's JavaScript challenges.

    This strategy looks for elements, titles, and iframes that are highly
    specific to Cloudflare's "I'm Under Attack Mode" or "Turnstile" pages,
    such as the "Just a moment..." title or the 'cf-spinner' element.
    """

    def is_challenge_present(self) -> bool:
        """Runs a series of checks highly specific to Cloudflare's layout.

        Returns:
            True if a Cloudflare challenge is detected, False otherwise.
        """
        try:
            title = self.browser.title.lower()
            if "just a moment" in title or "checking your browser" in title:
                return True

            spinner_xpath = "//*[contains(@class, 'cf-spinner') or contains(@class, 'cf-progress')]"
            if self.browser.find_elements(By.XPATH, spinner_xpath):
                return True

            turnstile_iframe_xpath = "//iframe[contains(@src, 'challenges.cloudflare.com/turnstile')]"
            if self.browser.find_elements(By.XPATH, turnstile_iframe_xpath):
                return True

        except Exception:
            return True

        return False