"""Defines the contract for browser interaction operations.

The domain expresses intent (click, fill, simulate human pacing, execute plans)
through this port. Concrete adapters handle the driver-specific mechanics so the
domain never imports browser automation tools directly.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.ui import InteractionPlan
from auto_apply.domain.ports.browser_port import ElementInterface


class InteractionPort(ABC):
    """Abstract interface for driving UI interactions.

    Adapters that implement this port live in
    ``adapters/secondary/interaction/``. They are responsible for timing,
    humanisation, and low-level error recovery — the domain only expresses
    *what* to do, never *how* to do it believably.
    """

    @abstractmethod
    def click(self, element: ElementInterface) -> None:
        """Clicks a UI element.

        The adapter may apply human-like cursor movement or a random pre-click
        delay. The domain does not care about those details.

        Args:
            element: The element to click.
        """

    @abstractmethod
    def fill(self, element: ElementInterface, value: str) -> None:
        """Fills a text input or textarea with the given value.

        The adapter may type character-by-character to simulate human input
        speed.

        Args:
            element: The input element to fill.
            value: The text value to enter.
        """

    @abstractmethod
    def simulate_idle(self, min_seconds: float, max_seconds: float) -> None:
        """Pauses for a randomised interval to mimic human pacing.

        The domain calls this between actions to avoid appearing robotic. The
        adapter chooses an actual sleep duration within the supplied range.

        Args:
            min_seconds: Minimum pause duration in seconds.
            max_seconds: Maximum pause duration in seconds.
        """

    @abstractmethod
    def execute_plan(self, plan: InteractionPlan) -> bool:
        """Executes all actions described in a structured interaction plan.

        The adapter iterates through the plan's actions sequentially, applying
        human-like pacing between steps. If a critical action fails the entire
        plan is aborted.

        Args:
            plan: The ordered sequence of actions to perform.

        Returns:
            True if all critical actions succeeded, False otherwise.
        """
