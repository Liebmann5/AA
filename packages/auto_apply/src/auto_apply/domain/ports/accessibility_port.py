"""Defines contracts for Accessibility Object Model (AOM) interactions.

The AOM provides a semantic representation of a webpage, intended for screen
readers. By querying the AOM instead of the raw HTML DOM, the agent becomes
immune to visual obfuscation, dynamic CSS class names, and layout shifts.
"""

from abc import ABC, abstractmethod
from typing import Any


class IAccessibilityNode(ABC):
    """Represents a single semantic node in the accessibility tree."""

    @property
    @abstractmethod
    def node_id(self) -> str:
        """A unique identifier for this node in the current tree."""
        ...

    @property
    @abstractmethod
    def role(self) -> str:
        """The semantic role (e.g., 'textbox', 'button', 'checkbox')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """The accessible name (often the label or visible text)."""
        ...

    @property
    @abstractmethod
    def properties(self) -> dict[str, Any]:
        """Additional ARIA properties (e.g., required, disabled, checked)."""
        ...

class IAccessibilityScanner(ABC):
    """Contract for extracting the accessibility tree from the browser."""

    @abstractmethod
    def get_accessibility_tree(self) -> list[IAccessibilityNode]:
        """Extracts the full, flattened accessibility tree of the current page.

        Returns:
            List[IAccessibilityNode]: A list of all semantic nodes on the page.
        """
        ...
