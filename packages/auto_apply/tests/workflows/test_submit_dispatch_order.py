"""The submit path's Phase 0 write order (AA_ENGINE_MATH.md §2–§3a; P0-3/P0-4).

Arm (journal ARMED, flushed and read back) → mint the token → re-check the
approved values → consume → click with the token's target → settle (ACKED /
UNKNOWN / NOT_SENT, then the database, then DONE). TEETH: every pin fails
against the pre-Phase-0 workflow, which clicked with no journal and no token.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap
from unittest.mock import MagicMock

from auto_apply.adapters.secondary.interaction.human_like_adapter import ClickFailedError
from auto_apply.application.services.data_processing import submit_intent_journal as sij
from auto_apply.application.services.data_processing.submit_intent_journal import (
    SubmitIntentJournal,
)
from auto_apply.application.services.form_engine import CLICKED, StepRecord
from auto_apply.application.services.profile_lock import ProfileLock
from auto_apply.application.workflows import applications_workflow as aw
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job_key import compute_job_key
from auto_apply.domain.models.submission_attempt import AttemptState
from auto_apply.domain.services.submit_token import ControlIdentity

from .test_submission_gate import _JOB, _workflow

KEY = compute_job_key(_JOB).as_string


def _autonomous() -> MagicMock:
    policy = MagicMock()
    policy.should_pause.return_value = False
    return policy


def _journal(tmp_path: pathlib.Path, *, synced: str | None = None) -> SubmitIntentJournal:
    return SubmitIntentJournal(tmp_path / "p.journal", "p", ProfileLock(tmp_path / "p.lock"),
                               synced_root=synced)


def _reread(tmp_path: pathlib.Path) -> SubmitIntentJournal:
    return SubmitIntentJournal(tmp_path / "p.journal", "p", ProfileLock(tmp_path / "re.lock"))


def _wf(tmp_path, *, port=None, journal="default"):
    wf = _workflow(interrupt_policy=_autonomous(), interaction_port=port)
    wf._submit_journal = _journal(tmp_path) if journal == "default" else journal
    wf._current_job = _JOB
    return wf


def test_the_armed_record_is_durable_before_the_click(tmp_path) -> None:
    seen: list[list[AttemptState]] = []
    port = MagicMock()
    port.click.side_effect = lambda *a, **k: seen.append(
        [v.state for v in _reread(tmp_path).unresolved()])
    wf = _wf(tmp_path, port=port)
    wf._submit_application(_JOB, ApplicationEvidence())
    assert seen and seen[0] and seen[0][0] in (AttemptState.ARMED, AttemptState.DISPATCHING)


def test_no_journal_means_no_click(tmp_path) -> None:
    port = MagicMock()
    wf = _wf(tmp_path, port=port, journal=None)
    evidence = wf._submit_application(_JOB, ApplicationEvidence())
    port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_an_arm_refusal_means_no_click(tmp_path) -> None:
    port = MagicMock()
    wf = _wf(tmp_path, port=port, journal=_journal(tmp_path, synced="OneDrive: x"))
    evidence = wf._submit_application(_JOB, ApplicationEvidence())
    port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"
    assert "synced" in (evidence.error_message or "")


def test_the_click_carries_the_token_target(tmp_path) -> None:
    port = MagicMock()
    wf = _wf(tmp_path, port=port)
    wf._navigation = MagicMock()
    wf._navigation.control_identity.return_value = ControlIdentity(tag="button", name="go")
    wf._submit_application(_JOB, ApplicationEvidence())
    assert port.click.call_args.kwargs["expect"] == ControlIdentity(tag="button", name="go")


def test_a_value_changed_after_approval_is_not_sent(tmp_path) -> None:
    """§3a: what the person approved, re-read just before the click."""
    port = MagicMock()
    wf = _wf(tmp_path, port=port)
    engine = MagicMock()
    engine.written_values.return_value = []
    engine.current_values.side_effect = [[("Email *", "email", "ada@example.org")],
                                         [("Email *", "email", "eve@example.org")]]
    wf._form_engine = engine
    evidence = wf._submit_application(_JOB, ApplicationEvidence(), final_step=MagicMock())
    port.click.assert_not_called()
    assert evidence.outcome == "ERROR" and "changed an answer" in evidence.error_message


def test_a_seen_submission_settles_acked_then_the_database_then_done(tmp_path) -> None:
    wf = _wf(tmp_path)
    evidence = wf._submit_application(_JOB, ApplicationEvidence())
    assert evidence.outcome == "SUBMITTED"
    settled = wf._settle_submit_attempt(evidence)
    assert settled.outcome == "SUBMITTED"
    kwargs = wf._task_queue.record_application_permanently.call_args.kwargs
    assert kwargs["outcome"] == "SUBMITTED" and kwargs["attempt_id"]
    reread = _reread(tmp_path)
    assert reread.unresolved() == [] and reread.blocks(KEY, _JOB.url)


def test_a_click_that_raised_mid_ladder_settles_unknown(tmp_path) -> None:
    port = MagicMock()
    port.click.side_effect = ClickFailedError("aborted after a rung raised", rung="keyboard")
    wf = _wf(tmp_path, port=port)
    evidence = wf._settle_submit_attempt(wf._submit_application(_JOB, ApplicationEvidence()))
    assert evidence.outcome == "UNKNOWN"
    assert wf._task_queue.record_application_permanently.call_args.kwargs["outcome"] == "UNKNOWN"
    assert _reread(tmp_path).blocks(KEY, _JOB.url)


def test_a_refusal_before_any_rung_settles_not_sent_and_stays_retriable(tmp_path) -> None:
    port = MagicMock()
    port.click.side_effect = ClickFailedError("click target not reachable: occluded",
                                              rung="probe")
    wf = _wf(tmp_path, port=port)
    evidence = wf._settle_submit_attempt(wf._submit_application(_JOB, ApplicationEvidence()))
    assert evidence.outcome == "ERROR"
    wf._task_queue.record_application_permanently.assert_not_called()
    assert not _reread(tmp_path).blocks(KEY, _JOB.url)


def test_after_a_confirmed_may_submit_click_a_failure_is_recorded_unknown(tmp_path) -> None:
    wf = _wf(tmp_path)
    token = wf._authorize_dispatch(ControlIdentity(tag="button", name="next"), "fp")
    assert token is not None and token.attempt_id
    record = MagicMock(spec=StepRecord)
    record.confirmed_click, record.click, record.index = True, CLICKED, 0
    record.step = MagicMock()
    wf._observe_form_structure = lambda *a, **k: None
    wf._structure_of = lambda step: None
    wf._observe_step(record, _JOB)
    evidence = wf._settle_submit_attempt(ApplicationEvidence(outcome="FAILED_REQUIRED_FIELD"))
    assert evidence.outcome == "UNKNOWN", "the click may have sent the application"
    assert _reread(tmp_path).blocks(KEY, _JOB.url)


def test_a_job_the_journal_blocks_is_not_started(tmp_path) -> None:
    wf = _wf(tmp_path)
    attempt = wf._submit_journal.arm(KEY, _JOB.url)
    wf._submit_journal.mark(attempt, AttemptState.UNKNOWN, "UNKNOWN")
    wf._apply_single = MagicMock()
    evidence = wf.run(_JOB, session_id="s")
    wf._apply_single.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_a_step_engine_build_failure_never_falls_back_silently(tmp_path) -> None:
    wf = _wf(tmp_path)
    wf._form_engine_build_error = "ImportError"
    wf._navigate_to_application = MagicMock()
    evidence = wf._apply_single(_JOB, ApplicationEvidence())
    wf._navigate_to_application.assert_not_called()
    assert evidence.outcome == "ERROR" and "legacy_fallback" in evidence.error_message
    wf._config = {"applications": {"legacy_fallback": True}}
    wf._navigate_to_application.return_value = ApplicationEvidence(outcome="FAILED_NAVIGATION")
    wf._apply_single(_JOB, ApplicationEvidence())
    wf._navigate_to_application.assert_called_once()


def test_the_production_default_is_no_journal() -> None:
    assert aw._no_submit_journal() is None


def test_every_refusal_the_journal_names_has_words_for_the_person() -> None:
    names = {v for k, v in vars(sij).items()
             if k.isupper() and isinstance(v, str) and k not in ("__all__",)
             and k in ("JOURNAL_CORRUPT", "JOURNAL_UNAVAILABLE", "PROFILE_LOCKED",
                       "SYNCED_FOLDER", "UNRESOLVED_ATTEMPT", "WRITE_FAILED")}
    assert names == set(aw._ARM_REFUSALS)


def test_the_write_order_in_the_source() -> None:
    """AST order pin: arm, then consume the token, then the click."""
    src = textwrap.dedent(inspect.getsource(ApplicationsWorkflow._submit_application))
    calls = [(n.lineno, n.func) for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]

    def line(attr: str, owner: str) -> int:
        return min(lineno for lineno, func in calls if func.attr == attr
                   and owner in ast.unparse(func.value))

    assert line("_arm", "self") < line("consume", "_token_book") < line("click", "_interaction_port")
