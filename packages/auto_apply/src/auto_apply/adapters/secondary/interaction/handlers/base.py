"""Defines the abstract contract for specific input interaction strategies.

This module provides the `BaseInputHandler` abstract base class. All specific
input strategies (Text, Select, File, etc.) must implement this interface.
This ensures the main Interactor can delegate tasks uniformly across different
UI widgets without coupling to specific implementations.
"""

from abc import ABC, abstractmethod
from typing import Any

from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface


class BaseInputHandler(ABC):
    """Abstract base class for handling specific form input interactions.

    This class defines the interface for the Strategy Pattern used to handle
    polymorphic DOM elements. Concrete implementations are responsible for
    the nuances of specific HTML tags (e.g., <select>, <input type="file">).
    """

    def __init__(self, browser: BrowserInterface):
        """Initializes the handler with the active browser context.

        Args:
            browser (BrowserInterface): The active browser instance, utilized for
                actions that require driver-level access (e.g., executing JavaScript,
                moving the mouse) beyond simple element interaction.
        """
        self.browser = browser

    @abstractmethod
    def handle(self, element: ElementInterface, value: Any) -> None:
        """Performs the specific interaction required to fill or manipulate the element.

        Concrete implementations must handle exceptions internally or raise
        domain-specific errors if the interaction fails completely.

        Args:
            element (ElementInterface): The target DOM element to interact with.
            value (Any): The data to be entered, selected, or uploaded. The type
                depends on the specific handler implementation (e.g., str for text,
                bool for checkboxes).

        Raises:
            NotImplementedError: If the subclass does not implement this method.
        """
        ...
