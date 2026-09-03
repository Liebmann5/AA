"""Defines the contracts for formal logic and reasoning engines.

This abstraction separates the application's decision-making process from the
underlying mathematical solver (e.g., Answer Set Programming via clingo) and
from higher-level form-planning strategies.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.ui import InteractionPlan, UIModel
from auto_apply.domain.ports.accessibility_port import IAccessibilityNode


class ILogicSolver(ABC):
    """Contract for a deterministic Answer Set Programming form-semantics solver.

    The single implementation is ``ClingoFormSolver``
    (``adapters/secondary/reasoning/asp_adapter.py``). It answers exactly one
    question: given the accessibility tree of the current page, which AOM node
    plays each logical role in the form (first name, résumé upload, submit
    button). The solver grounds the tree against its rule set
    (``rules/form_semantics.lp``) and returns a mapping of logical role to
    backend node id.

    HISTORY: this port previously declared a generic ASP contract,
    ``solve(facts: list[str], rules_path: str) -> list[dict[str, str]]``.
    Nothing in AA ever implemented or consumed that shape; the one implementer
    contradicted it from the day it was written — the exact defect class the
    architecture pins now catch. The contract below is the one that exists.
    A future generic ASP consumer should reintroduce the generic shape as a
    SEPARATE port rather than widening this one back into a union signature
    that fits nothing well.
    """

    @abstractmethod
    def solve(self, aom_nodes: list[IAccessibilityNode]) -> dict[str, str]:
        """Ground an accessibility tree against the solver's rule set.

        Args:
            aom_nodes: The semantic accessibility nodes of the current page,
                as produced by an ``IAccessibilityScanner``.

        Returns:
            Mapping of logical form-role name to AOM backend node id, e.g.
            ``{"first_name": "84729", "submit_button": "99312"}``. Empty when
            the logic program is unsatisfiable or the rules file is missing.
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
