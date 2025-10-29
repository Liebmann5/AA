"""A factory to select the appropriate application strategy based on the job URL.

This module provides the `get_application_strategy` function, which acts as a
factory for creating concrete `ApplicationStrategy` instances. It uses a
registry pattern (`STRATEGY_MAPPING`) to associate URL identifiers (like
'boards.greenhouse.io') with the specific strategy class designed to handle
that platform.
"""
import logging
from typing import Type, Optional
from selenium.webdriver.remote.webdriver import WebDriver

from .base_application_strategy import ApplicationStrategy
from .greenhouse_strategy import GreenhouseStrategy
from .lever_strategy import LeverStrategy

from ...user_data.user_profile import UserProfile
from ...scraping.search.search_result import SearchResult

logger = logging.getLogger(__name__)

STRATEGY_MAPPING = {
    "boards.greenhouse.io": GreenhouseStrategy,
    "jobs.lever.co": LeverStrategy,
}

def get_application_strategy(
    driver: WebDriver,
    user_profile: UserProfile,
    job: SearchResult
) -> Optional[ApplicationStrategy]:
    """Factory function to select and instantiate the correct application strategy.

    This function inspects the provided job's URL and compares it against the
    identifiers in the `STRATEGY_MAPPING` registry. If a match is found, it
    instantiates the corresponding strategy class with the necessary context
    (driver, profile, and job) and returns it.

    Args:
        driver: The Selenium WebDriver instance for the application browser.
        user_profile: The user's complete profile data.
        job: The `SearchResult` object for the job to be applied for.

    Returns:
        An instantiated `ApplicationStrategy` object if a matching strategy
        is found for the job's URL, otherwise returns None.
    """
    job_url = job.url.lower()

    for identifier, strategy_class in STRATEGY_MAPPING.items():
        if identifier in job_url:
            logger.info("Found matching strategy '%s' for URL: %s", strategy_class.__name__, job.url)
            return strategy_class(driver, user_profile, job)

    logger.warning("No suitable application strategy found for URL: %s", job.url)
    return None