"""Pins for making the submission gate fail-LOUD as well as fail-closed.

Stage 1 made submission fail closed. That is only half safe. A default install
with no approval gate wired blocks every submission correctly — and if that
shows up nowhere but evidence records and debug logs, the run looks broken
rather than safe. An operator who believes AA is broken will "fix" it by
disabling the very check protecting them.

So a blocked submission now says so three ways: one WARNING per session
carrying the reason and the remedy, a count in the session summary, and a
remedy line in the CLI results.
"""
import logging
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.session_report import SessionReport

CLI = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "adapters"
    / "primary"
    / "cli"
    / "startup.py"
)


def _report(*outcomes) -> SessionReport:
    """A report built the way the engine builds one, via record_application."""
    report = SessionReport(session_id="test")
    for index, outcome in enumerate(outcomes):
        job = MagicMock()
        job.url = f"https://x.test/{index}"
        job.title = f"Role {index}"
        job.company = "Acme Corp"
        report.record_application(
            job=job,
            evidence=ApplicationEvidence(
                outcome=outcome, pre_submit_url=f"https://x.test/{index}"
            ),
            duration_seconds=1.0,
        )
    return report


# ─────────────────────────────────────────────────────────────────────────────
# THE SUMMARY COUNTS IT, AND DOES NOT CALL IT A FAILURE
# ─────────────────────────────────────────────────────────────────────────────


def test_blocked_submissions_are_counted():
    report = _report(
        "SUBMISSION_GATE_BLOCKED",
        "SUBMITTED",
        "SUBMISSION_GATE_BLOCKED",
        "USER_SKIPPED",
    )
    assert report.submissions_blocked_by_gate == 2


def test_blocked_submissions_are_not_counted_as_failures():
    """Guards the Stage 1 exclusion: blocked is not-attempted, not failed."""
    report = _report("SUBMISSION_GATE_BLOCKED", "SUBMISSION_GATE_BLOCKED")

    assert report.applications_failed == 0
    assert report.submissions_blocked_by_gate == 2


def test_a_clean_run_says_nothing_about_the_gate():
    """The remedy disappears entirely when nothing was blocked."""
    report = _report("SUBMITTED", "SUBMITTED")

    assert report.submissions_blocked_by_gate == 0
    assert report.gate_block_remedy == ""


def test_the_remedy_names_both_ways_out():
    """A remedy that only says 'blocked' is the problem, not the fix."""
    remedy = _report("SUBMISSION_GATE_BLOCKED").gate_block_remedy

    assert remedy
    assert "approval gate" in remedy
    assert "BEFORE_FORM_SUBMIT" in remedy
    assert "human_review_checkpoints" in remedy
    assert "not a fault" in remedy


def test_the_stats_snapshot_carries_both():
    """get_stats feeds the CLI summary and the GUI dashboard."""
    stats = _report("SUBMISSION_GATE_BLOCKED").get_stats()

    assert stats["submissions_blocked_by_gate"] == 1
    assert stats["gate_block_remedy"]
    assert stats["applications_failed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# ONE WARNING PER SESSION, NOT ONE PER JOB
# ─────────────────────────────────────────────────────────────────────────────


def _workflow():
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.session_plan import SessionPlan

    return ApplicationsWorkflow(
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


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_the_first_block_warns_loudly(caplog):
    wf = _workflow()

    with caplog.at_level(logging.DEBUG):
        wf._warn_once_about_the_gate("SUBMISSION_GATE_BLOCKED", "no approver wired")

    warnings = _warnings(caplog)
    assert len(warnings) == 1

    message = warnings[0].getMessage()
    assert "BLOCKED" in message
    assert "no approver wired" in message
    assert "human_review_checkpoints" in message
    assert "not a fault" in message


def test_a_long_run_does_not_become_a_wall_of_warnings(caplog):
    """Twenty blocked jobs, one explanation."""
    wf = _workflow()

    with caplog.at_level(logging.DEBUG):
        for _ in range(20):
            wf._warn_once_about_the_gate("SUBMISSION_GATE_BLOCKED", "no approver wired")

    assert len(_warnings(caplog)) == 1


def test_a_deliberate_user_skip_is_not_shouted_about(caplog):
    """A person choosing to skip is not a fault and needs no remedy."""
    wf = _workflow()

    with caplog.at_level(logging.DEBUG):
        wf._warn_once_about_the_gate("USER_SKIPPED", "user declined")

    assert _warnings(caplog) == []


def test_each_session_gets_its_own_explanation(caplog):
    """The flag is per-workflow, so a fresh session explains itself again."""
    with caplog.at_level(logging.DEBUG):
        _workflow()._warn_once_about_the_gate("SUBMISSION_GATE_BLOCKED", "reason")
        _workflow()._warn_once_about_the_gate("SUBMISSION_GATE_BLOCKED", "reason")

    assert len(_warnings(caplog)) == 2


# ─────────────────────────────────────────────────────────────────────────────
# THE CLI SUMMARY SHOWS IT
# ─────────────────────────────────────────────────────────────────────────────


def test_the_cli_summary_reports_blocked_separately_from_failed():
    """Structural: the results printer reads and prints both keys.

    Structural rather than behavioural because `_print_results` writes to
    stdout from inside the CLI object; the values it prints are pinned above
    where they are computed.
    """
    source = CLI.read_text(encoding="utf-8", errors="ignore")

    assert 'stats.get("submissions_blocked_by_gate"' in source
    assert 'stats.get("gate_block_remedy"' in source
    assert "Blocked (awaiting review)" in source
    assert "Applications failed" in source


def test_the_adr_records_the_pre_real_site_checklist():
    adr = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "adr"
        / "012_fail_closed_submission_gate.md"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "Pre‑real‑site checklist" in adr
    assert "Fail‑loud surfacing — DONE" in adr
    # Item 2 was OPEN when this pin was written and was closed by the occlusion
    # guard stage. The checklist is pinned; its items track the real state.
    assert "occlusion guard — DONE" in adr
