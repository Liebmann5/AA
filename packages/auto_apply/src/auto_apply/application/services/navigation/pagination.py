"""Provides a resilient, multi-strategy system for handling pagination.

This module contains strategies for finding and clicking 'Next Page' controls.
It is robust against different website styles (Infinite Scroll, Numbered Lists,
Arrow Buttons) and integrates with InteractionPort to click naturally.
"""
# Layer: application
# Depends on: domain

import logging
import time
from abc import ABC, abstractmethod

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.interaction_port import InteractionPort
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

class PaginationStrategy(ABC):
    """The abstract base class (contract) for all pagination strategies."""

    def __init__(self, browser: BrowserInterface, interactor: InteractionPort | None = None):
        """Initializes the pagination strategy.

        Args:
            browser: The framework-agnostic browser adapter instance.
            interactor: Port for human-like interaction and pacing. Optional for
                        scroll-based strategies that operate entirely via JavaScript
                        and do not click DOM elements.
        """
        self.browser = browser
        self._interactor = interactor

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def next_page(self) -> bool:
        """Attempts to navigate to the next page of results.

        Returns:
            bool: True if navigation was triggered successfully.
                  False if the end of the list was reached or navigation failed.
        """
        ...

class KeywordPagination(PaginationStrategy):
    """A strategy that handles simple, keyword-based pagination buttons.

    This strategy searches for buttons or links containing common "next" keywords
    like 'Next', 'More', 'Continue', etc.
    """

    def __init__(self, browser: BrowserInterface, interactor: InteractionPort):
        """Initializes the keyword strategy with a predefined list of keywords."""
        super().__init__(browser, interactor)
        self.keywords = ['next', 'more', 'show more', 'continue', 'load more']

    def next_page(self) -> bool:
        """Scans for buttons with specific keywords."""
        xpath_template = (
            "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')] | "  # noqa: E501
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{kw}')]"  # noqa: E501
        )

        for keyword in self.keywords:
            try:
                xpath = xpath_template.format(kw=keyword)
                elements = self.browser.find_elements(Locator.XPATH, xpath)

                if elements:
                    target = elements[-1]
                    logger.info(f"{self.name}: Clicking '{keyword}' button.")
                    self._interactor.click(target)
                    return True
            except Exception:
                continue

        return False

class NumberedPagination(PaginationStrategy):
    """Handles numbered lists (1, 2, 3...) by finding the *current* page + 1."""

    def __init__(
        self,
        browser: BrowserInterface,
        interactor: InteractionPort,
        state_manager: object = None,
    ):
        """Initializes the numbered strategy."""
        super().__init__(browser, interactor)
        self.current_page = 1

    def next_page(self) -> bool:
        """Finds the link for (current_page + 1)."""
        next_target = self.current_page + 1
        logger.debug(f"{self.name}: Looking for page {next_target}...")

        try:
            xpath = f"//a[normalize-space()='{next_target}'] | //button[normalize-space()='{next_target}']"  # noqa: E501
            elements = self.browser.find_elements(Locator.XPATH, xpath)

            if not elements:
                aria_xpath = f"//*[@aria-label='Page {next_target}']"
                elements = self.browser.find_elements(Locator.XPATH, aria_xpath)

            if elements:
                target = elements[0]
                self._interactor.click(target)
                self.current_page += 1
                return True

        except Exception:
            pass

        return False

class ArrowPagination(PaginationStrategy):
    """
    A strategy that handles arrow-based buttons (e.g., > or >>) and those
    identified by ARIA labels (e.g., 'Next Page').

    This strategy is highly effective on modern websites as it relies on
    stable, accessibility-focused `aria-label` attributes rather than visual
    text or icons.
    """

    def __init__(self, browser: BrowserInterface, interactor: InteractionPort):
        """Initializes the arrow strategy with a list of common ARIA labels."""
        super().__init__(browser, interactor)
        self.aria_labels = ['next page', 'go to next page', 'next', 'pagination next']

    def next_page(self) -> bool:
        """Scans for elements with specific aria-labels."""
        for label in self.aria_labels:
            try:
                selector = f"[aria-label*='{label}']"
                elements = self.browser.find_elements(Locator.CSS_SELECTOR, selector)

                if elements:
                    target = elements[-1]
                    logger.info(f"{self.name}: Clicking ARIA label '{label}'.")
                    self._interactor.click(target)
                    return True
            except Exception:
                continue
        return False


class InfiniteScrollStrategy(PaginationStrategy):
    """
    Handles 'Endless Scroll' pages (LinkedIn Feed, Google Jobs Widget).
    It scrolls down and checks if the DOM height increased.
    """

    def next_page(self) -> bool:
        """
        Scrolls down and waits to see if new content loads.
        Returns:
            True if the page grew (new content loaded).
            False if we hit the bottom and nothing happened.
        """
        prev_height = self.browser.execute_script("return document.body.scrollHeight")

        self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        time.sleep(2.0)

        new_height = self.browser.execute_script("return document.body.scrollHeight")

        return new_height > prev_height

class PaginationHandler:
    """Orchestrates multiple pagination strategies for robust page navigation."""

    def __init__(self, browser: BrowserInterface, interactor: InteractionPort):
        self.browser = browser
        self.strategies = [
            KeywordPagination(browser, interactor),
            ArrowPagination(browser, interactor),
            NumberedPagination(browser, interactor),
            InfiniteScrollStrategy(browser, interactor),
        ]

    def navigate_to_next_page(self) -> bool:
        """Attempts to navigate to the next page using available strategies.

        Returns:
            bool: True if any strategy successfully navigated to the next page.
        """
        for strategy in self.strategies:
            try:
                if strategy.next_page():
                    logger.info(f"Successfully navigated using {strategy.name}")
                    return True
            except Exception as e:
                logger.debug(f"Strategy {strategy.name} failed: {e}")
                continue

        logger.info("All pagination strategies failed - likely at end of results")
        return False
