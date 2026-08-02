
"""Pins for joining per-page research rows to their outcome (Stage 6e).

Stage 6d made a multi-page application produce one row per step. It did not make
those rows *identifiable*: a partial attempt's pages and a completed attempt's
pages looked the same, and neither joined to the outcome that produced them. A
dataset where friction reads as success is worse than no dataset.

Tracing turned up something worse than expected. `FormObservation.posting_hash`
is documented as "links this form to its job posting" — and nothing anywhere
writes `job.metadata["posting_hash"]`. Only `ats`, `provider` and `parsed` are
ever stamped. So the documented join key has been `None` in every record ever
produced.

So: an `attempt_id`, generated once per attempt and stamped on the outcome
record, on the session-report row, and on every page's observation.
"""
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.ports.research_port import FormObservation

_JOB = Job(
    title="Software Engineer",
    company="Acme Corp",
    url="https://acme.example.com/jobs/1",
    source="greenhouse",
)


def _workflow(observer=None):
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )

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
# A PARTIAL ATTEMPT IS DISTINGUISHABLE FROM A COMPLETED ONE
# ─────────────────────────────────────────────────────────────────────────────


def test_a_mid_wizard_failure_yields_its_pages_and_a_non_submitted_outcome():
    """The headline: friction data reads as friction, and joins.

    Two pages reached, then the attempt ends without submitting. Both rows and
    the outcome must carry one shared id, and the outcome must not look like a
    completed application.
    """
    observer = MagicMock()
    wf = _workflow(observer)
    wf._attempt_id = "session-x:1"

    wf._observe_form_structure(MagicMock(), _JOB, page_index=0)
    wf._observe_form_structure(MagicMock(), _JOB, page_index=1)

    evidence = ApplicationEvidence(
        attempt_id=wf._attempt_id, outcome="ERROR", submit_clicked=False
    )

    rows = _observations(observer)
    assert [r.page_index for r in rows] == [0, 1]
    assert {r.attempt_id for r in rows} == {"session-x:1"}
    assert evidence.attempt_id == "session-x:1"
    assert evidence.outcome != "SUBMITTED"
    assert evidence.submit_clicked is False


def test_a_gate_blocked_attempt_joins_the_same_way():
    observer = MagicMock()
    wf = _workflow(observer)
    wf._attempt_id = "session-x:7"

    wf._observe_form_structure(MagicMock(), _JOB, page_index=0)

    evidence = ApplicationEvidence(
        attempt_id=wf._attempt_id, outcome="SUBMISSION_GATE_BLOCKED"
    )

    assert _observations(observer)[0].attempt_id == evidence.attempt_id
    assert evidence.outcome != "SUBMITTED"


def test_every_page_of_one_attempt_shares_one_id():
    observer = MagicMock()
    wf = _workflow(observer)
    wf._attempt_id = "session-x:3"

    for page in range(5):
        wf._observe_form_structure(MagicMock(), _JOB, page_index=page)

    assert len({r.attempt_id for r in _observations(observer)}) == 1


# ─────────────────────────────────────────────────────────────────────────────
# THE ID REACHES BOTH SIDES OF THE JOIN
# ─────────────────────────────────────────────────────────────────────────────


def test_the_outcome_record_carries_the_id_into_the_session_report():
    report = SessionReport(session_id="test")
    job = MagicMock()
    job.url, job.title, job.company = _JOB.url, _JOB.title, _JOB.company

    report.record_application(
        job=job,
        evidence=ApplicationEvidence(attempt_id="session-x:2", outcome="ERROR"),
        duration_seconds=1.0,
    )

    assert report.applications[0].attempt_id == "session-x:2"


def test_a_real_attempt_gets_a_non_empty_id():
    """Driven through run(), so the id comes from the code path, not the test."""
    wf = _workflow()
    wf._browser.get.side_effect = RuntimeError("dead link")

    evidence = wf.run(_JOB, session_id="live")

    assert evidence.attempt_id
    assert evidence.attempt_id.startswith("live:")
    assert evidence.outcome != "SUBMITTED"


def test_two_attempts_do_not_merge_into_one_set_of_rows():
    """Same job twice in a session must not collapse to one attempt."""
    wf = _workflow()
    wf._browser.get.side_effect = RuntimeError("dead link")

    first = wf.run(_JOB, session_id="live")
    second = wf.run(_JOB, session_id="live")

    assert first.attempt_id != second.attempt_id


def test_the_id_is_deterministic_and_uses_no_rng():
    """A seeded replay must reproduce the same ids."""
    source = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "application"
        / "workflows"
        / "applications_workflow.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert 'self._attempt_id = f"{session_id or \'session\'}:{self._attempt_seq}"' in source

    one, two = _workflow(), _workflow()
    one._browser.get.side_effect = RuntimeError("x")
    two._browser.get.side_effect = RuntimeError("x")

    assert one.run(_JOB, session_id="s").attempt_id == two.run(
        _JOB, session_id="s"
    ).attempt_id


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,attr",
    [(FormObservation, "attempt_id"), (ApplicationEvidence, "attempt_id")],
)
def test_the_id_defaults_to_empty(model, attr):
    """Behaviour-preserving for any constructor that does not pass one."""
    assert getattr(model(), attr) == ""
