"""Pins for the Applications-engine interruption-handler wiring (Stage S-3).

For weeks the Applications engine had two independent fatal faults in one
path: composition_root passed a phantom ``interactor=`` kwarg into a
constructor that takes only ``browser`` (TypeError, swallowed at DEBUG), and
the workflow then called ``.handle()`` on a class whose method is
``handle_interruptions()`` (AttributeError, swallowed by a bare
``except Exception: pass``). Either way, no consent overlay was ever
dismissed before form filling — and nothing said so.

Pin labels:
  pin 1 (behaviour)   — the full dismissal chain works end to end.
  pin 2 (degradation) — absence degrades: filling proceeds, one warning.
  pin 3 (guard, AST)  — the workflow only calls port-declared methods;
                        this catches the whole ``.handle()`` class.
  pin 4 (guard, AST)  — the phantom kwarg must not come back.

All four fail on the pre-fix tree: pin 1 — ``.handle()`` raises, no click;
pin 2 — the bare ``pass`` emits no warning; pin 3 — ``reached`` contains
``"handle"``; pin 4 — the kwarg is present.
"""

import ast
import logging
import pathlib
from unittest.mock import MagicMock

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan

_PKG_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOW_SRC = (
    _PKG_ROOT / "src" / "auto_apply" / "application" / "workflows" / "applications_workflow.py"
)
_COMPOSITION_SRC = _PKG_ROOT / "src" / "auto_apply" / "infrastructure" / "composition_root.py"


def _job() -> Job:
    return Job(
        title="Software Engineer",
        company="Acme Corp",
        url="https://acme.example.com/jobs/1",
        source="test",
    )


def _make_workflow(interruption_handler, browser) -> ApplicationsWorkflow:
    interrupt_policy = MagicMock()
    interrupt_policy.should_pause.return_value = False
    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=browser,
        perception_port=None,
        interaction_port=MagicMock(),
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=interruption_handler,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=interrupt_policy,
        text_generation_port=None,
        plan=SessionPlan(session_id="test"),
    )


def test_consent_overlay_is_dismissed_before_filling() -> None:
    """BEHAVIOUR: a form page with a consent overlay has it dismissed.

    Uses the REAL InterruptionHandler over a mock browser so the full chain —
    workflow → handler → browser click — is exercised, not mere delegation.
    """
    from auto_apply.adapters.secondary.navigation.interruption import InterruptionHandler

    browser = MagicMock()
    browser.page_source = "<html><body><form>fields</form></body></html>"

    consent_button = MagicMock()
    consent_button.get_size.return_value = (100, 40)
    consent_button.text = "Accept all"

    def _find_elements(by, selector):
        if "cookie" in selector.lower() or "accept" in selector.lower():
            return [consent_button]
        return []

    browser.find_elements.side_effect = _find_elements

    workflow = _make_workflow(InterruptionHandler(browser), browser)
    proceed = workflow._handle_interruptions(_job())

    consent_button.click.assert_called_once()
    assert proceed is True


def test_absent_handler_proceeds_and_warns_exactly_once(caplog) -> None:
    """DEGRADATION: no handler wired → filling still proceeds, one warning.

    Two calls, one warning. The bare ``pass`` used to emit zero.
    """
    browser = MagicMock()
    browser.page_source = "<html><body><form>fields</form></body></html>"

    workflow = _make_workflow(None, browser)

    with caplog.at_level(logging.WARNING):
        first = workflow._handle_interruptions(_job())
        second = workflow._handle_interruptions(_job())

    assert first is True and second is True
    warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "interruption" in r.getMessage().lower()
    ]
    assert len(warnings) == 1, (
        f"expected exactly one degradation warning, got {len(warnings)}: "
        f"{[r.getMessage() for r in warnings]}"
    )


def test_workflow_calls_only_port_declared_methods() -> None:
    """GUARD (AST): the workflow only calls methods InterruptionHandlerPort declares.

    This is the pin that catches the whole ``.handle()`` class: a method name
    that exists nowhere on the port cannot slip back in.
    """
    from auto_apply.domain.ports.navigation_port import InterruptionHandlerPort

    declared = {
        name
        for name, member in vars(InterruptionHandlerPort).items()
        if not name.startswith("_") and callable(member)
    }
    source = _WORKFLOW_SRC.read_text(encoding="utf-8")
    reached: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Attribute):
            continue
        inner = node.value
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr == "_interruption_handler"
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "self"
        ):
            reached.add(node.attr)

    assert reached, "no calls on self._interruption_handler found — pin is vacuous"
    assert reached <= declared, (
        f"workflow calls methods the port does not declare: "
        f"{sorted(reached - declared)} (declared: {sorted(declared)})"
    )


def test_composition_root_constructs_handler_without_phantom_kwarg() -> None:
    """GUARD (AST): the phantom ``interactor=`` kwarg must not come back.

    interruption.py's constructor takes only ``browser``; the old call raised
    TypeError every session and was swallowed at DEBUG.
    """
    import ast

    tree = ast.parse(_COMPOSITION_SRC.read_text(encoding="utf-8", errors="ignore"))

    # The phantom kwarg, by call shape. The old substring form was defeated by
    # a single space: "interactor = interaction_port" passed it.
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "InterruptionHandler")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "InterruptionHandler"
            )
        )
        and any(kw.arg == "interactor" for kw in node.keywords)
    ]
    assert not offenders, (
        f"InterruptionHandler called with the phantom kwarg 'interactor' at "
        f"composition_root.py line(s) {offenders} — the constructor takes only "
        "'browser'; this TypeError is what this pin exists to prevent"
    )

    # The loud null default, by structure. Assign OR AnnAssign, so adding a type
    # annotation to the line never breaks this pin again.
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(t, ast.Name) and t.id == "_interruption_handler"
                for t in targets
            ):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "NullInterruptionHandler"
                ):
                    found = True
    assert found, (
        "composition_root.py must default _interruption_handler to "
        "NullInterruptionHandler() (Assign or AnnAssign); the loud null default "
        "was removed or renamed, and absence becomes an AttributeError again"
    )