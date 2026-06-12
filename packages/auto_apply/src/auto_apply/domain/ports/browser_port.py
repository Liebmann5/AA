"""
Defines the abstract contracts for framework-agnostic browser automation.

This module contains the abstract base classes (ABCs) that form the core of the
application's browser control system. By defining this common "language," the
rest of the application can operate on any underlying automation library (like
Selenium or Playwright) without needing to know the specific implementation
details.

This is a fundamental application of the Dependency Inversion Principle.
"""

from abc import ABC, abstractmethod
from typing import Any


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
    def get_attribute(self, name: str) -> str | None:
        """Fetches the value of an element's HTML attribute.

        Args:
            name: The name of the attribute to retrieve (e.g., 'href', 'class').

        Returns:
            The value of the attribute as a string, or None if it does not exist.
        """
        ...

    @property
    @abstractmethod
    def text(self) -> str:
        """The visible text content of the element and its descendants."""
        ...

    @abstractmethod
    def get_location(self) -> tuple[int, int]:
        """Gets the (x, y) coordinates of the element's top-left corner on the page.

        Returns:
            A tuple containing the integer x and y coordinates.
        """
        ...

    @abstractmethod
    def get_size(self) -> tuple[int, int]:
        """
        Gets the rendered (width, height) of the element.

        Returns:
            A tuple containing the integer width and height.
        """
        ...

    @abstractmethod
    def get_shadow_root(self) -> "ElementInterface | None":
        """Retrieves the shadow root of a web component, if it exists.

        Returns:
            A new ElementInterface representing the root of the shadow DOM,
            or None if the element has no shadow root.
        """
        ...

    @abstractmethod
    def find_element(self, by: str, selector: str) -> "ElementInterface | None":
        """Finds a single child element within this element's subtree.

        Args:
            by: The mechanism to find the element (e.g., 'id', 'css selector').
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            An ElementInterface object if a matching child is found, otherwise None.
        """
        ...

    @abstractmethod
    def find_elements(self, by: str, selector: str) -> list["ElementInterface"]:
        """Finds all child elements within this element's subtree matching a selector.

        Args:
            by: The mechanism to find the elements (e.g., 'id', 'css selector').
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            A list of ElementInterface objects. The list will be empty if none are found.
        """  # noqa: E501
        ...

class BrowserInterface(ABC):
    """Abstracts the browser driver or page itself, defining a contract for control.

    This interface represents the "World" that the agent interacts with. It controls
    navigation, script execution, and top-level element finding.
    """

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """
        This property is the cornerstone of the Dependency Inversion fix, allowing
        high-level modules to identify the framework without importing low-level adapters.

        The lowercase name of the underlying framework (e.g., 'selenium').

        Returns:
            str: The name of the underlying adapter framework (e.g., 'selenium', 'playwright').
        """  # noqa: E501
        ...

    @property
    @abstractmethod
    def title(self) -> str:
        """
        The title of the current page.

        Returns:
            str: The title of the current page.
        """
        ...

    @property
    @abstractmethod
    def page_source(self) -> str:
        """
        The full HTML source of the current page's main frame.

        Returns:
            str: The full HTML source of the current page.
        """
        ...

    @property
    @abstractmethod
    def current_url(self) -> str:
        """
        The URL of the currently displayed page.

        Returns:
            str: The URL of the currently displayed page.
        """
        ...

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
        """Closes the browser and terminates the underlying driver process."""
        ...

    @abstractmethod
    def back(self) -> None:
        """Navigates back one step in the browser's history."""
        ...

    @abstractmethod
    def find_element(self, by: str, selector: str) -> ElementInterface | None:
        """Finds a single element on the current page.

        Args:
            by: The mechanism to find the element (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            An ElementInterface object if found, otherwise None.
        """
        ...

    @abstractmethod
    def find_elements(self, by: str, selector: str) -> list[ElementInterface]:
        """Finds all elements on the current page that match the selector.

        Args:
            by: The mechanism to find the elements (e.g., By.ID, By.CSS_SELECTOR).
            selector: The value of the selector (e.g., 'my-id', '.my-class').

        Returns:
            A list of ElementInterface objects. The list will be empty if none are found.
        """  # noqa: E501
        ...

    @abstractmethod
    def wait_for_element(self, by: str, selector: str, timeout: int = 10) -> ElementInterface | None:  # noqa: E501
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
        ...

    @abstractmethod
    def execute_script(self, script: str, *args: Any) -> Any:
        """Executes JavaScript in the context of the current frame or page.

        Args:
            script: The JavaScript code to execute.
            *args: Any arguments to pass to the script. These can be
                   ElementInterface objects, which will be unwrapped to their
                   native DOM element counterparts within the script.

        Returns:
            The value returned by the executed script.
        """
        ...

    @abstractmethod
    def switch_to_iframe(self, iframe_element: ElementInterface) -> None:
        """Switches the driver's context to the given iframe element.

        Args:
            iframe_element: The specified iframe element that we will prioritize the driver on.
        """  # noqa: E501
        ...

    @abstractmethod
    def switch_to_default_content(self) -> None:
        """Switches the driver's context back to the main page content."""
        ...

    @abstractmethod
    def get_cookies(self) -> list[dict]:
        """Gets all cookies from the current browser session.

        Returns:
            A list of dictionaries, where each dictionary represents a cookie.
        """
        ...

    @abstractmethod
    def add_cookie(self, cookie: dict) -> None:
        """Adds a single cookie to the browser session.

        Args:
            cookie: A dictionary representing the cookie to add(must contain name and value).
        """  # noqa: E501
        ...

    @abstractmethod
    def scroll_by_offset(self, x: int, y: int) -> None:
        """Scrolls the page by a given x/y offset.

        Args:
            x: The horizontal pixel offset to scroll by.
            y: The vertical pixel offset to scroll by.
        """
        ...

    @abstractmethod
    def move_mouse_by_offset(self, x: int, y: int) -> None:
        """Moves the mouse from its current position by an x/y offset.

        Args:
            x: The horizontal pixel offset to move by.
            y: The vertical pixel offset to move by.
        """
        ...

    @abstractmethod
    def move_mouse_to_element(self, element: ElementInterface, offset_x: int = 0, offset_y: int = 0) -> None:  # noqa: E501
        """Moves the mouse to a specific element, with an optional offset.

        Args:
            element: The target ElementInterface to move the mouse to.
            offset_x: An optional horizontal offset from the element's center.
            offset_y: An optional vertical offset from the element's center.
        """
        ...

    @abstractmethod
    def perform_mouse_fidget(self) -> None:
        """Performs a small, random mouse wiggle to simulate human-like behavior."""
        ...

    @abstractmethod
    def save_screenshot(self, filepath: str) -> None:
        """Saves a screenshot of the current page to a file.

        Args:
            filepath: The absolute or relative path where the screenshot will be saved.
        """
        ...
