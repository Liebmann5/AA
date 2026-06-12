"""Tests for ApplicationsWorkflow.

Covers:
    - Happy path: run() returns True when form is submitted successfully.
    - Navigation failure: run() returns False when browser navigation fails.
    - CAPTCHA detection: workflow enqueues a CAPTCHA WorkUnit and returns False.
    - Graceful degradation: no browser, no perception port, no optional components.
"""
import pytest
from unittest.mock import MagicMock, patch

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.work_unit import TaskType


def _make_workflow(
    profile,
    event_bus,
    job_repo,
    task_queue,
    text_matcher,
    browser=None,
    perception_port=None,
    interaction_port=None,
    interrupt_policy=None,
) -> ApplicationsWorkflow:
    if interrupt_policy is None:
        interrupt_policy = MagicMock()
        interrupt_policy.should_pause.return_value = False

    return ApplicationsWorkflow(
        profile=profile,
        browser=browser,
        perception_port=perception_port,
        interaction_port=interaction_port,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=text_matcher,
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=job_repo,
        task_queue=task_queue,
        event_bus=event_bus,
        interrupt_policy=interrupt_policy,
        text_generation_port=None,
    )


# ─────────────────────────────────────────────────────────────────────────────


def test_run_returns_true_on_submission(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
    mock_perception_port,
    mock_interaction_port,
):
    """run() returns True and publishes APPLICATION_SUBMITTED on successful submission."""
    # Stub the submission step so it returns True
    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        perception_port=mock_perception_port,
        interaction_port=mock_interaction_port,
    )

    # Patch _submit_application to simulate a successful submit
    with patch.object(wf, "_submit_application", return_value=True):
        result = wf.run(sample_job)

    assert result is True

    published_events = [e for e, _ in mock_event_bus.published_events]
    assert Event.APPLICATION_SUBMITTED in published_events


def test_run_returns_false_on_navigation_failure(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """run() returns False and publishes APPLICATION_FAILED when navigation fails."""
    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=None,   # no browser → navigation will fail
    )

    # Patch _navigate_to_application to simulate failure
    with patch.object(wf, "_navigate_to_application", return_value=False):
        result = wf.run(sample_job)

    assert result is False

    published_events = [e for e, _ in mock_event_bus.published_events]
    assert Event.APPLICATION_FAILED in published_events


def test_run_handles_captcha_by_enqueuing_task(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
    mock_perception_port,
    mock_interaction_port,
):
    """When CAPTCHA is detected via page_source, a HANDLE_CAPTCHA WorkUnit is enqueued."""
    # Simulate a page that contains reCAPTCHA — the workflow detects this in page_source
    mock_browser.page_source = (
        "<html><body>"
        '<div class="g-recaptcha">recaptcha challenge</div>'
        "</body></html>"
    )

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        perception_port=mock_perception_port,
        interaction_port=mock_interaction_port,
    )

    result = wf.run(sample_job)

    assert result is False

    # A HANDLE_CAPTCHA WorkUnit should have been enqueued by _handle_interruptions
    enqueued_tasks = [
        call.args[0] for call in mock_task_queue.queue_task.call_args_list
        if hasattr(call.args[0], "task_type")
    ]
    captcha_tasks = [t for t in enqueued_tasks if t.task_type == TaskType.HANDLE_CAPTCHA]
    assert len(captcha_tasks) >= 1


def test_handles_missing_optional_dependency_gracefully(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """Workflow runs without crash when all optional components are None."""
    wf = ApplicationsWorkflow(
        profile=mock_profile,
        browser=None,
        perception_port=None,
        interaction_port=None,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=mock_text_matcher,
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        event_bus=mock_event_bus,
        interrupt_policy=MagicMock(should_pause=MagicMock(return_value=False)),
        text_generation_port=None,
    )

    # Must not raise — degrades gracefully to APPLICATION_FAILED
    result = wf.run(sample_job)

    assert isinstance(result, bool)
