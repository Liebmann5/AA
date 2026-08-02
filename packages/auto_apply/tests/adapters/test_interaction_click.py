
"""Pins for the restored element-click path (Stage 1 — interaction beachhead).

Before this stage ``InteractionExecutor`` — the object injected everywhere as
``interaction_port`` — had no ``click`` method at all.  ``ApplicationsWorkflow``
calls ``self._interaction_port.click(...)`` at three sites (apply CTA, next
page, submit), so every click raised ``AttributeError`` inside a ``try`` block
and the Applications engine could not click anything.

These pins fix the shape of the repair:

    * ``click`` and ``simulate_idle`` exist on the executor and are pure
      DELEGATIONS to the injected ``PageActionService`` tool — the executor
      owns no timing, no RNG, and no mouse mechanics of its own.
    * ``click`` raises on failure (it returns ``None`` on success, per the
      ``InteractionPort`` contract) so the workflow's existing
      ``except`` path still records ``submit_clicked=False`` truthfully.
    * ``execute_plan`` paces through the tool's ``settle()``, not a hardcoded
      ``time.sleep(0.5)``.
    * There is exactly ONE click implementation in the interaction package.
"""
import inspect
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.adapters.secondary.interaction.human_like_adapter import (
    InteractionExecutor,
)
from auto_apply.domain.exceptions import ApplicationError


class _FakeActionResult:
    """Mimics PageActionService.ActionResult: truthy on success, carries reason."""

    def __init__(self, success: bool, reason: str = "ok") -> None:
        self.success = success
        self.reason = reason

    def __bool__(self) -> bool:
        return self.success


def _tool(success: bool = True, reason: str = "ok") -> MagicMock:
    """A stand-in PageActionService exposing the primitives the executor uses."""
    tool = MagicMock()
    tool.click.return_value = _FakeActionResult(success, reason)
    tool.type_text.return_value = _FakeActionResult(success, reason)
    tool.settle.return_value = None
    tool.macro_pause.return_value = None
    return tool


def _executor(tool=None) -> InteractionExecutor:
    return InteractionExecutor(browser=MagicMock(), page_action=tool)


# ─────────────────────────────────────────────────────────────────────────────
# click
# ─────────────────────────────────────────────────────────────────────────────


def test_executor_exposes_click():
    """InteractionExecutor.click exists — the live-fatal gap this stage closes."""
    assert hasattr(InteractionExecutor, "click"), (
        "InteractionExecutor has no click(); ApplicationsWorkflow calls "
        "interaction_port.click() at three sites and every one of them fails."
    )


def test_click_delegates_to_the_page_action_tool():
    """click() performs no mechanics itself — it hands the element to the tool."""
    tool = _tool()
    element = MagicMock()

    assert _executor(tool).click(element) is None
    tool.click.assert_called_once_with(element)


def test_click_raises_when_the_tool_reports_failure():
    """A failed click must raise so callers can record it as a failure.

    PageActionService.click never raises — it returns a falsy ActionResult.  If
    the executor swallowed that, ApplicationsWorkflow would write
    submit_clicked=True for a click that never landed.
    """
    tool = _tool(success=False, reason="element not interactable")

    with pytest.raises(ApplicationError) as exc_info:
        _executor(tool).click(MagicMock())

    assert "element not interactable" in str(exc_info.value)


def test_click_raises_cleanly_when_no_tool_is_injected():
    """Degradation: without the tool, click fails with a domain error.

    Not an AttributeError, and never a silent no-op.  In production the tool is
    always constructed alongside the driver (interaction_port is None when
    there is no driver), so this path is reachable only by direct construction.
    """
    with pytest.raises(ApplicationError):
        _executor(None).click(MagicMock())


def test_click_does_not_import_or_call_the_evasion_click_helper():
    """Single click path: the executor must not reach into behavior.human_like_click."""
    source = inspect.getsource(InteractionExecutor)
    assert "human_like_click" not in source, (
        "InteractionExecutor still calls behavior.human_like_click — clicking "
        "must live in exactly one place (the PageActionService tool)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# simulate_idle
# ─────────────────────────────────────────────────────────────────────────────


def test_executor_exposes_simulate_idle_and_delegates():
    """simulate_idle is the InteractionPort's pacing verb; the tool owns the sleep."""
    tool = _tool()

    _executor(tool).simulate_idle(0.5, 1.5)

    tool.macro_pause.assert_called_once_with(0.5, 1.5)


# ─────────────────────────────────────────────────────────────────────────────
# execute_plan pacing
# ─────────────────────────────────────────────────────────────────────────────


def test_execute_plan_paces_through_the_tool_not_a_hardcoded_sleep():
    """The 0.5s literal between plan steps is replaced by the tool's settle()."""
    from auto_apply.domain.models.ui import (
        InteractionPlan,
        InteractionType,
        PlannedAction,
        UIElement,
        UIElementType,
    )

    element = UIElement(id="e1", element_type=UIElementType.BUTTON)
    element.set_reference(MagicMock())
    action = PlannedAction(
        target_element_id="e1",
        action_type=InteractionType.CLICK,
        reasoning="pin",
        ui_element=element,
    )
    plan = InteractionPlan(goal_description="pin", actions=[action])

    tool = _tool()
    assert _executor(tool).execute_plan(plan) is True

    assert tool.settle.call_count == 1, (
        "execute_plan must pace via the tool's settle() so pacing is "
        "config-driven and seeded in one place."
    )
    tool.click.assert_called_once()


def test_no_hardcoded_pacing_constant_survives_between_plan_steps():
    """Structural: the inter-step pause is a delegation, not a literal.

    Scoped to the pacing site on purpose. ``time.sleep`` legitimately remains
    in this class for the WAIT_FOR action, whose duration comes from the plan
    itself — that is data, not a magic pacing constant.
    """
    source = inspect.getsource(InteractionExecutor.execute_plan)
    assert "time.sleep" not in source
    assert "self._settle()" in source


# ─────────────────────────────────────────────────────────────────────────────
# single source of truth
# ─────────────────────────────────────────────────────────────────────────────


def test_the_set_of_click_implementations_is_the_known_ledger():
    """Ceiling pin: no NEW click implementation may appear in this package.

    Two dead ones already exist — StealthHumanStrategy and
    InstantHeadlessStrategy in execution_strategies.py, each defining
    click/type_text/hover/inter_action_delay, neither ever constructed
    (``InteractionExecutor.strategy`` is assigned and never read). They are the
    right shape for the tool's two injected timing profiles and are Stage 2/3
    business, so this stage pins the set rather than shrinking it: the
    delegating executor joins the ledger, and nothing else may.
    """
    pkg = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "adapters"
        / "secondary"
        / "interaction"
    )
    definers = [
        str(path.relative_to(pkg))
        for path in sorted(pkg.rglob("*.py"))
        if "def click(" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert definers == ["execution_strategies.py", "human_like_adapter.py"], (
        f"The set of click() definitions in the interaction package changed. "
        f"Expected the known ledger (two dead strategy implementations + the "
        f"delegating executor); found: {definers}"
    )
