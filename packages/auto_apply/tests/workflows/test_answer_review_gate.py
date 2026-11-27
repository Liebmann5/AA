"""Answer review meets the submission decision at one point (docs/adr/026).

Two independent settings: whether AA may *send* without asking
(``human_review_checkpoints``), and which *answers* the person must see first
(``applications.answer_trust``). Sending without being asked never means
sending answers the person still has to see, and asking about the send
never asks twice.
"""

from unittest.mock import MagicMock

from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from tests.application.test_answer_review_and_external_steps import (
    _open_page,
    _saved_template,
)
from tests.application.test_form_engine import Form, _ctx, _engine

from .test_submission_gate import _JOB, _pausing_policy, _workflow

NEEDS = "Answers you asked to check before sending: Why this role?."


def _autonomous_policy() -> MagicMock:
    policy = MagicMock()
    policy.should_pause.return_value = False
    return policy


def _submit(wf, needs: str = NEEDS) -> ApplicationEvidence:
    return wf._submit_application(_JOB, ApplicationEvidence(), needs_person=needs)


def test_autonomous_sending_still_asks_about_answers_that_need_the_person() -> None:
    asked: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str, **kw) -> str:
        asked.append(checkpoint)
        return "submit"

    port = MagicMock()
    evidence = _submit(_workflow(interrupt_policy=_autonomous_policy(), approval_gate=gate,
                                 interaction_port=port))
    assert asked == ["ANSWER_REVIEW"]
    assert evidence.outcome != "SUBMISSION_GATE_BLOCKED"


def test_autonomous_sending_with_no_one_to_ask_sends_nothing_unseen() -> None:
    port = MagicMock()
    evidence = _submit(_workflow(interrupt_policy=_autonomous_policy(), approval_gate=None,
                                 interaction_port=port))
    port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"
    assert "still need the person" in (evidence.error_message or "")


def test_the_person_can_decline_at_the_answer_review() -> None:
    port = MagicMock()
    evidence = _submit(_workflow(interrupt_policy=_autonomous_policy(),
                                 approval_gate=lambda *a, **k: "skip",
                                 interaction_port=port))
    port.click.assert_not_called()
    assert evidence.outcome == "USER_SKIPPED"


def test_autonomous_sending_with_nothing_pending_asks_nothing() -> None:
    asked: list[str] = []

    def gate(*a, checkpoint: str = "", **k) -> str:
        asked.append(checkpoint)
        return "submit"

    _submit(_workflow(interrupt_policy=_autonomous_policy(), approval_gate=gate), needs="")
    assert asked == []


def test_when_the_send_is_asked_about_the_answers_are_not_asked_twice() -> None:
    asked: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str, **kw) -> str:
        asked.append(checkpoint)
        return "submit"

    _submit(_workflow(interrupt_policy=_pausing_policy(), approval_gate=gate))
    assert asked == ["BEFORE_FORM_SUBMIT"]


def test_the_submit_prompt_names_a_held_back_answer_once() -> None:
    form = Form()
    _open_page(form)
    result = _engine(form, sources=[_saved_template()]).run(_ctx())
    assert result.pending_reviews() == ["Why this role? *"]
    text = ApplicationsWorkflow._submit_summary(MagicMock(), _JOB, result)
    assert text.count("Why this role?") == 1, text
