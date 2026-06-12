"""Defines the contract for specialized resolution engines.

This interface standardizes how the application interacts with tools that
solve complex problems, such as CAPTCHAs or Logic puzzles.
"""

from abc import ABC, abstractmethod
from typing import Any


class ResolutionInterface(ABC):
    """Abstract base class for a solver/resolver."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the name of the resolution strategy (e.g., 'AudioCaptcha')."""
        pass

    @abstractmethod
    def resolve(self, context: Any) -> bool:
        """Attempts to solve the problem provided in the context.

        Args:
            context (Any): The data or browser state needed to solve the problem.

        Returns:
            bool: True if resolved successfully, False otherwise.
        """
        pass
