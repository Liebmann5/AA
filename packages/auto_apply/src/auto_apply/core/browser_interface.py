"""
Defines the abstract contracts for browser and element automation.

This module contains the abstract base classes (ABCs) that form the core
of the framework-agnostic browser control system. By defining a common
"language" or interface, the rest of the application can operate on any
underlying framework (like Selenium or Playwright) without needing to know
the specific implementation details.

This approach is fundamental to the Dependency Inversion Principle.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Tuple
from selenium.webdriver.common.by import By # Using By as a standard reference
from .browser_state import BrowserStateSnapshot

class ElementInterface(ABC):
    """
    Abstracts a single DOM element, defining a contract for interaction.

    Any class that represents a single element (e.g., Selenium's WebElement,
    Playwright's Locator) must implement these methods to be compatible with
    the automation framework.
    """

    @abstractmethod
    def click(self) -> None:
        """Simulates a user click on the element."""
        ...

    @abstractmethod
    def send_keys(self, text: str) -> None:
        """
        Types a string of text into an element, like a user typing.

        Args:
            text: The string of text to be typed into the element.
        """
        ...

    @abstractmethod
    def get_attribute(self, name: str) -> Optional[str]:
        """
        Fetches the value of an element's HTML attribute.

        Args:
            name: The name of the attribute to retrieve (e.g., 'href', 'class').

        Returns:
            The value of the attribute as a string, or None if it does not exist.
        """
        ...

    @property
    @abstractmethod
    def text(self) -> str:
        """str: The visible text content of the element."""
        ...

    @abstractmethod
    def get_location(self) -> Tuple[int, int]:
        """
        Gets the (x, y) location of the element on the page.
        Gets the (x, y) coordinates of the element's top-left corner.

        Returns:
            A tuple containing the integer x and y coordinates.
        """
        pass

    @abstractmethod
    def get_size(self) -> Tuple[int, int]:
        """
        Gets the rendered (width, height) of the element.

        Returns:
            A tuple containing the integer width and height.
        """
        pass

    def find_element(self, by: By, selector: str) -> Optional['ElementInterface']:
        """
        Finds a single child element within this element's subtree(element within this element).

        Args:
            by: The mechanism to find the element (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            An ElementInterface object if found, otherwise None
        """
        pass

    @abstractmethod
    def find_elements(self, by: By, selector: str) -> List['ElementInterface']:
        """
        Finds all child elements within this element's subtree matching the selector.

        Args:
            by: The mechanism to find the elements (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            A list of ElementInterface objects. The list will be empty if none are found.
        """
        pass

class BrowserInterface(ABC):
    """
    Abstracts the browser driver/page itself, defining a contract for control.

    Any class that manages a browser instance (e.g., Selenium's WebDriver)
    must implement these methods to be compatible with the automation framework.
    """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """
        str: The name of the underlying adapter framework (e.g., 'selenium', 'playwright').

        This property is the cornerstone of the Dependency Inversion fix, allowing
        high-level modules to identify the framework without importing low-level adapters.
        """
        pass

    @abstractmethod
    def get(self, url: str) -> None:
        """
        Navigates the browser to a specific URL.

        Args:
            url: The fully qualified URL to navigate to.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Closes the browser and terminates the driver process."""
        ...

    @abstractmethod
    def find_element(self, by: str, selector: str) -> Optional[ElementInterface]:
        """Finds a single element on the current page.

        Args:
            by: The mechanism to find the element (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            An ElementInterface object if found, otherwise None.
        """
        ...

    @abstractmethod
    def find_elements(self, by: By, selector: str) -> List[ElementInterface]:
        """Finds all elements on the current page that match the selector.

        Args:
            by: The mechanism to find the elements (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            A list of ElementInterface objects. The list will be empty if none are found.
        """
        ...

    @abstractmethod
    def wait_for_element(self, by: By, selector: str, timeout: int = 10) -> Optional[ElementInterface]:
        """
        Waits for a single element to be present in the DOM.

        This is a crucial method for handling dynamic pages where elements
        may not be immediately available after a page load.

        Args:
            by: The mechanism to find the element (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').
            timeout: The maximum number of seconds to wait for the element.

        Returns:
            The ElementInterface object if found within the timeout, otherwise None.
        """
        pass

    @property
    @abstractmethod
    def page_source(self) -> str:
        """str: The full HTML source of the current page."""
        ...

    @property
    @abstractmethod
    def title(self) -> str:
        """str: The title of the current page."""
        ...

    @property
    @abstractmethod
    def current_url(self) -> str:
        """str: The URL of the currently displayed page."""
        ...

    @abstractmethod
    def execute_script(self, script: str, *args: Any) -> Any:
        """
        Executes JavaScript in the current page context.

        Args:
            script: The JavaScript code to execute.
            *args: Any arguments to pass to the script. These can be
                   ElementInterface objects, which will be unwrapped to their
                   native DOM element counterparts within the script.

        Returns:
            The value returned by the executed script.
        """
        pass

    @abstractmethod
    def get_cookies(self) -> List[dict]:
        """
        Gets all cookies from the current browser session.

        Returns:
            A list of dictionaries, where each dictionary represents a cookie.
        """
        pass

    @abstractmethod
    def add_cookie(self, cookie: dict) -> None:
        """
        Adds a single cookie to the browser session.

        Args:
            cookie: A dictionary representing the cookie to add.
        """
        pass

    @abstractmethod
    def back(self) -> None:
        """Navigates back one-step in the browser's history."""
        pass

    @abstractmethod
    def scroll_by_offset(self, x: int, y: int) -> None:
        """
        Scrolls the page by a given x/y offset.

        Args:
            x: The horizontal pixel offset to scroll by.
            y: The vertical pixel offset to scroll by.
        """
        pass

    @abstractmethod
    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """
        Moves the mouse from its current position by an x/y offset.

        Args:
            x: The horizontal pixel offset to move by.
            y: The vertical pixel offset to move by.
        """
        pass

    @abstractmethod
    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:
        """
        Moves the mouse to the center of a specific element.
        Moves the mouse to a specific element, with an optional offset.

        Args:
            element: The target ElementInterface to move the mouse to.
            offset_x: An optional horizontal offset from the element's center.
            offset_y: An optional vertical offset from the element's center.
        """
        pass

    @abstractmethod
    def perform_mouse_fidget(self) -> None:
        """Performs a small, random mouse wiggle to simulate human-like idle behavior."""
        pass

    @abstractmethod
    def save_screenshot(self, filepath: str) -> None:
        """
        Saves a screenshot of the current page to a file.

        Args:
            filepath: The absolute or relative path where the screenshot will be saved.
        """
        pass