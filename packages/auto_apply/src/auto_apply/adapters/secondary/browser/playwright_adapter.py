"""Adapter for Playwright Page to conform to the BrowserInterface.

This module provides concrete implementations of the `BrowserInterface` and
`ElementInterface`, backed by the Playwright library. It handles the translation
of locators and manages the Page/Context lifecycle.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

# Playwright-specific imports are moved inside a lazy initialisation
# function to avoid hard dependency at module load time.
# All references to Playwright classes are replaced by globally cached
# variables that are populated the first time an adapter is instantiated.

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Keys as GenericKeys
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

# Global placeholders – populated on first adapter creation
_Playwright = None
_PwBrowser = None
_Page = None
_PlaywrightLocator = None


def _ensure_playwright() -> None:
    """Import all required Playwright components and cache them in globals."""
    global _Playwright, _PwBrowser, _Page, _PlaywrightLocator

    # Already initialised
    if _Playwright is not None:
        return

    try:
        import playwright.sync_api as _pw_sync  # noqa: E402

        _PwBrowser = _pw_sync.Browser
        _PlaywrightLocator = _pw_sync.Locator
        _Page = _pw_sync.Page
        _Playwright = _pw_sync.Playwright
        logger.info("Playwright dependencies loaded successfully.")
    except ImportError as e:
        logger.error("Failed to import Playwright: %s", e)
        raise


def _to_playwright_selector(by: str, selector: str) -> str:
    """Converts a generic Locator constant into a Playwright selector string.

    Args:
        by (str): The generic locator strategy (e.g., Locator.ID).
        selector (str): The value of the selector.

    Returns:
        str: A selector string compatible with Playwright (e.g., '#myId').

    Raises:
        ValueError: If the locator strategy is not supported.
    """
    if by == Locator.ID:
        return f"#{selector}"
    if by == Locator.CSS_SELECTOR:
        return selector
    if by == Locator.XPATH:
        if selector.startswith("xpath="):
            return selector
        return f"xpath={selector}"
    if by == Locator.NAME:
        return f"[name='{selector}']"
    if by == Locator.TAG_NAME:
        return f"{selector}"
    if by == Locator.CLASS_NAME:
        return f".{selector}"
    if by == Locator.LINK_TEXT:
        return f"text='{selector}'"
    if by == Locator.PARTIAL_LINK_TEXT:
        return f"text=/{selector}/i"  # Case-insensitive partial match regex

    raise ValueError(f"Playwright adapter does not support strategy: {by}")


class PlaywrightElementAdapter(ElementInterface):
    """Wraps a Playwright Locator to conform to the ElementInterface contract."""

    def __init__(self, locator: PlaywrightLocator):
        """Initializes the adapter with a raw Playwright Locator.

        Args:
            locator (PlaywrightLocator): The underlying Locator object.
        """
        _ensure_playwright()
        self._locator = locator

    def click(self) -> None:
        """Simulates a user click on the element."""
        self._locator.click()

    def send_keys(self, text: str) -> None:
        """Simulates typing text into the element or pressing keys.

        Args:
            text (str): The string of text to be typed.
        """
        # Translation Map: Generic -> Playwright String Codes
        key_map = {
            GenericKeys.ENTER: "Enter",
            GenericKeys.RETURN: "Enter",
            GenericKeys.TAB: "Tab",
            GenericKeys.ARROW_DOWN: "ArrowDown",
            GenericKeys.ARROW_UP: "ArrowUp",
            GenericKeys.ESCAPE: "Escape",
            GenericKeys.BACKSPACE: "Backspace",
            GenericKeys.SPACE: "Space",
        }

        if text in key_map:
            # Playwright uses .press() for special keys
            self._locator.press(key_map[text])
        else:
            # Playwright uses .fill() for text entry (it clears and types fast)
            # OR .type() for character-by-character typing.
            # We use type() here to match the behavior expected by 'human_like_typing'
            self._locator.type(text)

    def get_attribute(self, name: str) -> str | None:
        """Retrieves the value of a specific HTML attribute.

        Args:
            name (str): The name of the attribute.

        Returns:
            Optional[str]: The value, or None if not found.
        """
        return self._locator.get_attribute(name)

    @property
    def text(self) -> str:
        """Retrieves the visible text content of the element.

        Returns:
            str: The visible text.
        """
        return self._locator.text_content() or ""

    def get_location(self) -> tuple[int, int]:
        """Gets the (x, y) coordinates of the element's top-left corner.

        Returns:
            Tuple[int, int]: The x and y coordinates.
        """
        box = self._locator.bounding_box()
        if box:
            return (int(box['x']), int(box['y']))
        return (0, 0)

    def get_size(self) -> tuple[int, int]:
        """Gets the rendered dimensions of the element.

        Returns:
            Tuple[int, int]: The width and height.
        """
        box = self._locator.bounding_box()
        if box:
            return (int(box['width']), int(box['height']))
        return (0, 0)

    def get_shadow_root(self) -> Optional["ElementInterface"]:
        """Retrieves the shadow root (Not strictly applicable in Playwright).

        Playwright handles shadow DOM automatically (piercing by default), so
        explicitly getting the shadow root is rarely needed. However, to satisfy
        the interface, we return None as Playwright abstracts this away.

        Returns:
            None: Playwright auto-pierces Shadow DOM.
        """
        return None

    def find_element(self, by: str, selector: str) -> Optional["ElementInterface"]:
        """Finds a single child element within this element's subtree.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            Optional[ElementInterface]: The found child, or None.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            # We use .first to get a single specific handle if multiple match
            child = self._locator.locator(pw_selector).first
            # count() is fast check if it exists
            if child.count() > 0:
                return PlaywrightElementAdapter(child)
        except Exception:
            pass
        return None

    def find_elements(self, by: str, selector: str) -> list["ElementInterface"]:
        """Finds all child elements within this element's subtree.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            List[ElementInterface]: A list of found children.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            children = self._locator.locator(pw_selector).all()
            return [PlaywrightElementAdapter(child) for child in children]
        except Exception:
            return []


class PlaywrightAdapter(BrowserInterface):
    """Wraps a Playwright Page instance to conform to the BrowserInterface."""

    def __init__(self, page: Page, browser: Browser, playwright: Playwright):
        """Initializes the adapter with Playwright objects.

        Args:
            page (Page): The active Playwright Page.
            browser (Browser): The Browser instance.
            playwright (Playwright): The root Playwright object (for cleanup).
        """
        _ensure_playwright()
        self._page = page
        self._browser = browser
        self._playwright = playwright

    @property
    def framework_name(self) -> str:
        """Returns the identifier of the underlying framework.

        Returns:
            str: 'playwright'
        """
        return "playwright"

    @property
    def title(self) -> str:
        """Returns the title of the current page.

        Returns:
            str: The page title.
        """
        return self._page.title()

    @property
    def current_url(self) -> str:
        """Returns the URL of the currently active page.

        Returns:
            str: The full URL string.
        """
        return self._page.url

    @property
    def page_source(self) -> str:
        """Returns the full HTML source of the current page.

        Returns:
            str: The raw HTML string.
        """
        return self._page.content()

    def get(self, url: str) -> None:
        """Navigates the browser to the specified URL.

        Args:
            url (str): The fully qualified URL to visit.
        """
        self._page.goto(url)

    def close(self) -> None:
        """Closes the browser and releases all associated resources."""
        try:
            self._browser.close()
        except Exception as e:
            logger.warning("Error closing Playwright browser: %s", e)
        try:
            self._playwright.stop()
        except Exception as e:
            logger.warning("Error stopping Playwright handle: %s", e)

    def back(self) -> None:
        """Navigates back one step in the browser's history."""
        self._page.go_back()

    def find_element(self, by: str, selector: str) -> ElementInterface | None:
        """Finds a single element in the current DOM.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            Optional[ElementInterface]: The found element wrapper, or None.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            locator = self._page.locator(pw_selector).first
            if locator.count() > 0:
                return PlaywrightElementAdapter(locator)
        except Exception:
            pass
        return None

    def find_elements(self, by: str, selector: str) -> list[ElementInterface]:
        """Finds all matching elements in the current DOM.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.

        Returns:
            List[ElementInterface]: A list of found element wrappers.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            locators = self._page.locator(pw_selector).all()
            return [PlaywrightElementAdapter(loc) for loc in locators]
        except Exception:
            return []

    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> ElementInterface | None:  # noqa: E501
        """Waits for an element to be present in the DOM.

        Args:
            by (str): The location strategy.
            selector (str): The selector string.
            timeout (int): Maximum seconds to wait.

        Returns:
            Optional[ElementInterface]: The element if found within timeout.
        """
        pw_selector = _to_playwright_selector(by, selector)
        try:
            # Playwright uses milliseconds for timeout
            self._page.wait_for_selector(pw_selector, timeout=timeout * 1000, state="attached")  # noqa: E501
            locator = self._page.locator(pw_selector).first
            return PlaywrightElementAdapter(locator)
        except Exception:
            return None

    def execute_script(self, script: str, *args: Any) -> Any:
        """Executes JavaScript in the context of the current page.

        Args:
            script (str): The JavaScript code.
            *args (Any): Arguments.

        Returns:
            Any: The script result.
        """
        # Playwright's evaluate needs careful argument handling if passing handles.
        # For simplicity in this adaptation, we pass primitives.
        # If passing elements is needed, we would pass the locator._element (JSHandle).
        unwrapped_args = []
        for arg in args:
            if isinstance(arg, PlaywrightElementAdapter):
                # NOTE: Passing the raw locator is complex in evaluate.
                # In generic scripts, we usually pass data, not elements.
                # If element manipulation is needed, handle it in the adapter.
                pass
            else:
                unwrapped_args.append(arg)

        # We wrap the script in a function that accepts the args
        # Playwright evaluate signature: page.evaluate(expression, arg)
        return self._page.evaluate(f"() => {{ {script} }}")

    def switch_to_iframe(self, iframe_element: ElementInterface) -> None:
        """Switches context (Not strictly needed in Playwright).

        Playwright handles frames via `page.frame_locator()`. This method
        is largely a no-op or placeholder in the Playwright model as direct
        frame switching isn't the primary pattern, but we can implement it
        by focusing.
        """
        pass

    def switch_to_default_content(self) -> None:
        """Switches context back (No-op in Playwright)."""
        pass

    def get_cookies(self) -> list[dict]:
        """Retrieves all cookies from the current session.

        Returns:
            List[dict]: A list of cookie dictionaries.
        """
        return self._page.context.cookies()

    def add_cookie(self, cookie: dict) -> None:
        """Adds a cookie to the current session.

        Args:
            cookie (dict): A dictionary representing the cookie.
        """
        self._page.context.add_cookies([cookie])

    def scroll_by_offset(self, x: int, y: int) -> None:
        """Scrolls the viewport by a specific offset.

        Args:
            x (int): Horizontal pixels.
            y (int): Vertical pixels.
        """
        self._page.mouse.wheel(x, y)

    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """Moves the mouse cursor relative to its current position.

        Args:
            x (int): Horizontal pixels.
            y (int): Vertical pixels.
        """
        # Playwright doesn't have a direct "relative move" like Selenium.
        # We calculate current + offset.
        # Note: This is an approximation as getting current mouse pos
        # isn't exposed directly in the high level API.
        # For evasion, we usually just move to elements.
        pass

    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:  # noqa: E501
        """Moves the mouse cursor to the center of a specific element.

        Args:
            element (ElementInterface): The target element.
            offset_x (int): Horizontal offset.
            offset_y (int): Vertical offset.
        """
        if isinstance(element, PlaywrightElementAdapter):
            box = element._locator.bounding_box()
            if box:
                center_x = box['x'] + box['width'] / 2
                center_y = box['y'] + box['height'] / 2
                self._page.mouse.move(center_x + offset_x, center_y + offset_y)

    def perform_mouse_fidget(self) -> None:
        """Performs a small, random mouse movement."""
        x = random.randint(100, 500)
        y = random.randint(100, 500)
        self._page.mouse.move(x, y)

    def save_screenshot(self, filepath: str) -> None:
        """Saves a screenshot of the current viewport to a file.

        Args:
            filepath (str): The full path where the image should be saved.
        """
        self._page.screenshot(path=filepath)

    def get_raw_page(self) -> Page:
        """Returns the underlying Playwright Page object.

        Returns:
            Page: The raw Playwright page instance.
        """
        return self._page