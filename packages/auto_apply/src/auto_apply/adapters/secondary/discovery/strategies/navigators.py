# File: adapters/discovery/strategies/navigators.py

"""Provides strategies for navigating to search results.

This module implements the Strategy Pattern for browser navigation. It decouples
the 'Provider' (Google/Bing) from the 'Method' (Direct URL vs Typing), and
provides a composite 'ResilientNavigator' to handle automatic fallbacks.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from urllib.parse import urlparse

from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.application.services.navigation.interruption import InterruptionHandler
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Keys, Locator

logger = logging.getLogger(__name__)


class NavigationStrategy(ABC):
    """Abstract base class for navigation behaviors."""

    def __init__(self, browser: BrowserInterface):
        self.browser = browser

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def navigate(self, url: str, context_data: dict = None) -> bool:
        """Executes the navigation logic.

        Args:
            url (str): The target URL.
            context_data (dict, optional): Extra data needed for human emulation.

        Returns:
            bool: True if technical navigation succeeded (page loaded), False otherwise.
        """
        ...


class DirectURLNavigation(NavigationStrategy):
    """Navigates directly to a constructed URL (Fastest, High Detectability)."""

    def navigate(self, url: str, context_data: dict = None) -> bool:
        logger.info(f"Navigating via {self.name}: {url}")
        try:
            self.browser.get(url)
            return True
        except Exception as e:
            logger.error(f"{self.name} failed: {e}")
            return False


class HumanSearchNavigation(NavigationStrategy):
    """Navigates to homepage, types query, and clicks search (Slowest, Low Detectability)."""  # noqa: E501

    def navigate(self, url: str, context_data: dict = None) -> bool:
        if not context_data or 'query' not in context_data:
            logger.warning(f"{self.name} requires 'query' in context_data.")
            return False

        # Extract homepage from full URL (e.g. https://google.com)
        parsed = urlparse(url)
        homepage = f"{parsed.scheme}://{parsed.netloc}"

        logger.info(f"Navigating via {self.name} to homepage: {homepage}")
        self.browser.get(homepage)
        time.sleep(2)

        # FIX: Clear cookie banners BEFORE trying to find/type in search bar
        InterruptionHandler(self.browser).handle_interruptions()

        try:
            # FIX: Bing/Google specific search bar heuristics
            # We look for inputs that are visible
            selectors = [
                "input[id*='search' i]",
                "input[name*='search' i]",
                "input[placeholder*='search' i]",
                "input[placeholder*='job' i]",
                "input[name*='keyword' i]",
                "input[name='q']",
                "input[type='search']",
                "textarea[name='q']",
                "[aria-label*='search' i]",
            ]

            search_input = None
            for sel in selectors:
                candidates = self.browser.find_elements(Locator.CSS_SELECTOR, sel)
                for cand in candidates:
                    try:
                        w, h = cand.get_size()
                        if w > 0 and h > 0:
                            search_input = cand
                            break
                    except Exception:
                        continue
                if search_input:
                    break

            if search_input:
                query_text = context_data.get('query')
                if 'location' in context_data:
                    query_text += f" in {context_data['location']}"

                logger.info(f"Typing query: {query_text}")

                # Click to focus
                search_input.click()
                time.sleep(0.2)

                behavior.human_like_typing(search_input, query_text)
                time.sleep(0.5)
                search_input.send_keys(Keys.ENTER)
                return True
            else:
                logger.warning("Could not find a visible search bar on the homepage.")

        except Exception as e:
            logger.warning(f"{self.name} failed: {e}")

        return False


class ResilientNavigator:
    """A composite navigator that attempts multiple strategies in sequence.

    This class implements the 'Fallback Pattern'. It attempts the fastest
    strategy first. If the resulting page fails a validation check (e.g. is blocked),
    it resets the browser state (clearing cookies) and tries the next strategy.
    """

    def __init__(self, browser: BrowserInterface, strategies: list[NavigationStrategy]):
        """Initializes the resilient navigator.

        Args:
            browser (BrowserInterface): The active browser.
            strategies (List[NavigationStrategy]): A prioritized list of strategies to try.
        """  # noqa: E501
        self.browser = browser
        self.strategies = strategies

    def navigate_with_fallback(
        self,
        url: str,
        context_data: dict,
        validator: Callable[[], bool]
    ) -> bool:
        """Attempts navigation using the defined strategies until one yields a valid page.

        Args:
            url (str): The target URL.
            context_data (dict): Context for human search (query, location).
            validator (Callable[[], bool]): A function that returns True if the
                page is healthy/safe, and False if blocked/broken.

        Returns:
            bool: True if a valid page was loaded, False if all strategies failed.
        """  # noqa: E501
        for i, strategy in enumerate(self.strategies):
            attempt_num = i + 1
            logger.info(f"ResilientNavigation: Attempt {attempt_num}/{len(self.strategies)} using {strategy.name}")  # noqa: E501

            # 1. Attempt Navigation
            success = strategy.navigate(url, context_data)

            # 2. If navigation command worked, check if the page is actually valid (not blocked)  # noqa: E501
            if success:
                # Give it a moment to settle/render before validation
                time.sleep(2)

                if validator():
                    logger.info(f"ResilientNavigation: {strategy.name} successful and validated.")  # noqa: E501
                    return True

                logger.warning(f"ResilientNavigation: {strategy.name} resulted in a blocked or invalid page.")  # noqa: E501

            # 3. FAILURE RECOVERY
            # If we failed and have more strategies to try, we must reset the environment.  # noqa: E501
            if attempt_num < len(self.strategies):
                logger.info("ResilientNavigation: Resetting browser state (Cookies/Storage) before next attempt...")  # noqa: E501
                try:
                    self.browser.get("about:blank")
                    # Note: Not all drivers support deleting cookies perfectly, but we try  # noqa: E501
                    # self.browser.delete_all_cookies()
                    # If using SeleniumAdapter, we can add delete_all_cookies to interface later  # noqa: E501
                except Exception as e:
                    logger.debug(f"Reset warning: {e}")

                time.sleep(1)

        logger.error("ResilientNavigation: All strategies exhausted. Query failed.")
        return False