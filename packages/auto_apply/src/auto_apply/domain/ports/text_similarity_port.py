"""Protocol for text similarity scoring.

Defined here so domain/vetting/ can accept a TextMatcher (application layer)
via duck typing without importing from application/ — keeping domain/ pure.

The application-layer TextMatcher structurally satisfies this protocol.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TextSimilarityPort(Protocol):
    """Minimal contract for computing semantic similarity between two strings."""

    def get_similarity(self, text_a: str, text_b: str) -> float:
        """Return a similarity score in [0.0, 1.0].

        Args:
            text_a: First text string.
            text_b: Second text string.

        Returns:
            Float in [0.0, 1.0] where 1.0 is identical meaning.
        """
        ...

    def find_best_match(self, query: str, candidates: list[str]) -> tuple[str, float]:
        """Return the candidate most similar to *query*, and its score.

        Used by form-field matchers (select options, combobox items) and by the
        rule-based form solver to pair labels with profile keys. Backend-agnostic:
        the application-layer TextMatcher implements this over both its SpaCy
        and stdlib difflib tiers.

        Args:
            query: The reference string to match against.
            candidates: List of strings to compare.

        Returns:
            Tuple of (best_matching_candidate, score in [0.0, 1.0]).
        """
        ...
