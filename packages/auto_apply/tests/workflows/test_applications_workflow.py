"""Tests for ApplicationsWorkflow.

Covers:
    - Happy path: run() returns True when form is submitted successfully.
    - Navigation failure: run() returns False when browser navigation fails.
    - CAPTCHA detection: workflow enqueues a CAPTCHA WorkUnit and returns False.
    - Graceful degradation: no browser, no perception port, no optional components.
    - Browser lease is acquired when provided.
"""
import pytest
from unittest.mock import MagicMock, patch

from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.work_unit import TaskType
from auto_apply.domain.models.application_evidence import ApplicationEvidence


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
    browser_lease=None,
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
        browser_lease=browser_lease,
        plan=SessionPlan(session_id="test"),
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
    fake_evidence = ApplicationEvidence(outcome="SUBMITTED", confidence=0.95)
    with patch.object(wf, "_submit_application", return_value=fake_evidence):
        result = wf.run(sample_job)

    # run() returns a structured ApplicationEvidence; truthiness delegates to
    # is_likely_success (see ApplicationEvidence.__bool__).
    assert bool(result) is True
    assert result.outcome == "SUBMITTED"

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

    # _navigate_to_application returns an ApplicationEvidence (see _apply_single,
    # which reads evidence.outcome on the return value) — patch it to simulate a
    # failed navigation the same way the real method would report one.
    failed_evidence = ApplicationEvidence(
        pre_submit_url=sample_job.url,
        page_title_before=sample_job.title,
        outcome="FAILED_NAVIGATION",
        confidence=0.95,
    )
    with patch.object(wf, "_navigate_to_application", return_value=failed_evidence):
        result = wf.run(sample_job)

    # run() returns a structured ApplicationEvidence; truthiness delegates to
    # is_likely_success (see ApplicationEvidence.__bool__).
    assert bool(result) is False
    assert result.outcome == "FAILED_NAVIGATION"

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

    # run() returns a structured ApplicationEvidence; truthiness delegates to
    # is_likely_success (see ApplicationEvidence.__bool__).
    assert bool(result) is False
    assert result.outcome == "CAPTCHA_BLOCKED"

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
        plan=SessionPlan(session_id="test"),
    )

    # Must not raise — degrades gracefully to a structured failure evidence,
    # not a crash. run() returns ApplicationEvidence (see its docstring); the
    # graceful-degradation contract is "produces a valid, falsy evidence
    # object", not "produces a bool".
    result = wf.run(sample_job)

    assert isinstance(result, ApplicationEvidence)
    assert bool(result) is False


def test_browser_lease_is_acquired_during_run(
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
    """When browser_lease is supplied, its acquire() context is entered during run()."""
    mock_lease = MagicMock()
    # Configure acquire() to return a context manager mock
    mock_lease.acquire.return_value.__enter__ = MagicMock()
    mock_lease.acquire.return_value.__exit__ = MagicMock()

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        perception_port=mock_perception_port,
        interaction_port=mock_interaction_port,
        browser_lease=mock_lease,
    )

    # Stub the submission step so the full run path executes
    fake_evidence = ApplicationEvidence(outcome="SUBMITTED", confidence=0.95)
    with patch.object(wf, "_submit_application", return_value=fake_evidence):
        wf.run(sample_job)

    # The lease should have been used to wrap the core logic
    assert mock_lease.acquire.called, "Browser lease was not acquired during run()"