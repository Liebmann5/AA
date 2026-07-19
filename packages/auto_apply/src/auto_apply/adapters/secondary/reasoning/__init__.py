"""Public surface of the reasoning services package.

Re-exports the two classes that external code imports from this package:

    LogicEngine  — deterministic rule-based reasoning (work auth, sponsorship,
                   experience contradiction detection, security clearance).
    FormSolver   — converts UIModel page snapshots into InteractionPlans.

Usage::

    from auto_apply.adapters.secondary.reasoning import LogicEngine, FormSolver
"""

from auto_apply.adapters.secondary.reasoning.rule_based_adapter import (
    FormSolver,
    LogicEngine,
)

__all__ = ["LogicEngine", "FormSolver"]