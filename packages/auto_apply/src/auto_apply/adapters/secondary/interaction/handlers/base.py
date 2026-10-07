"""Defines the abstract contract for specific input interaction strategies.

This module provides the `BaseInputHandler` abstract base class. All specific
input strategies (Text, Select, File, etc.) must implement this interface.
This ensures the main Interactor can delegate tasks uniformly across different
UI widgets without coupling to specific implementations.
"""

from abc import ABC, abstractmethod
from typing import Any

from auto_apply.domain.exceptions import ApplicationError
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
        """Click through the tool. The tool is REQUIRED.

        There is deliberately no raw-element fallback: a raw click bypasses
        the probe (occlusion, challenge widgets), the pacing and the session
        tally, so a mis-wired handler would click silently and untraceably.
        The composition root always injects the tool; tests inject a fake.

        A refused or failed tool click RAISES. Discarding the ActionResult
        (the old behaviour) let a widget that was never actually operated
        pass as filled; raising here is what lets a handler with a fallback
        (the checkable handler's JS click) actually reach it.
        """
        if self._act is None:
            raise ApplicationError(
                "input handler has no interaction tool — refusing a raw click"
            )
        result = self._act.click(element)
        if not result:
            reason = getattr(result, "reason", "unknown")
            raise ApplicationError(f"click did not complete: {reason}")

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