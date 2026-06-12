"""Adapter for Selenium WebDriver to conform to the BrowserInterface.

This module provides concrete implementations of the `BrowserInterface` and
`ElementInterface`, backed by the Selenium WebDriver library. It acts as a
translation layer, converting the framework-agnostic calls from the main
application logic into specific Selenium commands.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

# Selenium-specific imports are moved inside a lazy initialisation
# function to avoid hard dependency at module load time.
# All references to Selenium classes are replaced by globally cached
# variables that are populated the first time an adapter is instantiated.

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Keys as GenericKeys
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# Global placeholders – populated on first adapter creation
_SeleniumBy = None
_SeleniumKeys = None
_WebDriver = None
_WebElement = None
_ActionChains = None
_WebDriverWait = None
_EC = None
_TimeoutException = None
_WebDriverException = None
_LOCATOR_MAP = {}


def _ensure_selenium() -> None:
    """Import all required Selenium components and cache them in globals."""
    global _SeleniumBy, _SeleniumKeys, _WebDriver, _WebElement
    global _ActionChains, _WebDriverWait, _EC, _TimeoutException, _WebDriverException
    global _LOCATOR_MAP

    # Already initialised
    if _SeleniumBy is not None:
        return

    try:
        from selenium.common.exceptions import TimeoutException, WebDriverException  # noqa: E402
        from selenium.webdriver.common.action_chains import ActionChains  # noqa: E402
        from selenium.webdriver.common.by import By  # noqa: E402
        from selenium.webdriver.common.keys import Keys  # noqa: E402
        from selenium.webdriver.remote.webdriver import WebDriver  # noqa: E402
        from selenium.webdriver.remote.webelement import WebElement  # noqa: E402
        from selenium.webdriver.support import expected_conditions  # noqa: E402
        from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

        _TimeoutException = TimeoutException
        _WebDriverException = WebDriverException
        _ActionChains = ActionChains
        _SeleniumBy = By
        _SeleniumKeys = Keys
        _WebDriver = WebDriver
        _WebElement = WebElement
        _EC = expected_conditions
        _WebDriverWait = WebDriverWait

        _LOCATOR_MAP.update({
            Locator.ID: _SeleniumBy.ID,
            Locator.XPATH: _SeleniumBy.XPATH,
            Locator.LINK_TEXT: _SeleniumBy.LINK_TEXT,
            Locator.PARTIAL_LINK_TEXT: _SeleniumBy.PARTIAL_LINK_TEXT,
            Locator.NAME: _SeleniumBy.NAME,
            Locator.TAG_NAME: _SeleniumBy.TAG_NAME,
            Locator.CLASS_NAME: _SeleniumBy.CLASS_NAME,
            Locator.CSS_SELECTOR: _SeleniumBy.CSS_SELECTOR,
        })
        logger.info("Selenium dependencies loaded successfully.")
    except ImportError as e:
        logger.error("Failed to import Selenium: %s", e)
        raise


class SeleniumElementAdapter(ElementInterface):
    """Wraps a Selenium WebElement to conform to the ElementInterface contract."""

    def __init__(self, element: WebElement):
        """Initializes the adapter with a raw Selenium WebElement.

        Args:
            element (WebElement): The underlying Selenium WebElement to be managed.
        """
        _ensure_selenium()
        self._element = element

    def click(self) -> None:
        """Simulates a user click on the element."""
        self._element.click()

    def send_keys(self, text: str) -> None:
        """Simulates typing text into the element, handling special keys.

        Args:
            text (str): The string of text to be typed.
        """
        # Translation Map: Generic -> Selenium
        key_map = {
            GenericKeys.ENTER: _SeleniumKeys.ENTER,
            GenericKeys.RETURN: _SeleniumKeys.RETURN,
            GenericKeys.TAB: _SeleniumKeys.TAB,
            GenericKeys.ARROW_DOWN: _SeleniumKeys.ARROW_DOWN,
            GenericKeys.ARROW_UP: _SeleniumKeys.ARROW_UP,
            GenericKeys.ESCAPE: _SeleniumKeys.ESCAPE,
            GenericKeys.BACKSPACE: _SeleniumKeys.BACKSPACE,
            GenericKeys.SPACE: _SeleniumKeys.SPACE,
        }

        # Check if the input text is actually a special key constant
        if text in key_map:
            self._element.send_keys(key_map[text])
        else:
            self._element.send_keys(text)

    def get_attribute(self, name: str) -> str | None:
        """Retrieves the value of a specific HTML attribute.

        Args:
            name (str): The name of the attribute (e.g., 'href', 'class').

        Returns:
            Optional[str]: The value of the attribute, or None if it does not exist.
        """
        return self._element.get_attribute(name)

    @property
    def text(self) -> str:
        """Retrieves the visible text content of the element.

        Returns:
            str: The visible text, stripped of leading/trailing whitespace.
        """
        return self._element.text

    def get_location(self) -> tuple[int, int]:
        """Gets the (x, y) coordinates of the element's top-left corner.

        Returns:
            Tuple[int, int]: The x and y coordinates relative to the viewport.
        """
        loc = self._element.location
        return (int(loc['x']), int(loc['y']))

    def get_size(self) -> tuple[int, int]:
        """Gets the rendered dimensions of the element.

        Returns:
            Tuple[int, int]: The width and height in pixels.
        """
        size = self._element.size
        return (int(size['width']), int(size['height']))

    def get_shadow_root(self) -> Optional["ElementInterface"]:
        """Retrieves the shadow root of a web component, if it exists.

        Returns:
            Optional[ElementInterface]: An interface representing the root of the
                                        shadow DOM, or None if not present.
        """
        try:
            shadow_root = self._element.shadow_root
            if shadow_root:
                # In Selenium 4+, shadow_root returns a ShadowRoot object,
                # which acts very similar to a WebElement. We wrap it recursively.
                # Note: We cheat slightly here because ShadowRoot isn't exactly
                # a WebElement, but for find_element purposes, it behaves like one.
                return SeleniumElementAdapter(shadow_root)
        except _WebDriverException:
            pass
        return None

    def find_element(self, by: str, selector: str) -> Optional["ElementInterface"]:
        """Finds a single child element within this element's subtree.

        Args:
            by (str): The location strategy (from Locator).
            selector (str): The selector string.

        Returns:
            Optional[ElementInterface]: The found child element, or None if not found.
        """
        selenium_by = _LOCATOR_MAP.get(by)
        if not selenium_by:
            logger.error(f"Unsupported locator strategy: {by}")
            return None
        try:
            found = self._element.find_element(selenium_by, selector)
            return SeleniumElementAdapter(found)
        except Exception:
            return None

    def find_elements(self, by: str, selector: str) -> list["ElementInterface"]:
        """Finds all child elements within this element's subtree.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            List[ElementInterface]: A list of found child elements.
        """
        selenium_by = _LOCATOR_MAP.get(by)
        if not selenium_by:
            return []
        try:
            found_list = self._element.find_elements(selenium_by, selector)
            return [SeleniumElementAdapter(el) for el in found_list]
        except Exception:
            return []


class SeleniumAdapter(BrowserInterface):
    """Wraps a Selenium WebDriver instance to conform to the BrowserInterface."""

    def __init__(self, driver: WebDriver):
        """Initializes the adapter with a raw Selenium WebDriver instance.

        Args:
            driver (WebDriver): The underlying Selenium WebDriver to be managed.
        """
        _ensure_selenium()
        self._driver = driver

    @property
    def framework_name(self) -> str:
        """Returns the identifier of the underlying framework.

        Returns:
            str: 'selenium'
        """
        return "selenium"

    @property
    def title(self) -> str:
        """Returns the title of the current page.

        Returns:
            str: The page title.
        """
        return self._driver.title

    @property
    def current_url(self) -> str:
        """Returns the URL of the currently active page.

        Returns:
            str: The full URL string.
        """
        return self._driver.current_url

    @property
    def page_source(self) -> str:
        """Returns the full HTML source of the current page.

        Returns:
            str: The raw HTML string.
        """
        return self._driver.page_source

    def get(self, url: str) -> None:
        """Navigates the browser to the specified URL.

        Args:
            url (str): The fully qualified URL to visit.
        """
        self._driver.get(url)

    def close(self) -> None:
        """Closes the browser and releases all associated resources."""
        try:
            self._driver.quit()
        except Exception as e:
            logger.warning(f"Error closing Selenium driver: {e}")

    def back(self) -> None:
        """Navigates back one step in the browser's history."""
        self._driver.back()

    def _find_recursive_shadow(self, by: str, selector: str) -> WebElement | None:
        """Helper to find an element piercing through Shadow DOMs.

        Supports a custom syntax 'parent_selector >> child_selector'.

        Args:
            by (str): The locator strategy (must be CSS or XPATH for this logic).
            selector (str): The selector string, potentially with '>>'.

        Returns:
            Optional[WebElement]: The found raw element or None.
        """
        if ">>" not in selector:
            selenium_by = _LOCATOR_MAP.get(by)
            try:
                return self._driver.find_element(selenium_by, selector)
            except Exception:
                return None

        # Split the selector chain
        parts = [p.strip() for p in selector.split(">>")]
        current_context = self._driver

        try:
            for part in parts:
                # We assume CSS selector for shadow piercing as XPATH doesn't work well inside shadow roots  # noqa: E501
                element = current_context.find_element(_SeleniumBy.CSS_SELECTOR, part)
                # If this is not the last part, we need to enter its shadow root
                if part != parts[-1]:
                    shadow_root = element.shadow_root
                    if not shadow_root:
                        return None  # Chain broken
                    current_context = shadow_root
                else:
                    return element
        except Exception:
            return None
        return None

    def find_element(self, by: str, selector: str) -> ElementInterface | None:
        """Finds a single element in the current DOM.

        Args:
            by (str): The location strategy (Locator constant).
            selector (str): The selector string.

        Returns:
            Optional[ElementInterface]: The found element wrapper, or None.
        """
        # First, try the recursive logic if '>>' is present
        if ">>" in selector:
            raw_el = self._find_recursive_shadow(by, selector)
            return SeleniumElementAdapter(raw_el) if raw_el else None

        # Standard lookup
        selenium_by = _LOCATOR_MAP.get(by)
        if not selenium_by:
            logger.error(f"Unsupported locator: {by}")
            return None

        try:
            element = self._driver.find_element(selenium_by, selector)
            return SeleniumElementAdapter(element)
        except Exception:
            return None

    def find_elements(self, by: str, selector: str) -> list[ElementInterface]:
        """Finds all matching elements in the current DOM.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            List[ElementInterface]: A list of found element wrappers.
        """
        selenium_by = _LOCATOR_MAP.get(by)
        if not selenium_by:
            return []
        try:
            elements = self._driver.find_elements(selenium_by, selector)
            return [SeleniumElementAdapter(el) for el in elements]
        except Exception:
            return []

    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> ElementInterface | None:  # noqa: E501
        """Waits for an element to be present in the DOM.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.
            timeout (int): Maximum seconds to wait.

        Returns:
            Optional[ElementInterface]: The element if found within the timeout,
                                        otherwise None.
        """
        selenium_by = _LOCATOR_MAP.get(by)
        if not selenium_by:
            return None

        try:
            wait = _WebDriverWait(self._driver, timeout)
            element = wait.until(_EC.presence_of_element_located((selenium_by, selector)))  # noqa: E501
            return SeleniumElementAdapter(element)
        except _TimeoutException:
            return None

    def execute_script(self, script: str, *args: Any) -> Any:
        """Executes JavaScript in the context of the current page.

        Args:
            script (str): The JavaScript code to execute.
            *args (Any): Arguments. Wrappers are unwrapped to raw WebElements.

        Returns:
            Any: The script result.
        """
        # Unwrap adapters back to raw Selenium elements for the driver
        raw_args = []
        for arg in args:
            if isinstance(arg, SeleniumElementAdapter):
                raw_args.append(arg._element)
            else:
                raw_args.append(arg)

        return self._driver.execute_script(script, *raw_args)

    def switch_to_iframe(self, iframe_element: ElementInterface) -> None:
        """Switches the driver's context to a specific iframe.

        Args:
            iframe_element (ElementInterface): The iframe element wrapper.
        """
        if isinstance(iframe_element, SeleniumElementAdapter):
            self._driver.switch_to.frame(iframe_element._element)
        else:
            raise TypeError("Provided element is not a Selenium element")

    def switch_to_default_content(self) -> None:
        """Switches the driver's context back to the main page."""
        self._driver.switch_to.default_content()

    def get_cookies(self) -> list[dict]:
        """Retrieves all cookies from the current session.

        Returns:
            List[dict]: A list of cookie dictionaries.
        """
        return self._driver.get_cookies()

    def add_cookie(self, cookie: dict) -> None:
        """Adds a cookie to the current session.

        Args:
            cookie (dict): A dictionary representing the cookie.
        """
        self._driver.add_cookie(cookie)

    def scroll_by_offset(self, x: int, y: int) -> None:
        """Scrolls the viewport by a specific offset.

        Args:
            x (int): Horizontal pixels.
            y (int): Vertical pixels.
        """
        # Selenium's generic scroll is best handled via JS for reliability
        self._driver.execute_script(f"window.scrollBy({x}, {y});")

    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """Moves the mouse cursor relative to its current position.

        Args:
            x (int): Horizontal pixels.
            y (int): Vertical pixels.
        """
        _ActionChains(self._driver).move_by_offset(x, y).perform()

    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:  # noqa: E501
        """Moves the mouse cursor to the center of a specific element.

        Args:
            element (ElementInterface): The target element.
            offset_x (int): Horizontal offset.
            offset_y (int): Vertical offset.
        """
        if isinstance(element, SeleniumElementAdapter):
            _ActionChains(self._driver).move_to_element_with_offset(element._element, offset_x, offset_y).perform()  # noqa: E501

    def perform_mouse_fidget(self) -> None:
        """Performs a small, random mouse movement to simulate human 'jitter'."""
        x_move = random.randint(-5, 5)
        y_move = random.randint(-5, 5)
        try:
            _ActionChains(self._driver).move_by_offset(x_move, y_move).perform()
            # Move back slightly to avoid drifting off screen over time
            _ActionChains(self._driver).move_by_offset(-x_move, -y_move).perform()
        except Exception:
            pass  # Ignore movement errors (e.g., if mouse is out of bounds)

    def save_screenshot(self, filepath: str) -> None:
        """Saves a screenshot of the current viewport to a file.

        Args:
            filepath (str): The full path where the image should be saved.
        """
        self._driver.save_screenshot(filepath)

    def get_raw_driver(self) -> WebDriver:
        """Returns the underlying Selenium WebDriver.

        Crucial for Evasion strategies that need to access low-level
        properties (like CDP) not exposed by the generic interface.

        Returns:
            WebDriver: The raw Selenium driver instance.
        """
        return self._driver