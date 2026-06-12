"""Defines the contracts for formal logic and reasoning engines.

This abstraction separates the application's decision-making process from the
underlying mathematical solver (e.g., Answer Set Programming via clingo) and
from higher-level form-planning strategies.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.ui import InteractionPlan, UIModel


class ILogicSolver(ABC):
    """Contract for a deterministic logic programming solver."""

    @abstractmethod
    def solve(self, facts: list[str], rules_path: str) -> list[dict[str, str]]:
        """Executes a logic program to find valid solutions.

        Args:
            facts: A list of logical facts (e.g., ["role(n1, textbox)."]).
            rules_path: Path to the file containing the logic rules (.lp file).

        Returns:
            A list of valid models/solutions. Each dictionary maps a logical
            variable to its determined value.
        """
        ...


class ReasoningPort(ABC):
    """Contract for analysing page state and producing an interaction plan.

    Implementations live in ``adapters/secondary/reasoning/``. They receive a
    :class:`~auto_apply.domain.models.ui.UIModel` snapshot and return a fully
    ordered :class:`~auto_apply.domain.models.ui.InteractionPlan` ready for
    execution by an :class:`InteractionPort`.
    """

    @abstractmethod
    def devise_plan(self, ui_model: UIModel) -> InteractionPlan:
        """Analyses the current page snapshot and returns an ordered interaction plan.

        Args:
            ui_model: The perception snapshot from the scanner.

        Returns:
            An :class:`~auto_apply.domain.models.ui.InteractionPlan` describing
            the sequence of actions to perform.
        """
