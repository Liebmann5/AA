"""
Framework-agnostic system for detecting bot challenges.

This module combines:
1. A simple functional interface (`is_challenge_present`)
2. A flexible Strategy Pattern for advanced detection

It acts as the "eyes" of the evasion system and supports multiple
detection strategies (default, Cloudflare-specific, etc.).
"""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from importlib import resources

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# ============================================================
# Fallback / Baseline Keywords (used if config fails)
# ============================================================

BLOCK_TITLE_KEYWORDS = [
    "verify you are human",
    "just a moment",
    "access denied",
    "attention required",
    "security check",
    "are you a robot",
    "403 forbidden",
    "captcha"
]

BLOCK_URL_SUBSTRINGS = [
    "/challenge-platform/",
    "/recaptcha/",
    "geo.captcha-delivery.com"
]

# ============================================================
# Strategy Base Class
# ============================================================

class DetectionStrategy(ABC):
    """Abstract base class (contract) for challenge/detection strategies."""

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

# ============================================================
# Default Strategy (Primary System)
# ============================================================

class DefaultDetectionStrategy(DetectionStrategy):
    """
    Multi-vector detection strategy using weighted confidence scoring.
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the default strategy.

        This constructor loads the 'default' configuration from the JSON file
        and sets up weighted scoring vectors.

        Args:
            browser: A browser adapter that conforms to the BrowserInterface.
        """
        super().__init__(browser)
        self.config = self._load_config("default")
        self.threshold = self.config.get("threshold", 60)
        weights = self.config.get("weights", {})
        self.weights = {
            "url_keywords":   weights.get("url_keywords",   30),
            "title_keywords": weights.get("title_keywords", 30),
            "iframe_keywords":weights.get("iframe_keywords", 40),
            "text_keywords":  weights.get("text_keywords",  40),
            "js_variables":   weights.get("js_variables",    0),
        }

    # --------------------------------------------------------
    # Config Loader
    # --------------------------------------------------------

    def _load_config(self, strategy_name: str) -> dict:
        """Loads detection configuration from the central JSON file.

        Args:
            strategy_name: The key for the specific strategy in the JSON config.

        Returns:
            A dictionary of keywords and selectors. Returns a minimal structure
            if the file cannot be loaded, allowing graceful failure.
        """
        try:
            with resources.open_text("auto_apply.adapters.secondary.evasion", "detection_config.json") as f:  # noqa: E501
                return json.load(f)["strategies"][strategy_name]
        except Exception:
            logger.error("Failed to load detection_config.json, using fallback.")
            return {
                "threshold": 60,
                "weights": {
                    "url_keywords": 30,
                    "title_keywords": 30,
                    "iframe_keywords": 40,
                    "text_keywords": 40,
                    "js_variables": 0,
                },
                "url_keywords": BLOCK_URL_SUBSTRINGS,
                "title_keywords": BLOCK_TITLE_KEYWORDS,
                "iframe_keywords": ["recaptcha", "hcaptcha"],
                "text_keywords": BLOCK_TITLE_KEYWORDS,
                "js_variables": [],
            }

    # --------------------------------------------------------
    # Detection Checks
    # --------------------------------------------------------

    def _check_url_keywords(self) -> bool:
        """Checks the page URL for known challenge-related keywords."""
        try:
            url = self.browser.current_url.lower()
            for keyword in self.config["url_keywords"]:
                if keyword in url:
                    logger.warning(
                        "CAPTCHA signal: URL keyword '%s' found.", keyword
                    )
                    return True
        except Exception:
            pass
        return False

    def _check_title_keywords(self) -> bool:
        """Checks the page title for known challenge-related keywords."""
        try:
            title = self.browser.title.lower()
            for keyword in self.config["title_keywords"]:
                if keyword in title:
                    logger.warning(
                        "CAPTCHA signal: Title keyword '%s' found.", keyword
                    )
                    return True
        except Exception:
            pass
        return False

    def _check_js_variables(self) -> bool:
        """Checks for tell-tale JavaScript variables created by CAPTCHA scripts.

        Note: reCAPTCHA widgets are present on many normal pages (e.g. login modals),
        so the default weight for this vector is 0.  The configuration file must
        explicitly raise the weight if this signal is intended to be used.
        """
        for var in self.config.get("js_variables", []):
            try:
                if self.browser.execute_script(f"return window.{var} ? true : false;"):
                    logger.warning(
                        "CAPTCHA signal: JS variable 'window.%s' found.", var
                    )
                    return True
            except Exception:
                continue
        return False

    def _check_iframes(self) -> bool:
        """Checks for the presence of iframes from common CAPTCHA providers."""
        try:
            for keyword in self.config.get("iframe_keywords", []):
                if self.browser.find_elements(
                    Locator.XPATH, f"//iframe[contains(@src, '{keyword}')]"
                ):
                    logger.warning(
                        "CAPTCHA signal: iframe with src containing '%s' found.", keyword
                    )
                    return True
        except Exception:
            pass
        return False

    def _perform_deep_scan(self) -> bool:
        """Performs a single, efficient XPath query to scan all visible text."""
        text_conditions = " or ".join(
            [f"contains(., '{kw}')" for kw in self.config.get("text_keywords", [])]
        )
        deep_scan_xpath = (
            f"//body//*[not(self::script or self::style)][text()[{text_conditions}]]"
        )
        try:
            elements = self.browser.find_elements(Locator.XPATH, deep_scan_xpath)
            if elements:
                logger.warning(
                    "CAPTCHA signal: Found text on page matching keywords (e.g., '%s...').",
                    elements[0].text[:50],
                )
                return True
        except Exception:
            pass
        return False

    # --------------------------------------------------------
    # Weighted confidence evaluation
    # --------------------------------------------------------

    def is_challenge_present(self) -> bool:
        """Runs all configured checks and returns True only when the weighted
        confidence exceeds the threshold.

        This prevents false positives caused by CAPTCHA widgets that are
        present on normal pages (e.g. login modals on Indeed).
        """
        logger.debug("Running DefaultDetectionStrategy...")
        try:
            confidence = 0

            if self.weights.get("url_keywords", 0) > 0 and self._check_url_keywords():
                confidence += self.weights["url_keywords"]

            if self.weights.get("title_keywords", 0) > 0 and self._check_title_keywords():
                confidence += self.weights["title_keywords"]

            if self.weights.get("iframe_keywords", 0) > 0 and self._check_iframes():
                confidence += self.weights["iframe_keywords"]

            if self.weights.get("text_keywords", 0) > 0 and self._perform_deep_scan():
                confidence += self.weights["text_keywords"]

            if self.weights.get("js_variables", 0) > 0 and self._check_js_variables():
                confidence += self.weights["js_variables"]

            logger.debug(
                "CAPTCHA confidence: %d / threshold %d", confidence, self.threshold
            )
            return confidence >= self.threshold

        except Exception as e:
            logger.warning(
                "Error during challenge detection, assuming challenge is present: %s", e
            )
            return True

# ============================================================
# Cloudflare Specialized Strategy
# ============================================================

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

            spinner_xpath = "//*[contains(@class, 'cf-spinner') or contains(@class, 'cf-progress')]"  # noqa: E501
            if self.browser.find_elements(Locator.XPATH, spinner_xpath):
                return True

            turnstile_iframe_xpath = "//iframe[contains(@src, 'challenges.cloudflare.com/turnstile')]"  # noqa: E501
            if self.browser.find_elements(Locator.XPATH, turnstile_iframe_xpath):
                return True

        except Exception:
            return True

        return False

# ============================================================
# Simple Functional Interface (Backward Compatibility)
# ============================================================

def is_challenge_present(browser: BrowserInterface) -> bool:
    """
    Simple entrypoint for detection.

    Uses DefaultDetectionStrategy internally.
    """
    strategy = DefaultDetectionStrategy(browser)
    return strategy.is_challenge_present()