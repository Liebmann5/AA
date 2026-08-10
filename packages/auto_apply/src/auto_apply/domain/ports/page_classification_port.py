"""Contract for deciding what kind of page the browser is currently showing.

``serp_strategy`` asks this before extracting, to tell a results page from a
CAPTCHA wall or an error page. It was importing the concrete
``adapters.secondary.dom.classifier.PageClassifier``.

``PageType`` already lives in ``domain.types``, so the return type needed no
move — only the annotation had to stop pointing at the concrete classifier.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_apply.domain.types import PageType


@runtime_checkable
class PageClassifierPort(Protocol):
    """Classifies the page currently loaded in the browser."""

    def classify(self) -> PageType:
        """Return the page's type."""
        ...
