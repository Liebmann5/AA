
"""Pins for the fail-closed submission gate (Stage 1).

Stage 1 restores ``interaction_port.click()``, which means the submit click at
``ApplicationsWorkflow._submit_application`` starts landing on real pages for
the first time.  The pre-submit human-in-the-loop check that guards it was
FAIL-OPEN in four distinct ways — submission proceeded when:

    1. the interrupt policy asked for a pause but no approval gate was wired
       (``if self._approval_gate is not None:`` simply fell through),
    2. ``should_pause`` raised (swallowed at debug level),
    3. the gate itself raised (same swallow),
    4. the gate returned anything that was not the literal ``"skip"``.

None of that mattered while clicking was broken.  All of it matters the moment
clicking works, so these pins hold submission closed unless it is explicitly
authorised, and they hold the checkpoint contract (a real
``ApplicationContext``, not a fabricated stand-in object).

Authorisation is exactly one of:
    * the user's configured policy does not ask for a pre-submit pause
      (``human_review_checkpoints`` without ``BEFORE_FORM_SUBMIT`` — an
      explicit, sovereign user choice), or
    * a wired approval gate returned the literal approval token.

Everything else records evidence and does not click.
"""
import pathlib

from unittest.mock import MagicMock

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.ports.interrupt_policy_port import (
    ApplicationContext,
    Checkpoint,
    ProfileBasedInterruptPolicy,
)

_JOB = Job(
    title="Software Engineer",
    company="Acme Corp",
    url="https://acme.example.com/jobs/123",
    source="test",
)


def _workflow(
    *,
    interrupt_policy,
    approval_gate=None,
    interaction_port=None,
    text_matcher=None,
) -> ApplicationsWorkflow:
    """Build a workflow with only what _submit_application touches."""
    if interaction_port is None:
        interaction_port = MagicMock()
        interaction_port.click.return_value = None

    if text_matcher is None:
        text_matcher = MagicMock()
        # Any button text scores above the 0.7 submit threshold.
        text_matcher.find_best_match.return_value = ("submit application", 0.95)

    browser = MagicMock()
    browser.current_url = _JOB.url
    browser.page_source = "<html><body>thank you for applying</body></html>"
    browser.title = "Applied"

    wf = ApplicationsWorkflow(
        profile=MagicMock(),
        browser=browser,
        perception_port=None,
        interaction_port=interaction_port,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=text_matcher,
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=interrupt_policy,
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )
    if approval_gate is not None:
        wf.set_approval_gate(approval_gate)

    # One clickable submit button is always available, so any refusal to submit
    # is the gate's decision and never "no button found".
    wf._get_clickable_elements = lambda: [MagicMock(text="Submit Application")]
    return wf


def _pausing_policy() -> MagicMock:
    policy = MagicMock()
    policy.should_pause.return_value = True
    return policy


def _submit(wf) -> ApplicationEvidence:
    return wf._submit_application(_JOB, ApplicationEvidence())


# ─────────────────────────────────────────────────────────────────────────────
# Fail-closed paths — the gate is unsatisfied, so submit must not fire
# ─────────────────────────────────────────────────────────────────────────────


def test_submit_does_not_fire_when_a_pause_is_required_and_no_gate_is_wired():
    """The headline pin: no approval gate → no submission.

    ``SessionController._wire_approval_gate`` binds the gate inside a
    try/except that logs "HITL disabled" and continues, so an unwired gate is a
    reachable production state, not a hypothetical.
    """
    interaction_port = MagicMock()
    wf = _workflow(
        interrupt_policy=_pausing_policy(),
        approval_gate=None,
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    interaction_port.click.assert_not_called()
    assert evidence.submit_clicked is False
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_submit_does_not_fire_when_the_policy_raises():
    """A policy error is not consent. Fail closed, record why."""
    policy = MagicMock()
    policy.should_pause.side_effect = RuntimeError("policy exploded")
    interaction_port = MagicMock()

    wf = _workflow(
        interrupt_policy=policy,
        approval_gate=lambda *a, **k: "submit",
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    interaction_port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_submit_does_not_fire_when_the_gate_raises():
    """A gate error is not consent either."""
    def _exploding_gate(*args, **kwargs):
        raise RuntimeError("gate exploded")

    interaction_port = MagicMock()
    wf = _workflow(
        interrupt_policy=_pausing_policy(),
        approval_gate=_exploding_gate,
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    interaction_port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_submit_does_not_fire_on_an_unrecognised_gate_answer():
    """Only the explicit approval token authorises.

    A UI that is dismissed, times out oddly, or returns None must never be read
    as approval.  The old code compared against "skip" and treated everything
    else — including None — as consent.
    """
    for answer in (None, "", "cancel", "later", "SUBMIT!"):
        interaction_port = MagicMock()
        wf = _workflow(
            interrupt_policy=_pausing_policy(),
            approval_gate=lambda *a, **k: answer,
            interaction_port=interaction_port,
        )

        evidence = _submit(wf)

        interaction_port.click.assert_not_called()
        assert evidence.outcome == "SUBMISSION_GATE_BLOCKED", (
            f"gate answer {answer!r} was treated as authorisation"
        )


def test_user_declining_is_recorded_as_user_skipped_not_as_a_gate_block():
    """A deliberate human "skip" is a different research signal from a fault."""
    interaction_port = MagicMock()
    wf = _workflow(
        interrupt_policy=_pausing_policy(),
        approval_gate=lambda *a, **k: "skip",
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    interaction_port.click.assert_not_called()
    assert evidence.outcome == "USER_SKIPPED"


# ─────────────────────────────────────────────────────────────────────────────
# Authorised paths — submission proceeds
# ─────────────────────────────────────────────────────────────────────────────


def test_submit_fires_once_when_the_gate_approves():
    interaction_port = MagicMock()
    interaction_port.click.return_value = None

    wf = _workflow(
        interrupt_policy=_pausing_policy(),
        approval_gate=lambda *a, **k: "submit",
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    assert interaction_port.click.call_count == 1
    assert evidence.submit_clicked is True


def test_submit_fires_when_the_user_configured_no_pre_submit_pause():
    """User sovereignty: an explicit no-pause policy is a real authorisation.

    This is also the path every pre-existing workflow test takes (their policy
    mock returns should_pause=False), so the gate is behaviour-preserving for
    the current suite.
    """
    policy = MagicMock()
    policy.should_pause.return_value = False
    interaction_port = MagicMock()
    interaction_port.click.return_value = None

    wf = _workflow(interrupt_policy=policy, interaction_port=interaction_port)

    evidence = _submit(wf)

    assert interaction_port.click.call_count == 1
    assert evidence.submit_clicked is True


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint contract
# ─────────────────────────────────────────────────────────────────────────────


def test_the_policy_receives_a_real_application_context():
    """The port defines a frozen ApplicationContext; the caller fabricated one.

    ``ctx = type("ctx", (), {"job": job})()`` satisfied nothing: a policy that
    reads ``ctx.url`` or ``ctx.company`` would raise, and the raise was
    swallowed straight into an unauthorised submit.
    """
    policy = _pausing_policy()
    wf = _workflow(
        interrupt_policy=policy,
        approval_gate=lambda *a, **k: "submit",
    )

    _submit(wf)

    checkpoint, ctx = policy.should_pause.call_args[0]
    assert checkpoint is Checkpoint.BEFORE_FORM_SUBMIT
    assert isinstance(ctx, ApplicationContext)
    assert ctx.url == _JOB.url
    assert ctx.job_title == _JOB.title
    assert ctx.company == _JOB.company


def test_no_fabricated_checkpoint_contexts_remain_in_the_workflow():
    """Structural: every checkpoint call site uses the real context type."""
    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "application"
        / "workflows"
        / "applications_workflow.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert 'type("ctx"' not in source, (
        "a fabricated checkpoint context object is still being passed to the "
        "interrupt policy"
    )



def test_a_profile_that_opted_out_of_pre_submit_review_still_submits():
    """Sovereignty pin, built from the real policy — not a mock.

    A user whose ``human_review_checkpoints`` omits BEFORE_FORM_SUBMIT has
    deliberately chosen autonomous submission. Fail-closed must catch errors,
    denials, a missing approver and None — and must never override that choice.

    The policy here is the shipped ProfileBasedInterruptPolicy constructed
    exactly as the composition root constructs it, from the profile's
    checkpoint list, with NO approval gate wired: the strictest possible
    version of "would the gate block this user?"
    """
    policy = ProfileBasedInterruptPolicy(["ON_SUSPICIOUS_REDIRECT"])
    assert policy.should_pause(Checkpoint.BEFORE_FORM_SUBMIT, None) is False

    interaction_port = MagicMock()
    interaction_port.click.return_value = None

    wf = _workflow(
        interrupt_policy=policy,
        approval_gate=None,
        interaction_port=interaction_port,
    )

    evidence = _submit(wf)

    assert interaction_port.click.call_count == 1, (
        "the gate blocked a user who deliberately opted out of pre-submit review"
    )
    assert evidence.submit_clicked is True
    assert evidence.outcome != "SUBMISSION_GATE_BLOCKED"

def test_the_shipped_default_policy_asks_for_a_pre_submit_pause():
    """Guard (passes before and after): the default is review-before-submit.

    Combined with the no-gate pin above, this is what makes the safe default
    safe — a fresh install with no HITL UI wired cannot auto-submit.
    """
    assert (
        Checkpoint.BEFORE_FORM_SUBMIT
        in ProfileBasedInterruptPolicy.DEFAULT_CHECKPOINTS
    )
