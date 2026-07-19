"""
Evasion techniques specifically implemented for Playwright.
"""
import logging

from .. import fingerprint_js
from .base import EvasionStrategyInterface

logger = logging.getLogger(__name__)

class PlaywrightEvasionStrategy(EvasionStrategyInterface):
    def apply_static_evasion(self):
        """Applies fingerprint modifications for Playwright browsers."""
        logger.info("Applying static Playwright evasion tactics.")

        try:
            raw_page = self.browser.get_raw_page()
        except AttributeError:
            logger.warning("The provided browser adapter does not have 'get_raw_page'. Skipping Playwright evasions.")  # noqa: E501
            return

        if self.settings.enable_fingerprint_spoofing:
            js_payload = fingerprint_js.get_js_payload(self.settings)
            raw_page.add_init_script(js_payload)
            logger.info("Successfully injected JavaScript payload for fingerprinting defense.")  # noqa: E501