"""Abstract port for mathematical webpage understanding.

This interface defines the contract for the core reasoning engine that
segments a DOM tree, identifies forms, pairs labels with inputs, and
infers field types—all using pure mathematics.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.math_dom import DOMNode
from auto_apply.domain.models.math_webpage import WebpageStructure


class FormUnderstandingPort(ABC):
    """Contract for a deterministic form analysis engine.

    Implementations of this port take a raw DOMNode tree (with geometry)
    and produce a structured `WebpageStructure` containing identified
    form regions, field clusters, and inferred field semantics.
    """

    @abstractmethod
    def analyze(self, dom_root: DOMNode, url: str = "", title: str = "") -> WebpageStructure:
        """Perform complete mathematical analysis of the given DOM tree.

        This method orchestrates the full pipeline:
          1. Segment the page into visual blocks.
          2. Identify form containers and their fields.
          3. Pair each input with its corresponding label.
          4. Infer the semantic type of each field.
          5. Detect multi‑step flows, honeypots, and CAPTCHAs.
          6. Optionally detect job listing containers.

        Args:
            dom_root: The root of the DOM tree (typically <body>).
            url: The URL of the page (for metadata).
            title: The page title (for metadata).

        Returns:
            A fully populated WebpageStructure instance.
        """
        pass
