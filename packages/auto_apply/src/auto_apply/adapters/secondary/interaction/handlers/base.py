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

    def __init__(
        self,
        browser: BrowserInterface,
        page_action=None,
        readiness=None,
    ):
        """Initializes the handler with the active browser context.

        Args:
            browser (BrowserInterface): The active browser instance, utilized for
                actions that require driver-level access (e.g., executing JavaScript,
                moving the mouse) beyond simple element interaction.
            page_action: The PageActionService tool, seen through the narrow
                :class:`PageActionPrimitives` protocol — click, type_text,
                settle, and nothing else. It owns all timing and the seeded
                RNG, which is why handlers contain no sleeps.
            readiness: A :class:`DomReadinessPort` — one method,
                ``wait_for_dom_stable``. Used where a handler must wait for the
                page to finish reacting (combobox filtering, upload
                processing); that is readiness, not pacing, and a fixed sleep
                can only guess at it.
        """
        self.browser = browser
        self._act = page_action
        self._ready = readiness

    # ------------------------------------------------------------------
    # Collaborator access — the ONLY place a handler reaches either one
    # ------------------------------------------------------------------

    def _click(self, element: ElementInterface) -> None:
        """Click through the tool, falling back to the raw element.

        The fallback is timing-free by design: without the tool there is no
        pacing to apply, and inventing some here would recreate the duplication
        this stage removes. In production the tool is always injected.
        """
        if self._act is None:
            element.click()
            return
        self._act.click(element)

    def _type(self, element: ElementInterface, text: str) -> None:
        """Type through the tool, falling back to the raw element."""
        if self._act is None:
            element.send_keys(text)
            return
        self._act.type_text(element, text)

    def _settle(self) -> None:
        """Short pause from the tool's configured range, if a tool is present."""
        if self._act is None:
            return
        self._act.settle()

    def _await_dom_ready(self) -> bool:
        """Wait for the page to finish reacting, if a readiness port is present.

        Returns:
            True if the DOM settled (or there is nothing to wait on), False if
            the readiness budget expired.
        """
        if self._ready is None:
            return True
        return self._ready.wait_for_dom_stable()

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