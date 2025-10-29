from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class BaseState(ABC):
    """The abstract contract for all states in the agent's lifecycle."""
    def __init__(self, context: dict):
        self.context = context

    @abstractmethod
    def execute(self) -> str | None:
        """
        Executes the main logic for this state.

        Returns:
            The name of the next state to transition to, or None if this is a terminal state.
        """
        pass