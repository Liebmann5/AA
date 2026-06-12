"""Port for page understanding capabilities used by discovery providers.

Allows providers (e.g., GoogleProvider) to delegate SERP analysis
without coupling to concrete implementations. Adapters implementing
this protocol may use geometric, DOM, or ML-based analysis.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PageUnderstandingPort(Protocol):
    """Contract for analyzing search result pages and forms."""

    def analyze_serp(self, context: Any) -> Any:
        """Analyze a SERP currently loaded in the browser context.

        Args:
            context: The provider or browser context needed for analysis.

        Returns:
            Analysis result (e.g., list of Job objects).
        """
        ...

    def analyze_form(self, context: Any) -> Any:
        """Analyze an application form currently loaded.

        Args:
            context: The provider or browser context needed for analysis.

        Returns:
            Structured form understanding (e.g., WebpageStructure).
        """
        ...