
"""Pins for per-page research records (Stage 6d).

`_observe_form_structure` ran once, after the page loop, on a `structure`
variable that had been rebound on every iteration. A five-page application
therefore contributed exactly one record — its last page — to the dataset AA
exists to produce.

Your call was one row per wizard step, page-indexed and job-tagged: a merged
record loses which fields lived on which step, and for research the per-step
structure is the interesting part.

Note what had to land first. Until Stage 6b, `SessionReport.record_application`
raised on every call, so nothing reached the dataset at all — there was no point
page-indexing rows that were never written.
"""
import ast
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.research_port import FormObservation

WORKFLOW = (
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
    url="https://acme.example.com/jobs/1",
    source="greenhouse",
)


def _workflow(observer):
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.session_plan import SessionPlan

    wf = ApplicationsWorkflow(
        profile=MagicMock(),
        browser=MagicMock(),
        perception_port=None,
        interaction_port=MagicMock(),
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
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )
    wf._research_observer = observer
    return wf


def _observations(observer):
    return [call.args[0] for call in observer.observe_form.call_args_list]


# ─────────────────────────────────────────────────────────────────────────────
# ONE ROW PER STEP
# ─────────────────────────────────────────────────────────────────────────────


def test_a_five_page_application_produces_five_records():
    """The headline: N pages, N records, not one."""
    observer = MagicMock()
    wf = _workflow(observer)

    for page in range(5):
        wf._observe_form_structure(MagicMock(), _JOB, page_index=page)

    observations = _observations(observer)
    assert len(observations) == 5
    assert [o.page_index for o in observations] == [0, 1, 2, 3, 4]


def test_a_single_page_application_still_produces_one_record_at_index_zero():
    observer = MagicMock()

    _workflow(observer)._observe_form_structure(MagicMock(), _JOB)

    observations = _observations(observer)
    assert len(observations) == 1
    assert observations[0].page_index == 0


def test_every_record_is_tagged_with_its_job():
    """Page-indexed alone is not enough — the rows must be joinable."""
    observer = MagicMock()
    wf = _workflow(observer)

    for page in range(3):
        wf._observe_form_structure(MagicMock(), _JOB, page_index=page)

    for observation in _observations(observer):
        assert observation.company_name == _JOB.company
        assert observation.job_title == _JOB.title
        assert observation.platform == _JOB.source


def test_the_page_index_defaults_to_zero():
    """Behaviour-preserving for any caller that does not pass one."""
    assert FormObservation().page_index == 0


# ─────────────────────────────────────────────────────────────────────────────
# THE OBSERVATION HAPPENS WHERE THE PAGES ARE
# ─────────────────────────────────────────────────────────────────────────────


def _loop_calls() -> set[str]:
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
            return called
    return set()


def test_the_observation_is_made_inside_the_per_page_loop():
    """Outside the loop it can only ever see the last page.

    That was the bug: `structure` is rebound each iteration, so a post-loop
    observation records the final step and silently discards the rest.
    """
    called = _loop_calls()

    assert called, "could not find the per-page loop"
    assert "_observe_form_structure" in called


def test_no_post_loop_observation_survives():
    """Exactly one call site, and it is the one inside the loop."""
    source = WORKFLOW.read_text(encoding="utf-8", errors="ignore")

    call_sites = source.count("self._observe_form_structure(")
    assert call_sites == 1, (
        f"expected a single call site inside the page loop, found {call_sites}"
    )


def test_the_index_comes_from_the_pages_navigated_counter():
    source = WORKFLOW.read_text(encoding="utf-8", errors="ignore")
    assert "page_index=self._pages_navigated" in source


# ─────────────────────────────────────────────────────────────────────────────
# DEGRADATION
# ─────────────────────────────────────────────────────────────────────────────


def test_no_research_observer_is_a_silent_no_op():
    """Research is observation; it must never be able to break a fill."""
    wf = _workflow(None)

    wf._observe_form_structure(MagicMock(), _JOB, page_index=2)


def test_an_observer_that_raises_does_not_break_the_page():
    observer = MagicMock()
    observer.observe_form.side_effect = RuntimeError("research pipeline down")

    _workflow(observer)._observe_form_structure(MagicMock(), _JOB, page_index=1)
