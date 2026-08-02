
"""Pins for the understand -> plan -> act triad going live (Stage 6).

The domain has carried this triad since the beginning and never ran it:
``UIModel`` (perception) -> ``InteractionPlan`` (reasoning) ->
``InteractionPort.execute_plan`` (execution). ``execute_plan`` had zero callers.
``FormSolver`` was built by the composition root and handed to nobody. Both
were constructed and never connected — this codebase's signature failure, and
the reason the anti-orphan pins below are the ones that matter.

The pass is deliberately SUPPLEMENTARY. It fills what the classifier left
alone; it does not click. That is not tidiness — ``FormSolver.devise_plan``
puts a submit button in its plan, and executing that here would submit an
application from a path that never consults the submission gate built in
Stage 1.
"""
import ast
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.ui import (
    InteractionPlan,
    InteractionType,
    PlannedAction,
    UIElement,
    UIElementType,
)

SRC = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "auto_apply"
WORKFLOW = SRC / "application" / "workflows" / "applications_workflow.py"


def _element(el_id: str, existing_value: str | None = "", raises: bool = False):
    element = UIElement(id=el_id, element_type=UIElementType.TEXT_INPUT)
    reference = MagicMock()
    if raises:
        reference.get_attribute.side_effect = RuntimeError("stale element")
    else:
        reference.get_attribute.return_value = existing_value
    element.set_reference(reference)
    return element


def _action(element, action_type=InteractionType.TYPE, value="Nick"):
    return PlannedAction(
        target_element_id=element.id,
        action_type=action_type,
        reasoning="pin",
        ui_element=element,
        value=value,
    )


def _workflow(*, plan=None, perception=None, reasoning=None, interaction=None):
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )

    if perception is None:
        perception = MagicMock()
        perception.scan_page.return_value = MagicMock()
    if reasoning is None:
        reasoning = MagicMock()
        reasoning.devise_plan.return_value = plan or InteractionPlan(
            goal_description="apply", actions=[]
        )
    if interaction is None:
        interaction = MagicMock()
        interaction.execute_plan.return_value = True

    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=perception,
        interaction_port=interaction,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        reasoning_port=reasoning,
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-ORPHAN — the triad actually runs
# ─────────────────────────────────────────────────────────────────────────────


def test_the_whole_triad_runs_on_one_pass():
    """scan_page -> devise_plan -> execute_plan, all three, in that order."""
    element = _element("e1")
    wf = _workflow(plan=InteractionPlan(goal_description="apply", actions=[_action(element)]))

    filled = wf._run_strategic_pass()

    wf._perception_port.scan_page.assert_called_once()
    wf._reasoning_port.devise_plan.assert_called_once()
    wf._interaction_port.execute_plan.assert_called_once()
    assert filled == 1


def test_the_plan_reaching_the_executor_is_a_real_interaction_plan():
    element = _element("e1")
    wf = _workflow(plan=InteractionPlan(goal_description="apply", actions=[_action(element)]))

    wf._run_strategic_pass()

    executed = wf._interaction_port.execute_plan.call_args[0][0]
    assert isinstance(executed, InteractionPlan)
    assert [a.target_element_id for a in executed.actions] == ["e1"]


def test_execute_plan_now_has_a_caller_in_production_code():
    """The orphan check, done the same way as the scroller injection.

    ``execute_plan`` is defined in the interaction adapter. Before this stage
    nothing in src called it.
    """
    callers = []
    for path in sorted(SRC.rglob("*.py")):
        if "interaction" in str(path) and "human_like_adapter" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if ".execute_plan(" in text:
            callers.append(str(path.relative_to(SRC)).replace("\\", "/"))

    assert callers, "execute_plan still has no production caller"
    assert "application/workflows/applications_workflow.py" in callers


def test_the_composition_root_hands_form_solver_to_the_engine():
    """FormSolver was assigned and passed to nobody for the whole project."""
    source = (SRC / "infrastructure" / "composition_root.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert "reasoning_port = FormSolver(" in source
    assert "reasoning_port=reasoning_port" in source


def test_the_strategic_pass_is_called_inside_the_per_page_loop():
    """Live path, not a helper nobody invokes — checked the same way as 5c."""
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8", errors="ignore"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        called = {
            inner.func.attr
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
        }
        if "_navigate_multi_page_flow" in called:
            assert "_run_strategic_pass" in called
            return

    pytest.fail("could not find the per-page loop")


# ─────────────────────────────────────────────────────────────────────────────
# THE SUBMISSION GATE MUST NOT BE ROUTED AROUND
# ─────────────────────────────────────────────────────────────────────────────


def test_a_planned_click_is_never_executed_by_the_strategic_pass():
    """FormSolver plans a submit click. This pass must not perform it.

    Executing a planned click here would submit the application without ever
    consulting the interrupt policy or the approval gate — the exact fail-open
    that Stage 1 closed.
    """
    submit = _element("submit")
    wf = _workflow(
        plan=InteractionPlan(
            goal_description="apply",
            actions=[_action(submit, action_type=InteractionType.CLICK, value=None)],
        )
    )

    assert wf._run_strategic_pass() == 0
    wf._interaction_port.execute_plan.assert_not_called()


def test_clicks_are_stripped_but_fills_still_run():
    typed, submit = _element("e1"), _element("submit")
    wf = _workflow(
        plan=InteractionPlan(
            goal_description="apply",
            actions=[
                _action(typed),
                _action(submit, action_type=InteractionType.CLICK, value=None),
            ],
        )
    )

    assert wf._run_strategic_pass() == 1

    executed = wf._interaction_port.execute_plan.call_args[0][0]
    assert [a.action_type for a in executed.actions] == [InteractionType.TYPE]


# ─────────────────────────────────────────────────────────────────────────────
# EQUIVALENCE — the existing fill path is untouched
# ─────────────────────────────────────────────────────────────────────────────


def test_an_already_filled_element_is_never_overwritten():
    """Whatever the classifier put there stays there."""
    wf = _workflow(
        plan=InteractionPlan(
            goal_description="apply",
            actions=[_action(_element("e1", existing_value="already here"))],
        )
    )

    assert wf._run_strategic_pass() == 0
    wf._interaction_port.execute_plan.assert_not_called()


def test_an_uninspectable_element_is_left_alone():
    """Not being able to check is a reason to skip, not a licence to overwrite."""
    wf = _workflow(
        plan=InteractionPlan(
            goal_description="apply", actions=[_action(_element("e1", raises=True))]
        )
    )

    assert wf._run_strategic_pass() == 0


def test_the_pass_never_calls_fill_directly():
    """All execution goes through the plan; no second fill mechanism appears."""
    wf = _workflow(
        plan=InteractionPlan(goal_description="apply", actions=[_action(_element("e1"))])
    )

    wf._run_strategic_pass()

    wf._interaction_port.fill.assert_not_called()


def test_an_empty_plan_touches_nothing():
    wf = _workflow(plan=InteractionPlan(goal_description="apply", actions=[]))

    assert wf._run_strategic_pass() == 0
    wf._interaction_port.execute_plan.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# DEGRADATION — a supplementary pass must never break a fill
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", ["perception", "reasoning", "interaction"])
def test_a_missing_collaborator_is_a_no_op(missing):
    wf = _workflow(plan=InteractionPlan(goal_description="apply", actions=[]))
    setattr(wf, f"_{missing}_port", None)

    assert wf._run_strategic_pass() == 0


def test_a_planner_that_raises_does_not_break_the_page():
    reasoning = MagicMock()
    reasoning.devise_plan.side_effect = RuntimeError("planner exploded")
    wf = _workflow(reasoning=reasoning)

    assert wf._run_strategic_pass() == 0


def test_an_executor_that_raises_does_not_break_the_page():
    interaction = MagicMock()
    interaction.execute_plan.side_effect = RuntimeError("executor exploded")
    wf = _workflow(
        plan=InteractionPlan(goal_description="apply", actions=[_action(_element("e1"))]),
        interaction=interaction,
    )

    assert wf._run_strategic_pass() == 0


def test_a_scanner_that_raises_does_not_break_the_page():
    perception = MagicMock()
    perception.scan_page.side_effect = RuntimeError("scanner exploded")
    wf = _workflow(perception=perception)

    assert wf._run_strategic_pass() == 0
