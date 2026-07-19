"""Abstract port for extracting a mathematical DOM tree from a browser.

This interface defines the contract for any adapter that can acquire the
full DOM structure of a webpage, including geometry (bounding boxes).
Implementations may use Selenium, Playwright, or even static HTML parsing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from auto_apply.domain.models.math_dom import DOMNode


class MathematicalPerceptionPort(ABC):
    """Contract for a geometry‑aware DOM extractor.

    The single method `extract_full_dom_tree()` returns a complete,
    immutable DOMNode tree representing the current page. The returned
    tree must be self‑contained and require no further browser interaction.
    """

    @abstractmethod
    def extract_full_dom_tree(self) -> DOMNode | None:
        """Extract the entire DOM tree of the currently loaded page.

        This method should:
          - Use the underlying browser automation framework to traverse
            the live DOM and collect tag names, attributes, visible text,
            and computed bounding boxes (via getBoundingClientRect).
          - Omit non‑rendered nodes (<script>, <style>, etc.) to reduce
            memory usage, unless required for structural analysis.
          - Return a root DOMNode (typically <body> or a synthetic root).

        Returns:
            A DOMNode tree with geometry where available, or None if
            extraction fails (e.g., no page loaded, driver disconnected).

        Raises:
            PerceptionError: If a critical, unrecoverable error occurs.
        """
        pass

    @abstractmethod
    def get_current_url(self) -> str:
        """Return the current page URL, if available."""
        ...

    @abstractmethod
    def get_page_title(self) -> str:
        """Return the current page title, if available."""
        ...