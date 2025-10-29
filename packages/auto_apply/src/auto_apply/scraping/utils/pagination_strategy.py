"""Provides a resilient, multi-strategy system for handling pagination.

This module contains the `PaginationStrategy` abstract base class and several
concrete implementations for common types of pagination controls found on websites.
This pattern allows the scraping logic to try different methods of finding and
clicking the "next page" element, making it highly resilient to variations in
website design.
"""
import logging
import time
from abc import ABC, abstractmethod
from selenium.webdriver.common.by import By
from ...core.browser_interface import BrowserInterface
from ...evasion import behavior

logger = logging.getLogger(__name__)

class PaginationStrategy(ABC):
    """The abstract base class (contract) for all pagination strategies."""

    def __init__(self, browser: BrowserInterface):
        """Initializes the pagination strategy.

        Args:
            browser: The framework-agnostic browser adapter instance.
        """
        self.browser = browser

    @abstractmethod
    def find_and_click(self) -> bool:
        """Attempts to find and click a pagination element using a specific strategy.

        This is the core method that must be implemented by all concrete subclasses.

        Returns:
            True if a "next page" element was successfully found and clicked,
            False otherwise.
        """
        pass

class KeywordPaginationStrategy(PaginationStrategy):
    """A strategy that handles simple, keyword-based pagination buttons.

    This strategy searches for buttons or links containing common "next" keywords
    like 'Next', 'More', 'Continue', etc.
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the keyword strategy with a predefined list of keywords."""
        super().__init__(browser)
        self.keywords = ['next', 'more', 'show more', 'continue']

    def find_and_click(self) -> bool:
        """Finds and clicks a button or link matching a keyword.

        This method uses a powerful XPath query that is resilient to changes in
        element tags (`<a>` or `<button>`), text case, and surrounding whitespace.

        Returns:
            True if a matching element was clicked, False otherwise.
        """
        xpath_template = "//a[normalize-space(lower-case(.))='{keyword}'] | //button[normalize-space(lower-case(.))='{keyword}']"

        for keyword in self.keywords:
            try:
                button = self.browser.find_element(By.XPATH, xpath_template.format(keyword=keyword))
                if button:
                    logger.info(f"Found keyword pagination button: '{keyword}'")
                    behavior.human_like_click(self.browser, button)
                    return True
            except Exception:
                continue
        return False

class NumberedPaginationStrategy(PaginationStrategy):
    """A strategy that handles numbered page lists (e.g., < 1 2 3 ... 10 >).

    This strategy requires access to a state manager to know which page number
    to look for next.
    """

    def __init__(self, browser: BrowserInterface, state_manager):
        """Initializes the numbered strategy.

        Args:
            browser: The framework-agnostic browser adapter instance.
            state_manager: An object that has a `current_page_number` attribute.
                This is used to determine the next page number to search for.
        """
        super().__init__(browser)
        self.state_manager = state_manager

    def find_and_click(self) -> bool:
        """Finds and clicks the link corresponding to the next page number.

        This method constructs a precise XPath query to find the link for the
        *next* page number (e.g., if on page 2, it looks for the link to page 3).
        Upon a successful click, it updates the state manager's page count.

        Returns:
            True if the next page link was clicked, False otherwise.
        """
        try:
            current_page = self.state_manager.current_page_number
            next_page_number = current_page + 1
            xpath = f"//a[normalize-space(.)='{next_page_number}' and @aria-label='Page {next_page_number}']"
            next_page_link = self.browser.find_element(By.XPATH, xpath)
            if next_page_link:
                logger.info(f"Found numbered pagination link for page {next_page_number}.")
                behavior.human_like_click(self.browser, next_page_link)
                self.state_manager.current_page_number = next_page_number
                return True
        except Exception:
            return False
        return False

class ArrowPaginationStrategy(PaginationStrategy):
    """A strategy that handles arrow-based buttons (e.g., > or >>).

    This strategy is highly effective on modern websites as it relies on
    stable, accessibility-focused `aria-label` attributes rather than visual
    text or icons.
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the arrow strategy with a list of common ARIA labels."""
        super().__init__(browser)
        self.aria_labels = ['Next page', 'Go to next page', 'Next']

    def find_and_click(self) -> bool:
        """Finds and clicks a button or link with a "Next" ARIA label.

        Returns:
            True if a matching element was clicked, False otherwise.
        """
        xpath_template = "//a[@aria-label='{label}'] | //button[@aria-label='{label}']"
        for label in self.aria_labels:
            try:
                button = self.browser.find_element(By.XPATH, xpath_template.format(label=label))
                if button:
                    logger.info(f"Found arrow pagination button with aria-label: '{label}'")
                    behavior.human_like_click(self.browser, button)
                    return True
            except Exception:
                continue
        return False