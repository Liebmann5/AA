"""Adapter for Selenium WebDriver to conform to the BrowserInterface.

This module provides concrete implementations of the BrowserInterface and
ElementInterface, backed by the Selenium WebDriver library. It acts as a
translation layer, converting the framework-agnostic calls from the main
application logic into specific Selenium commands.

It also includes the powerful `get_current_state` method for performing a
comprehensive digital identity audit.
"""
import logging
import random
import datetime
import requests
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By as SeleniumBy
from typing import Any, List, Optional, Tuple

from ..core.browser_interface import BrowserInterface, ElementInterface

logger = logging.getLogger(__name__)

BY_MAPPING = {
    "id": SeleniumBy.ID,
    "xpath": SeleniumBy.XPATH,
    "link text": SeleniumBy.LINK_TEXT,
    "partial link text": SeleniumBy.PARTIAL_LINK_TEXT,
    "name": SeleniumBy.NAME,
    "tag name": SeleniumBy.TAG_NAME,
    "class name": SeleniumBy.CLASS_NAME,
    "css selector": SeleniumBy.CSS_SELECTOR,
}

class SeleniumElementAdapter(ElementInterface):
    """Wraps a Selenium WebElement to conform to the ElementInterface contract."""

    def __init__(self, element: WebElement):
        """Initializes the adapter with a raw Selenium WebElement.

        Args:
            element: The underlying Selenium WebElement to be managed.
        """
        self._element = element

    def click(self) -> None:
        """Delegates the click action to the underlying Selenium WebElement."""
        self._element.click()

    def send_keys(self, text: str) -> None:
        """Delegates the send_keys action to the underlying WebElement.

        Args:
            text: The text to be typed into the element.
        """
        self._element.send_keys(text)

    def get_attribute(self, name: str) -> Optional[str]:
        """Delegates the get_attribute action to the underlying WebElement.

        Args:
            name: The name of the attribute to retrieve.

        Returns:
            The attribute's value as a string, or None if not found.
        """
        return self._element.get_attribute(name)

    def get_location(self) -> Tuple[int, int]:
        """Gets the element's location using the underlying WebElement.

        Returns:
            A tuple containing the integer (x, y) coordinates.
        """
        loc = self._element.location
        return (loc['x'], loc['y'])

    def get_size(self) -> Tuple[int, int]:
        """Gets the element's size using the underlying WebElement.

        Returns:
            A tuple containing the integer (width, height).
        """
        size = self._element.size
        return (size['width'], size['height'])

    @property
    def text(self) -> str:
        """str: The visible text of the underlying WebElement."""
        return self._element.text

    def find_element(self, by: str, selector: str) -> Optional[ElementInterface]:
        """Finds a single child element using the underlying WebElement.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A new SeleniumElementAdapter for the child element, or None if not found.
        """
        try:
            child_element = self._element.find_element(by, selector)
            return SeleniumElementAdapter(child_element)
        except:
            return None

    def find_elements(self, by: str, selector: str) -> List[ElementInterface]:
        """Finds all child elements using the underlying WebElement.

        Args:
            by: The mechanism to find the elements (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A list of SeleniumElementAdapter instances for the found child elements.
        """
        child_elements = self._element.find_elements(by, selector)
        return [SeleniumElementAdapter(el) for el in child_elements]

class SeleniumAdapter(BrowserInterface):
    """Wraps a Selenium WebDriver instance to conform to the BrowserInterface."""

    def __init__(self, driver: WebDriver):
        """Initializes the adapter with a raw Selenium WebDriver instance.

        Args:
            driver: The underlying Selenium WebDriver to be managed.
        """
        self._driver = driver

    @property
    def framework_name(self) -> str:
        """str: Returns the hardcoded string 'selenium' to identify the framework."""
        return "selenium"

    def get(self, url: str) -> None:
        """Navigates the managed browser to the specified URL.

        Args:
            url: The URL to navigate to.
        """
        self._driver.get(url)

    def close(self) -> None:
        """Closes the browser by calling the driver's quit() method."""
        self._driver.quit()

    def find_element(self, by: str, selector: str) -> Optional[ElementInterface]:
        """Finds a single element by translating the 'by' string to a Selenium By constant.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A SeleniumElementAdapter for the found element, or None if not found.

        Raises:
            ValueError: If the provided 'by' strategy is not supported.
        """
        selenium_by = BY_MAPPING.get(by)
        if not selenium_by:
            raise ValueError(f"Unsupported 'by' strategy: {by}")
        try:
            element = self._driver.find_element(selenium_by, selector)
            return SeleniumElementAdapter(element)
        except:
            return None

    def find_elements(self, by: str, selector: str) -> List[ElementInterface]:
        """Finds all elements by translating the 'by' string to a Selenium By constant.

        Args:
            by: The mechanism to find the elements (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A list of SeleniumElementAdapter instances for the found elements.

        Raises:
            ValueError: If the provided 'by' strategy is not supported.
        """
        selenium_by = BY_MAPPING.get(by)
        if not selenium_by:
            raise ValueError(f"Unsupported 'by' strategy: {by}")

        elements = self._driver.find_elements(selenium_by, selector)
        return [SeleniumElementAdapter(el) for el in elements]

    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> Optional[ElementInterface]:
        """Waits for an element using Selenium's WebDriverWait.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.
            timeout: The maximum number of seconds to wait.

        Returns:
            A SeleniumElementAdapter for the found element, or None if it times out.
        """
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException

        selenium_by = BY_MAPPING.get(by)
        if not selenium_by:
            raise ValueError(f"Unsupported 'by' strategy: {by}")

        try:
            wait = WebDriverWait(self._driver, timeout)
            raw_element = wait.until(EC.presence_of_element_located((selenium_by, selector)))
            return SeleniumElementAdapter(raw_element)
        except TimeoutException:
            return None

    def get_raw_driver(self) -> WebDriver:
        """
        This Returns the underlying Selenium WebDriver object for specific operations.
        Provides an 'escape hatch' to access the raw Selenium WebDriver object.

        This should be used sparingly, only when a feature specific to Selenium
        is required that is not available in the generic BrowserInterface.

        Returns:
            The underlying Selenium WebDriver instance.
        """
        return self._driver

    def execute_script(self, script: str, *args) -> Any:
        """Executes JavaScript, unwrapping custom element adapters to raw WebElements.

        This implementation correctly handles passing our SeleniumElementAdapter
        objects into a script, where they become real DOM elements.

        Args:
            script: The JavaScript code to execute.
            *args: Arguments to pass to the script, including ElementInterface objects.

        Returns:
            The value returned by the JavaScript execution.
        """
        raw_args = [arg._element if isinstance(arg, SeleniumElementAdapter) else arg for arg in args]
        return self._driver.execute_script(script, *raw_args)

    def get_cookies(self) -> List[dict]:
        """Gets all cookies by delegating to the Selenium driver's get_cookies method.

        Returns:
            A list of dictionaries, where each dictionary represents a cookie.
        """
        return self._driver.get_cookies()

    def add_cookie(self, cookie: dict) -> None:
        """Adds a single cookie by delegating to the Selenium driver's add_cookie method.

        Args:
            cookie: A dictionary representing the cookie to add.
        """
        self._driver.add_cookie(cookie)

    def back(self) -> None:
        """Navigates back in history by delegating to the Selenium driver's back method."""
        self._driver.back()

    def scroll_by_offset(self, x: int, y: int) -> None:
        """Scrolls the page by executing a 'window.scrollBy' JavaScript snippet.

        Args:
            x: The horizontal pixel offset to scroll by.
            y: The vertical pixel offset to scroll by.
        """
        self.execute_script(f"window.scrollBy({x}, {y});")

    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """Moves the mouse relatively using Selenium's ActionChains.

        Args:
            x: The horizontal pixel offset to move by.
            y: The vertical pixel offset to move by.
        """
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self._driver).move_by_offset(x, y).perform()

    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:
        """Moves the mouse to an element using Selenium's ActionChains.

        This method unwraps the provided ElementInterface to access the raw
        underlying WebElement required by ActionChains.

        Args:
            element: The target ElementInterface to move the mouse to.
            offset_x: An optional horizontal offset from the element's center.
            offset_y: An optional vertical offset from the element's center.
        """
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self._driver)
        actions.move_to_element(element._element).move_by_offset(offset_x, offset_y).perform()

    def perform_mouse_fidget(self) -> None:
        """Simulates a human-like mouse wiggle using Selenium's ActionChains.

        Performs a small, random, relative mouse movement and then returns to
        the original position.
        """
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self._driver)
        x_move = random.randint(-5, 5)
        y_move = random.randint(-5, 5)
        actions.move_by_offset(x_move, y_move).move_by_offset(-x_move, -y_move).perform()

    def save_screenshot(self, filepath: str) -> None:
        """Saves a screenshot by delegating to the Selenium driver's save_screenshot method.

        Args:
            filepath: The absolute or relative path where the screenshot will be saved.
        """
        self._driver.save_screenshot(filepath)

    @property
    def page_source(self) -> str:
        """str: The full HTML source of the current page."""
        return self._driver.page_source

    @property
    def title(self) -> str:
        """str: The title of the current page."""
        return self._driver.title

    @property
    def current_url(self) -> str:
        """str: The URL of the currently displayed page."""
        return self._driver.current_url