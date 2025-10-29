"""A factory for creating the appropriate, framework-specific Evasion Strategy.

This module provides the single, public entry point for the evasion system.
The `get_evasion_manager` function acts as a factory that embodies the
Strategy and Factory design patterns. It inspects the provided browser adapter
and returns the correct concrete strategy implementation, ensuring the rest of
the application remains decoupled from the specifics of any single evasion framework.
"""
import logging
from ..core.browser_interface import BrowserInterface
from ..config import EvasionSettings
from .session import SessionManager

from .strategies.base_strategy import EvasionStrategyInterface
from .strategies.selenium_strategy import SeleniumEvasionStrategy
from .strategies.playwright_strategy import PlaywrightEvasionStrategy

logger = logging.getLogger(__name__)

def get_evasion_manager(
    browser: BrowserInterface,
    settings: EvasionSettings,
    session: SessionManager
) -> EvasionStrategyInterface:
    """Factory function that returns the appropriate evasion strategy.

    This function inspects the browser adapter's `framework_name` property
    to determine which concrete evasion strategy to instantiate. This approach
    decouples the high-level workflow (which calls this function) from the
    low-level evasion implementations (e.g., Selenium-specific CDP commands),
    thus resolving potential circular import issues.

    Args:
        browser: The framework-agnostic browser adapter instance.
        settings: The application's evasion settings configuration.
        session: The current session manager for handling state.

    Returns:
        An instantiated, framework-specific evasion strategy that conforms to
        the `EvasionStrategyInterface` contract.

    Raises:
        NotImplementedError: If no evasion strategy has been implemented for
            the browser adapter's reported framework name.
    """
    logger.info("Selecting evasion strategy for framework: '%s'", browser.framework_name)

    if browser.framework_name == "selenium":
        return SeleniumEvasionStrategy(browser, settings, session)
    elif browser.framework_name == "playwright":
        return PlaywrightEvasionStrategy(browser, settings, session)
    else:
        raise NotImplementedError(f"No evasion strategy has been implemented for framework: {browser.framework_name}")