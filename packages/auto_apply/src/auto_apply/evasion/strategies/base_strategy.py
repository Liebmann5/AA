"""Defines the abstract base class for a framework-specific Evasion Strategy.

This module contains the `EvasionStrategyInterface`, which acts as the
contract for all concrete evasion strategy implementations. By inheriting from
this class, each strategy (e.g., for Selenium or Playwright) is guaranteed
to have the same public methods, allowing the high-level application logic
to use them interchangeably.
"""
from abc import ABC, abstractmethod
from ...core.browser_interface import BrowserInterface
from ...config import EvasionSettings
from ..session import SessionManager
import logging

logger = logging.getLogger(__name__)

class EvasionStrategyInterface(ABC):
    """Abstract contract for all framework-specific evasion implementations."""

    def __init__(self, browser: BrowserInterface, settings: EvasionSettings, session: SessionManager):
        """Initializes the evasion strategy with the necessary context.

        Args:
            browser: The framework-agnostic browser adapter instance.
            settings: The application's evasion settings configuration.
            session: The current session manager for handling state.
        """
        self.browser = browser
        self.settings = settings
        self.session = session

    @abstractmethod
    def apply_static_evasion(self) -> None:
        """Applies framework-specific, static fingerprint modifications.

        This method should be called *before* navigating to the target website.
        It is responsible for injecting scripts or using browser-specific
        protocols (like CDP) to alter the browser's fingerprint before it can
        be detected. Examples include hiding the 'navigator.webdriver' flag or
        spoofing WebGL properties.
        """
        pass

    def manage_session_startup(self) -> None:
        """Performs session warmup routines or establishes a basic starting page.

        This method provides a generic, framework-agnostic implementation for
        session warming. If enabled in the settings, it uses the SessionManager
        to visit a series of benign websites to build a plausible browsing
        history and gather common cookies. If disabled, it performs a simple,
        single navigation to a safe page like google.com.

        Concrete strategies can override this method if they require a more
        specialized startup sequence.
        """
        if self.settings.enable_session_warming:
            self.session.intelligent_warmup(self.settings)
        else:
            logger.info("Session warming disabled. Performing simple startup navigation.")
            self.browser.get("https://www.google.com")