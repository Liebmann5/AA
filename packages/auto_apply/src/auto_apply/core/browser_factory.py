"""A registry-based meta-factory for creating browser driver adapters.

This module provides the primary entry point for the application to obtain a
browser instance. It uses a registry pattern to map framework names (e.g.,
"selenium") to their corresponding factory classes (e.g., SeleniumFactory).

This approach makes the system highly extensible; to support a new browser
automation framework, one only needs to create a new factory class and add it
to the FACTORY_REGISTRY.
"""
import logging
from typing import Dict, Type

from .proxy_manager import ProxyManager
from ..exceptions import BrowserSetupError


from .base_factory import BaseFactory
from .selenium_factory import SeleniumFactory
from .playwright_factory import PlaywrightFactory
# from .mobile_browser_factory import MobileBrowserFactory

from ..core.browser_interface import BrowserInterface

logger = logging.getLogger(__name__)

FACTORY_REGISTRY: Dict[str, Type[BaseFactory]] = {
    "selenium": SeleniumFactory,
    "playwright": PlaywrightFactory,
    # "mobile": MobileBrowserFactory,
}

def get_driver_adapter(
    framework: str,
    proxy_manager: ProxyManager = None,
    preferred_browser: str = "any"
) -> BrowserInterface:
    """Creates a browser adapter instance for the specified framework.

    This function acts as a meta-factory. It looks up the requested framework
    in the registry, instantiates the corresponding factory, and then uses that
    factory to create and return a fully configured browser adapter that conforms
    to the BrowserInterface.

    Args:
        framework: The name of the framework to use (e.g., "selenium").
        proxy_manager: An optional ProxyManager instance to configure proxies.
        preferred_browser: The specific browser the user wants (e.g., "chrome").
            This is passed down to the concrete factory.

    Returns:
        An initialized browser adapter that conforms to the BrowserInterface.

    Raises:
        BrowserSetupError: If the requested framework is not supported or if
            the concrete factory fails during browser initialization.
    """
    framework = framework.lower()
    logger.info("Attempting to create driver adapter using '%s' framework.", framework)

    factory_class = FACTORY_REGISTRY.get(framework)

    if not factory_class:
        logger.error(
            "No factory registered for framework: '%s'. Available frameworks: %s",
            framework, list(FACTORY_REGISTRY.keys())
        )
        raise BrowserSetupError(f"Framework '{framework}' is not supported.")

    try:
        factory_instance = factory_class(proxy_manager=proxy_manager)
        driver_adapter = factory_instance.get_driver(preferred_browser=preferred_browser)
        return driver_adapter
    except BrowserSetupError as e:
        logger.critical(
            "The '%s' factory failed to create a browser driver.", framework, exc_info=True
        )
        raise e