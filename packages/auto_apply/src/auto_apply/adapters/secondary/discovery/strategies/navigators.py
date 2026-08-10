"""Provides strategies for navigating to search results.

This module implements the Strategy Pattern for browser navigation. It decouples
the 'Provider' (Google/Bing) from the 'Method' (Direct URL vs Typing), and
provides a composite 'ResilientNavigator' to handle automatic fallbacks.

The navigator now receives a ``SearchEngineStrategy`` + ``SearchInstruction``
instead of a pre‑built URL.  This lets each navigation strategy use the
engine‑specific knowledge (homepage URL, search bar selectors) encapsulated
in the strategy, while the provider remains a pure scraping executor.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    SearchEngineStrategy,
)
from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.adapters.secondary.navigation.interruption import InterruptionHandler
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import Keys, Locator

logger = logging.getLogger(__name__)


class NavigationStrategy(ABC):
    """Abstract base class for navigation behaviors.

    Each concrete strategy receives a ``SearchEngineStrategy`` (which knows
    engine‑specific details like homepage URL and search bar selectors) and a
    ``SearchInstruction`` (the user's query parameters).  The strategy returns
    ``True`` if the technical navigation succeeded (page loaded or search
    submitted).
    """

    def __init__(self, browser: BrowserInterface) -> None:
        self.browser = browser

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def navigate(
        self,
        engine_strategy: SearchEngineStrategy,
        instruction: SearchInstruction,
    ) -> bool:
        """Execute the navigation logic.

        Args:
            engine_strategy: The search‑engine‑specific strategy (Google, Bing,
                Indeed) that provides ``homepage_url``, ``build_search_url()``,
                and ``search_bar_selectors``.
            instruction: The typed search instruction (title, location,
                date_range, etc.).

        Returns:
            ``True`` if navigation succeeded, ``False`` otherwise.
        """
        ...


class DirectURLNavigation(NavigationStrategy):
    """Navigates directly to a constructed URL (Fastest, High Detectability)."""

    def navigate(
        self,
        engine_strategy: SearchEngineStrategy,
        instruction: SearchInstruction,
    ) -> bool:
        url = engine_strategy.build_search_url(instruction)
        logger.info("Navigating via %s: %s", self.name, url)
        try:
            self.browser.get(url)
            return True
        except Exception as exc:
            logger.error("%s failed: %s", self.name, exc)
            return False


class HumanSearchNavigation(NavigationStrategy):
    """Navigates to homepage, types query, and clicks search (Slowest, Low Detectability).

    Uses the engine strategy's ``homepage_url`` and ``search_bar_selectors``
    so that no engine‑specific knowledge is hardcoded here.
    """

    def navigate(
        self,
        engine_strategy: SearchEngineStrategy,
        instruction: SearchInstruction,
    ) -> bool:
        homepage = engine_strategy.homepage_url

        logger.info(
            "Navigating via %s to homepage: %s", self.name, homepage
        )
        self.browser.get(homepage)
        time.sleep(2)

        # Clear cookie banners BEFORE trying to find/type in search bar.
        InterruptionHandler(self.browser).handle_interruptions()

        try:
            selectors = engine_strategy.search_bar_selectors
            search_input = None

            for sel in selectors:
                candidates = self.browser.find_elements(
                    Locator.CSS_SELECTOR, sel
                )
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
                query_text = instruction.effective_query
                if instruction.location:
                    query_text += f" in {instruction.location}"

                logger.info("Typing query: %s", query_text)

                # Click to focus
                search_input.click()
                time.sleep(0.2)

                behavior.human_like_typing(search_input, query_text)
                time.sleep(0.5)
                search_input.send_keys(Keys.ENTER)
                return True
            else:
                logger.warning(
                    "Could not find a visible search bar on the homepage "
                    "for engine=%s",
                    engine_strategy.engine_name,
                )

        except Exception as exc:
            logger.warning("%s failed: %s", self.name, exc)

        return False


class ResilientNavigator:
    """A composite navigator that attempts multiple strategies in sequence.

    This class implements the 'Fallback Pattern'. It attempts the fastest
    strategy first. If the resulting page fails a validation check (e.g. is
    blocked), it resets the browser state (clearing cookies) and tries the
    next strategy.

    The navigator now receives a ``SearchEngineStrategy`` + ``SearchInstruction``
    instead of a pre‑built URL.  This eliminates URL‑construction logic from
    providers and makes toolbar interactions a separate, post‑navigation step.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        strategies: list[NavigationStrategy],
    ) -> None:
        """Initializes the resilient navigator.

        Args:
            browser: The active browser.
            strategies: A prioritized list of strategies to try.
        """
        self.browser = browser
        self.strategies = strategies

    def navigate_with_fallback(
        self,
        engine_strategy: SearchEngineStrategy,
        instruction: SearchInstruction,
        validator: Callable[[], bool],
    ) -> bool:
        """Attempts navigation using the defined strategies until one yields a valid page.

        Args:
            engine_strategy: The search‑engine‑specific strategy that provides
                URL construction, homepage URL, and toolbar interactions.
            instruction: The typed search instruction.
            validator: A function that returns ``True`` if the page is
                healthy/safe, and ``False`` if blocked/broken.

        Returns:
            ``True`` if a valid page was loaded, ``False`` if all strategies
            failed.
        """
        for i, strategy in enumerate(self.strategies):
            attempt_num = i + 1
            logger.info(
                "ResilientNavigation: Attempt %d/%d using %s",
                attempt_num,
                len(self.strategies),
                strategy.name,
            )

            # 1. Attempt Navigation
            success = strategy.navigate(engine_strategy, instruction)

            # 2. If navigation command worked, check if the page is actually
            #    valid (not blocked).
            if success:
                # Give it a moment to settle/render before validation.
                time.sleep(2)

                if validator():
                    logger.info(
                        "ResilientNavigation: %s successful and validated.",
                        strategy.name,
                    )
                    return True

                logger.warning(
                    "ResilientNavigation: %s resulted in a blocked or invalid page.",
                    strategy.name,
                )

            # 3. FAILURE RECOVERY
            # If we failed and have more strategies to try, reset the
            # environment.
            if attempt_num < len(self.strategies):
                logger.info(
                    "ResilientNavigation: Resetting browser state "
                    "(Cookies/Storage) before next attempt..."
                )
                try:
                    self.browser.get("about:blank")
                except Exception as exc:
                    logger.debug("Reset warning: %s", exc)

                time.sleep(1)

        logger.error(
            "ResilientNavigation: All strategies exhausted. Query failed."
        )
        return False