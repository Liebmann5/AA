"""Pins for fill-evidence integrity (P1-e).

``InteractionPort.fill`` returns bool: True when the fill completed, False
when it did not. Before this stage, all three call sites in
``applications_workflow.py`` treated "no exception" as success and the return
value was discarded — a failed fill was published as FORM_FIELD_FILLED and
counted. AA is a research data-collection platform; evidence that says
"filled" when nothing was filled is a data-integrity defect, and the
fail-closed submission gate consumes it.

Pin labels:

* TEETH (pins 1–6) — verified to fail against the pre-fix tree for the
  reason stated, not merely because a method is new.
* GUARD (pin 7) — passes on both trees; it pins that a fully successful
  page behaves exactly as before.

The ``UnifiedInteractor.fill_input`` catch-all tightening lives in
``human_like_adapter.py`` and is deliberately out of this batch (one src
file per stage); its teeth pin belongs to that stage.
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from dataclasses import dataclass


@dataclass(frozen=True)
class _Field:
    """Hashable stand-in for a real form field.

    ApplicationWorkflow.{_fill_standard_fields,_generate_custom_answers}
    iterate ``classifications.items()``, so a field object is used as a dict
    KEY. ``types.SimpleNamespace`` is not hashable - using it as a key raised
    ``TypeError:unhashable type: 'types.SimpleNamespace'`` in six of the
    seven pins. A frozen dataclass gives us hashability plus the same
    ``getattr``-based attribute access the production code uses.
    """
    is_required: bool = False
    label: str = ""
    name: str = ""
    element_type: str = ""


from auto_apply.application.workflows.applications_workflow import (
    ApplicationsWorkflow,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan

WORKFLOW_SRC = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "application"
    / "workflows"
    / "applications_workflow.py"
)

_JOB = Job(
    title="Software Engineer",
    company="Acme Corp",
    url="https://acme.example.com/apply",
    source="test",
)


def _workflow(fill_result=True) -> ApplicationsWorkflow:
    """Build a workflow whose interaction port returns a scripted fill result."""
    interaction_port = MagicMock()
    interaction_port.fill.return_value = fill_result

    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=interaction_port,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=MagicMock(),
        text_matcher=MagicMock(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=MagicMock(),
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )


def _reset_counters(wf: ApplicationsWorkflow) -> None:
    """The counters are reset in run(); direct-method pins set them explicitly."""
    wf._fields_filled = 0
    wf._fields_classified = 0
    wf._required_fields_filled = 0
    wf._failed_required_fields = []


def _published_events(wf: ApplicationsWorkflow) -> list:
    return [c.args[0] for c in wf._event_bus.publish.call_args_list]


def _failed_payloads(wf: ApplicationsWorkflow) -> list:
    return [
        c.args[1]
        for c in wf._event_bus.publish.call_args_list
        if c.args and c.args[0] is Event.FORM_FIELD_FAILED
    ]


# ----------------------------------------------------------------------
# Pin 1 (TEETH): standard fill failure is recorded, not filled
# ----------------------------------------------------------------------


def test_standard_field_fill_failure_is_recorded_not_filled():
    wf = _workflow(fill_result=False)
    _reset_counters(wf)
    field = _Field(is_required=False)

    filled = wf._fill_standard_fields({field: "TEXT"})

    assert filled == 0, (
        f"a fill that returned False was counted as filled ({filled})"
    )
    events = _published_events(wf)
    assert Event.FORM_FIELD_FILLED not in events, (
        "FORM_FIELD_FILLED was published for a fill that returned False"
    )
    assert Event.FORM_FIELD_FAILED in events, (
        "no FORM_FIELD_FAILED was published for a fill that returned False"
    )
    assert _failed_payloads(wf)[0]["strategy"] == "semantic_filler"


# ----------------------------------------------------------------------
# Pin 2 (TEETH): custom-answer fill failure is recorded, not filled
# ----------------------------------------------------------------------


def test_custom_answer_fill_failure_is_recorded_not_filled():
    wf = _workflow(fill_result=False)
    _reset_counters(wf)
    wf._profile.work_experience = [
        SimpleNamespace(description="Built distributed systems.")
    ]
    field = _Field(is_required=False)

    filled = wf._generate_custom_answers(
        {field: "CUSTOM_OPEN_ENDED"}, SimpleNamespace(label_field_pairs={})
    )

    assert filled == 0
    events = _published_events(wf)
    assert Event.FORM_FIELD_FILLED not in events
    assert Event.FORM_FIELD_FAILED in events
    assert _failed_payloads(wf)[0]["strategy"] == "spacy_fallback"


# ----------------------------------------------------------------------
# Pin 3 (TEETH): the raw-text cover-letter branch publishes FORM_FIELD_FAILED
# ----------------------------------------------------------------------


def test_cover_letter_text_fill_failure_publishes_field_failed():
    wf = _workflow(fill_result=False)
    _reset_counters(wf)
    wf._profile.personal_info.resume_path = None
    wf._profile.personal_info.cover_letter = "Dear team, I am a strong fit."

    field = SimpleNamespace(
        element_type="text",
        name="cover_upload",
        label="Upload your cover letter",
        is_required=False,
    )
    wf._handle_file_uploads(SimpleNamespace(fields=[field]))

    failed = _failed_payloads(wf)
    assert failed, (
        "no FORM_FIELD_FAILED was published for the cover-letter text branch"
    )
    assert failed[0]["field_type"] == "COVER_LETTER"


# ----------------------------------------------------------------------
# Pin 4 (TEETH, structural): every fill() call is boolean-checked
# ----------------------------------------------------------------------


def test_every_fill_call_is_boolean_checked__structural():
    """AST pin: no bare ``self._interaction_port.fill(...)`` may survive.

    A call added later as a plain expression statement fails here, so the
    class cannot quietly come back through a fourth call site.
    """
    tree = ast.parse(WORKFLOW_SRC.read_text(encoding="utf-8", errors="ignore"))

    def _is_fill_call(node) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fill"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_interaction_port"
        )

    fill_lines: set[int] = set()
    checked_lines: set[int] = set()
    for node in ast.walk(tree):
        if _is_fill_call(node):
            fill_lines.add(node.lineno)
        if isinstance(node, ast.If):
            for inner in ast.walk(node.test):
                if _is_fill_call(inner):
                    checked_lines.add(inner.lineno)

    unchecked = sorted(fill_lines - checked_lines)
    assert not unchecked, (
        f"{len(unchecked)} unchecked interaction_port.fill() call(s) at "
        f"line(s) {unchecked} in applications_workflow.py — every fill must "
        f"be an `if` test so a failure is recorded, not filled"
    )


# ----------------------------------------------------------------------
# Pin 5 (TEETH): a failed REQUIRED field blocks submission
# ----------------------------------------------------------------------


def _drive_run_with_fields(
    wf: ApplicationsWorkflow, classifications: dict
):
    """Drive run() with the real _apply_single loop and stubbed surroundings."""
    wf._navigate_to_application = MagicMock(side_effect=lambda job, ev: ev)
    wf._detect_login_wall = MagicMock(return_value=False)
    wf._handle_interruptions = MagicMock(return_value=True)
    wf._get_form_structure_with_iframe_fallback = MagicMock(
        return_value=SimpleNamespace()
    )
    wf._classify_all_fields = MagicMock(return_value=classifications)
    wf._lazy_scroll_to_top = MagicMock()
    wf._navigate_multi_page_flow = MagicMock(return_value=False)
    wf._observe_form_structure = MagicMock()
    return wf.run(_JOB, session_id="test")


def test_failed_required_field_blocks_submission():
    wf = _workflow(fill_result=False)
    wf._submit_application = MagicMock()

    evidence = _drive_run_with_fields(
        wf, {_Field(is_required=True): "TEXT"}
    )

    wf._submit_application.assert_not_called()
    assert evidence.outcome == "FAILED_REQUIRED_FIELD"
    assert evidence.unknown_required_field
    assert evidence.submit_clicked is False


def test_optional_field_failure_does_not_block_submission():
    """Optional failures are recorded (FORM_FIELD_FAILED) but never block."""
    wf = _workflow(fill_result=False)
    wf._submit_application = MagicMock(return_value=MagicMock())

    _drive_run_with_fields(wf, {_Field(is_required=False): "TEXT"})

    assert wf._submit_application.called, (
        "an optional-field failure blocked submission — only REQUIRED field "
        "failures may stop an application"
    )


# ----------------------------------------------------------------------
# Pin 6 (TEETH): counters split — classified vs required-filled
# ----------------------------------------------------------------------


def test_counters_split_classified_vs_required():
    wf = _workflow()
    wf._interaction_port.fill.side_effect = [True, False]
    good = _Field(is_required=True, label="good")
    bad = _Field(is_required=True, label="bad")

    _drive_run_with_fields(wf, {good: "TEXT", bad: "TEXT"})

    assert wf._fields_classified == 2, (
        f"fields_classified={wf._fields_classified}, expected the 2 "
        f"classified fields, not the fill count"
    )
    assert wf._required_fields_filled == 1, (
        f"required_fields_filled={wf._required_fields_filled}, expected 1 "
        f"(the one required field that filled successfully)"
    )
    assert wf._fields_classified != wf._required_fields_filled, (
        "fields_classified and required_fields_filled are still the same "
        "counter — two concepts stamped with one shared value"
    )


# ----------------------------------------------------------------------
# Pin 7 (GUARD): a fully successful page is unchanged
# ----------------------------------------------------------------------


def test_all_success_page_is_behaviour_preserving():
    """GUARD — passes before and after: success shape must not drift."""
    wf = _workflow(fill_result=True)
    _reset_counters(wf)
    required = _Field(is_required=True)
    optional = _Field(is_required=False)

    filled = wf._fill_standard_fields({required: "TEXT", optional: "TEXT"})

    assert filled == 2
    events = _published_events(wf)
    assert events.count(Event.FORM_FIELD_FILLED) == 2
    assert Event.FORM_FIELD_FAILED not in events
    assert wf._required_fields_filled == 1