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


def _gated_html() -> str:
    """A Cloudflare-style interstitial, by measured shape: challenge markup,
    no form, almost no visible text, and a non-English title (the verdict
    must not read the title at all)."""
    return (
        "<html><head><title>Einen Moment bitte</title>"
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js">'
        "</script></head><body>"
        '<input type="hidden" name="cf-turnstile-response" value=""/>'
        "<p>Checking your browser before continuing.</p>"
        "</body></html>"
    )


def _posting_html() -> str:
    """An ordinary rendered job posting, by measured shape: 2+ forms, real
    visible text, and a stray 'recaptcha' token in an inline script and a
    comment — exactly the false-positive shape the substring scan fell for."""
    body_text = "Software Engineer role. Join our team. " * 40
    return (
        "<html><head><title>Registered Nurse</title>"
        "<script>var cfg = { captcha: 'recaptcha-site-key' };</script>"
        "</head><body>"
        "<form id='search'><input name='q'/></form>"
        "<form id='alert'><input name='email'/></form>"
        f"<p>{body_text}</p>"
        "<!-- recaptcha -->"
        "</body></html>"
    )


def test_run_records_captcha_blocked_and_enqueues_no_captcha_task(
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
    """A gated page with NO gate wired records CAPTCHA_BLOCKED — and no
    hand-off WorkUnit is enqueued (the late, wrong-page escalation is gone)."""
    mock_browser.page_source = _gated_html()

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

    assert bool(result) is False
    assert result.outcome == "CAPTCHA_BLOCKED"
    assert result.captcha_encountered is True
    assert "no human-review gate" in (result.error_message or "")
    assert "no-page-content" in result.challenge_signals

    # No hand-off task of any kind was enqueued.
    for call in mock_task_queue.queue_task.call_args_list:
        task = call.args[0]
        assert getattr(task, "task_type", None) is not TaskType.HANDLE_CAPTCHA


def test_challenge_pauses_in_place_and_solved_continues_same_attempt(
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
    """Teeth (the pause): the gate is asked BEFORE any outcome is recorded,
    while the browser is still on the challenge page; 'solved' re-checks and
    the SAME attempt continues (not CAPTCHA_BLOCKED, captcha_encountered=True)."""
    mock_browser.page_source = _gated_html()
    mock_browser.current_url = sample_job.url

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

    def _human_solves_it(*args, **kwargs):
        # The gate was asked before ANY application outcome was published...
        terminal_events = {Event.APPLICATION_SUBMITTED, Event.APPLICATION_FAILED}
        assert not any(
            e in terminal_events for e, _ in mock_event_bus.published_events
        ), "an outcome was recorded before the human was asked"
        # ...and the browser was never navigated away from the challenge page.
        assert mock_browser.current_url == sample_job.url
        # The human solves it: the page becomes the posting.
        mock_browser.page_source = _posting_html()
        return "solved"

    gate = MagicMock(side_effect=_human_solves_it)
    wf.set_approval_gate(gate)

    result = wf.run(sample_job)

    assert gate.call_count == 1
    _, kwargs = gate.call_args
    assert kwargs.get("checkpoint") == "CAPTCHA_PRESENTED"
    # The attempt continued past the challenge: the outcome is whatever the
    # rest of the pipeline produced, NOT CAPTCHA_BLOCKED.
    assert result.outcome != "CAPTCHA_BLOCKED"
    assert result.captcha_encountered is True
    for call in mock_task_queue.queue_task.call_args_list:
        task = call.args[0]
        assert getattr(task, "task_type", None) is not TaskType.HANDLE_CAPTCHA


def test_challenge_skip_records_blocked_after_asking(
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
    """'skip' (or a timeout, which returns 'skip') records CAPTCHA_BLOCKED —
    after the human was asked, not before."""
    mock_browser.page_source = _gated_html()
    mock_browser.current_url = sample_job.url

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
    gate = MagicMock(return_value="skip")
    wf.set_approval_gate(gate)

    result = wf.run(sample_job)

    assert gate.call_count == 1
    assert result.outcome == "CAPTCHA_BLOCKED"
    assert result.captcha_encountered is True
    assert "skip" in (result.error_message or "")


def test_challenge_without_gate_records_blocked_with_honest_message(
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
    """No gate wired: AA records CAPTCHA_BLOCKED, says why, and never hangs."""
    mock_browser.page_source = _gated_html()
    mock_browser.current_url = sample_job.url

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

    assert result.outcome == "CAPTCHA_BLOCKED"
    assert "no human-review gate" in (result.error_message or "")


def test_registered_nurse_title_is_not_a_login_wall(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
):
    """Teeth: a posting titled 'Registered Nurse' is not a login wall.
    Fails against the old title-substring check ('register')."""
    mock_browser.title = "Registered Nurse"
    mock_browser.current_url = sample_job.url
    mock_browser.page_source = _posting_html()

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
    )

    assert wf._detect_login_wall(sample_job) is False


def test_password_form_page_is_a_login_wall(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
):
    """A small page whose main content is a password form IS a login wall."""
    mock_browser.title = "Account"
    mock_browser.current_url = sample_job.url
    mock_browser.page_source = (
        "<html><body>"
        "<form method='post'>"
        "<input name='user'/><input type='password' name='pw'/>"
        "</form>"
        "<p>Sign in to continue.</p>"
        "</body></html>"
    )

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
    )

    assert wf._detect_login_wall(sample_job) is True


def test_submit_gate_receives_checkpoint_name_not_url(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
):
    """Guard: the approval gate receives 'BEFORE_FORM_SUBMIT', never a URL."""
    policy = MagicMock()
    policy.should_pause.return_value = True
    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        interrupt_policy=policy,
    )
    gate = MagicMock(return_value="submit")
    wf.set_approval_gate(gate)

    authorized, _, _ = wf._authorize_submission(sample_job)

    assert authorized is True
    _, kwargs = gate.call_args
    assert kwargs.get("checkpoint") == "BEFORE_FORM_SUBMIT"


def test_submit_input_element_is_found_as_submit_control(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
    mock_interaction_port,
):
    """TEETH (deliverable 2): <input type="submit" value="Submit application">
    is found as the submit control. The old buttons-only search — and the
    .text label reader, which is empty on an input — could not see it."""
    submit_input = MagicMock()
    submit_input.text = ""
    submit_input.get_attribute = lambda name: (
        "Submit application" if name == "value" else None
    )
    mock_browser.find_elements.return_value = [submit_input]
    mock_browser.current_url = sample_job.url
    mock_browser.title = ""
    mock_browser.page_source = "<html><body>thanks</body></html>"

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        interaction_port=mock_interaction_port,
    )
    evidence = ApplicationEvidence(
        pre_submit_url=sample_job.url,
        page_title_before=sample_job.title,
    )

    result = wf._submit_application(sample_job, evidence)

    assert result.submit_button_found is True
    assert result.submit_button_text == "Submit application"
    mock_interaction_port.click.assert_called_once_with(submit_input, irreversible=True)


def test_next_anchor_is_found_by_multi_page_walk(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
    mock_interaction_port,
):
    """TEETH (deliverable 3): an <a> Next is found — invisible to the old
    buttons-only search."""
    next_anchor = MagicMock()
    next_anchor.text = "Next"
    next_anchor.get_attribute = lambda name: None
    mock_browser.find_elements.return_value = [next_anchor]

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        interaction_port=mock_interaction_port,
    )

    assert wf._navigate_multi_page_flow() is True
    mock_interaction_port.click.assert_called_once_with(next_anchor)
    assert wf._pages_navigated == 1


def test_next_role_button_is_found_by_multi_page_walk(
    mock_profile,
    sample_job,
    mock_event_bus,
    mock_job_repo,
    mock_task_queue,
    mock_text_matcher,
    mock_browser,
    mock_interaction_port,
):
    """TEETH (deliverable 3): a [role=button] Next is found too."""
    next_button = MagicMock()
    next_button.text = "Continue"
    next_button.get_attribute = lambda name: (
        "button" if name == "role" else None
    )
    mock_browser.find_elements.return_value = [next_button]

    wf = _make_workflow(
        profile=mock_profile,
        event_bus=mock_event_bus,
        job_repo=mock_job_repo,
        task_queue=mock_task_queue,
        text_matcher=mock_text_matcher,
        browser=mock_browser,
        interaction_port=mock_interaction_port,
    )

    assert wf._navigate_multi_page_flow() is True
    mock_interaction_port.click.assert_called_once_with(next_button)
    assert wf._pages_navigated == 1


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