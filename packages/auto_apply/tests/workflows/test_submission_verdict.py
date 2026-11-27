"""What AA concludes after clicking Submit (live run 2026-11-26).

"The address changed" is measured from the form's own address at the click,
never from ``job.url``: for jobs found through a search engine that is a
redirect link, so every page "differs" from it and every click read as
"probably submitted".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auto_apply.application.workflows.applications_workflow import _left_the_form
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job

from .test_submission_gate import _workflow

FORM = "https://apply.workable.com/acme/j/ABC123/apply/"
REDIRECT_JOB = Job(title="Engineer", company="Acme", source="google",
                   url="https://www.google.com/goto?url=CAESxyz&gsessionid=q")


def _autonomous() -> MagicMock:
    policy = MagicMock()
    policy.should_pause.return_value = False
    return policy


def _after_click(url: str, text: str) -> ApplicationEvidence:
    port = MagicMock()
    wf = _workflow(interrupt_policy=_autonomous(), interaction_port=port)
    wf._browser.current_url = FORM
    wf._browser.page_source = f"<html><body><main>{text}</main></body></html>"
    wf._browser.title = "Apply"

    def click(*a, **k):
        wf._browser.current_url = url

    port.click.side_effect = click
    return wf._submit_application(REDIRECT_JOB, ApplicationEvidence())


def test_same_form_address_and_no_confirmation_is_ambiguous_not_submitted() -> None:
    ev = _after_click(FORM, "Please fill in the required fields.")
    assert (ev.outcome, ev.confidence) == ("AMBIGUOUS", 0.35)


def test_moving_off_the_form_without_a_confirmation_is_probably_submitted() -> None:
    ev = _after_click("https://apply.workable.com/acme/j/ABC123/apply/success", "Done")
    assert (ev.outcome, ev.confidence) == ("PROBABLY_SUBMITTED", 0.65)


def test_a_confirmation_on_the_same_address_is_submitted() -> None:
    ev = _after_click(FORM, "Thank you for applying! We have received your application.")
    assert ev.outcome == "SUBMITTED"


@pytest.mark.parametrize(("before", "after", "left"), [
    (FORM, FORM, False),
    (FORM, FORM.rstrip("/"), False),
    (FORM, FORM + "?utm=x#top", False),
    (FORM, "https://apply.workable.com/acme/j/ABC123/apply/success", True),
    (FORM, "https://www.acme.example/thanks", True),
    ("", FORM, False),
    (FORM, "", False),
])
def test_left_the_form(before: str, after: str, left: bool) -> None:
    assert _left_the_form(before, after) is left
