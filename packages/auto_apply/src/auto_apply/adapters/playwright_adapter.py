"""Adapter for a Playwright Page to conform to the BrowserInterface.

This module provides concrete implementations of the BrowserInterface and
ElementInterface, backed by the Playwright library. It acts as a
translation layer, converting the framework-agnostic calls from the main
application logic into specific Playwright commands.
"""
import random
from playwright.sync_api import Page, Browser, Playwright
from typing import List, Optional, Tuple, Any

from ..core.browser_interface import BrowserInterface, ElementInterface
from selenium.webdriver.common.by import By

def _to_playwright_selector(by: str, selector: str) -> str:
    """Converts a standard 'By' strategy into a Playwright-compatible selector string.

    Playwright uses a powerful selector engine that often combines CSS and XPath
    locators into a single string. This helper function performs the necessary
    translation from our framework-agnostic 'by' strings.

    Args:
        by: The mechanism to find the element (e.g., By.ID, By.XPATH).
        selector: The value of the selector.

    Returns:
        A single selector string compatible with Playwright's `page.locator()`.

    Raises:
        ValueError: If the provided 'by' strategy is not supported.
    """
    if by == By.ID:
        return f"#{selector}"
    if by == By.CSS_SELECTOR:
        return selector
    if by == By.XPATH:
        return f"xpath={selector}"
    if by == By.NAME:
        return f"[name='{selector}']"
    if by == By.TAG_NAME:
        return selector
    if by == By.LINK_TEXT:
        return f"a:has-text(\"{selector}\")"

    raise ValueError(f"Playwright adapter does not yet support 'by' strategy: {by}")

class PlaywrightElementAdapter(ElementInterface):
    """Wraps a Playwright Locator to conform to the ElementInterface contract."""

    def __init__(self, element):
        """Initializes the adapter with a raw Playwright Locator.

        Args:
            element: The underlying Playwright Locator to be managed.
        """
        self._element = element

    def click(self) -> None:
        """Delegates the click action to the underlying Playwright Locator."""
        self._element.click()

    def send_keys(self, text: str) -> None:
        """Types text by delegating to the Locator's `type` method.

        Args:
            text: The text to be typed into the element.
        """
        self._element.type(text)

    def get_attribute(self, name: str) -> Optional[str]:
        """Delegates the get_attribute action to the underlying Locator.

        Args:
            name: The name of the attribute to retrieve.

        Returns:
            The attribute's value as a string, or None if not found.
        """
        return self._element.get_attribute(name)

    def get_location(self) -> Tuple[int, int]:
        """Gets the element's location using the Locator's `bounding_box`.

        Returns:
            A tuple containing the integer (x, y) coordinates.
        """
        box = self._element.bounding_box()
        return (box['x'], box['y'])

    def get_size(self) -> Tuple[int, int]:
        """Gets the element's size using the Locator's `bounding_box`.

        Returns:
            A tuple containing the integer (width, height).
        """
        box = self._element.bounding_box()
        return (box['width'], box['height'])

    @property
    def text(self) -> str:
        """str: The visible text of the underlying Locator."""
        return self._element.text_content()

    def find_element(self, by: str, selector: str) -> Optional[ElementInterface]:
        """Finds a single child element by chaining a new locator.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A new PlaywrightElementAdapter for the child, or None if not found.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            child_locator = self._element.locator(pw_selector).first
            if child_locator.is_visible():
                return PlaywrightElementAdapter(child_locator)
            return None
        except:
            return None

    def find_elements(self, by: str, selector: str) -> List[ElementInterface]:
        """Finds all child elements by chaining a new locator.

        Args:
            by: The mechanism to find the elements (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A list of PlaywrightElementAdapter instances for the found children.
        """
        pw_selector = _to_playwright_selector(by, selector)
        child_locators = self._element.locator(pw_selector).all()
        return [PlaywrightElementAdapter(loc) for loc in child_locators]

class PlaywrightAdapter(BrowserInterface):
    """Wraps a Playwright Page instance to conform to the BrowserInterface."""

    def __init__(self, page: Page, browser: Browser, playwright: Playwright):
        """Initializes the adapter with the core Playwright objects.

        This adapter takes ownership of the lifecycle of these objects.

        Args:
            page: The active Playwright Page to interact with.
            browser: The Playwright Browser instance the page belongs to.
            playwright: The root Playwright instance.
        """
        self._page = page
        self._browser = browser
        self._playwright = playwright

    @property
    def framework_name(self) -> str:
        """str: Returns the hardcoded string 'playwright' to identify the framework."""
        return "playwright"

    def get(self, url: str) -> None:
        """Navigates the page to the specified URL using `page.goto()`.

        Args:
            url: The URL to navigate to.
        """
        self._page.goto(url)

    def close(self) -> None:
        """Closes the browser and stops the root Playwright instance."""
        self._browser.close()
        self._playwright.stop()

    def find_element(self, by: str, selector: str) -> Optional[ElementInterface]:
        """Finds a single element using a translated Playwright selector.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A PlaywrightElementAdapter for the found element, or None if not found.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            element = self._page.locator(pw_selector).first
            if element.is_visible():
                 return PlaywrightElementAdapter(element)
            return None
        except:
            return None

    def find_elements(self, by: str, selector: str) -> List[ElementInterface]:
        """Finds all elements using a translated Playwright selector.

        Args:
            by: The mechanism to find the elements (e.g., 'id', 'css selector').
            selector: The selector's value.

        Returns:
            A list of PlaywrightElementAdapter instances for the found elements.
        """
        pw_selector = _to_playwright_selector(by, selector)
        elements = self._page.locator(pw_selector).all()
        return [PlaywrightElementAdapter(el) for el in elements]

    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> Optional[ElementInterface]:
        """Waits for an element using Playwright's built-in auto-waiting mechanism.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The selector's value.
            timeout: The maximum number of seconds to wait.

        Returns:
            A PlaywrightElementAdapter for the element, or None if it times out.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            locator = self._page.locator(pw_selector).first
            locator.wait_for(state="attached", timeout=timeout * 1000)
            return PlaywrightElementAdapter(locator)
        except Exception:
            return None

    def get_raw_page(self) -> Page:
        """
        Returns the underlying Playwright Page object for specific operations.
        (aka: Provides an 'escape hatch' to access the raw Playwright Page object.)

        This should be used sparingly for Playwright-specific features not
        in the BrowserInterface.

        Returns:
            The underlying Playwright Page instance.
        """
        return self._page

    def execute_script(self, script: str, *args) -> Any:
        """
        (Me: Executes JavaScript in the page context.
        This professional implementation correctly handles passing ElementInterface
        adapters into the script, where they become real DOM elements.)
        Executes JavaScript using `page.evaluate`, unwrapping custom element adapters.

        This implementation correctly handles passing PlaywrightElementAdapter
        objects into a script, where Playwright turns them into real DOM elements.

        Args:
            script: The JavaScript code to execute.
            *args: Arguments to pass to the script, including ElementInterface objects.

        Returns:
            The value returned by the JavaScript execution.
        """
        unwrapped_args = []
        for arg in args:
            if isinstance(arg, PlaywrightElementAdapter):
                unwrapped_args.append(arg._element)
            else:
                unwrapped_args.append(arg)

        js_function = f"function(args) {{ return (({', '.join(['arg' + str(i) for i in range(len(unwrapped_args))])}) => {{ {script} }})(...args) }}"

        return self._page.evaluate(js_function, unwrapped_args)

    def get_cookies(self) -> List[dict]:
        """Gets all cookies from the page's browser context."""
        return self._page.context.cookies()

    def add_cookie(self, cookie: dict) -> None:
        """Adds a single cookie to the page's browser context.

        Args:
            cookie: A dictionary representing the cookie to add.
        """
        self._page.context.add_cookies([cookie])

    def back(self) -> None:
        """Navigates back in history using `page.go_back()`."""
        self._page.go_back()

    def scroll_by_offset(self, x: int, y: int) -> None:
        """Scrolls the page using the virtual mouse wheel.

        Args:
            x: The horizontal pixel offset to scroll by.
            y: The vertical pixel offset to scroll by.
        """
        self._page.mouse.wheel(x, y)

    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """Moves the mouse relatively by getting the current position first.

        Args:
            x: The horizontal pixel offset to move by.
            y: The vertical pixel offset to move by.
        """
        current_pos = self._page.mouse.location
        self._page.mouse.move(current_pos['x'] + x, current_pos['y'] + y)

    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:
        """Moves the mouse to an element's bounding box center.

        Args:
            element: The target ElementInterface to move the mouse to.
            offset_x: An optional horizontal offset from the element's center.
            offset_y: An optional vertical offset from the element's center.
        """
        box = element._element.bounding_box()
        self._page.mouse.move(box['x'] + box['width'] / 2 + offset_x, box['y'] + box['height'] / 2 + offset_y)

    def perform_mouse_fidget(self) -> None:
        """Simulates a mouse wiggle by moving to a random nearby point and back."""
        pos = self._page.mouse.location
        x_move = random.randint(-5, 5)
        y_move = random.randint(-5, 5)
        self._page.mouse.move(pos['x'] + x_move, pos['y'] + y_move)
        self._page.mouse.move(pos['x'], pos['y'])

    def save_screenshot(self, filepath: str) -> None:
        """Saves a screenshot using `page.screenshot()`.

        Args:
            filepath: The path where the screenshot will be saved.
        """
        self._page.screenshot(path=filepath)

    @property
    def page_source(self) -> str:
        """str: The full HTML source of the current page via `page.content()`."""
        return self._page.content()

    @property
    def title(self) -> str:
        """str: The title of the current page via `page.title()`."""
        return self._page.title()

    @property
    def current_url(self) -> str:
        """str: The URL of the currently displayed page via `page.url`."""
        return self._page.url