"""Pins for the workflow's step-engine path (ApplicationsWorkflow side).

The engine fills; the workflow owns the irreversible parts. These pins hold
the contract between them: every engine status maps to one evidence outcome;
the fail-closed submit gate still decides every submission; the engine's
own submit control is the one clicked; nothing is submitted when no question
holds an answer; frames are opened only when they are plausibly the
application; the pre-2026-11 page loop stays selectable.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.form_engine import (
    ACCOUNT_REQUIRED,
    BLOCKED,
    LOOP,
    MAX_STEPS,
    NO_ADVANCE,
    NO_FORM,
    READY_TO_SUBMIT,
    USER_SKIPPED,
    FormRunResult,
    QuestionOutcome,
    StepRecord,
)
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
from auto_apply.domain.applications.form_model import (
    REQUIRED,
    TRAP,
    ControlRef,
    FormButton,
    FormQuestion,
    FormStep,
    FrameCandidate,
    QuestionKind,
)
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan

_JOB = Job(title="Data Analyst", company="Northwind", url="https://jobs.example/apply/1",
           source="test")
_SUBMIT = FormButton("submit", "Submit application",
                     ControlRef(path=(("c", 9),), tag="button", name="submit"), final=True)


def _step(frames: tuple[FrameCandidate, ...] = ()) -> FormStep:
    return FormStep(_JOB.url, "Apply", "application", (), (_SUBMIT,), "fp",
                    frame_candidates=frames)


def _outcome(action: str, reason: str = "answer", source: str = "profile:x") -> QuestionOutcome:
    return QuestionOutcome("k", "First name", "text", "first_name", REQUIRED, False,
                           action, reason, source, "type")


def _result(status: str, *outcomes: QuestionOutcome, **kw: Any) -> FormRunResult:
    record = StepRecord(0, _step(), tuple(outcomes))
    return FormRunResult(status, kw.pop("reason", "why"), steps=(record,),
                         final_step=kw.pop("final_step", _step()), **kw)


class FakeEngine:
    def __init__(self, *results: FormRunResult | Exception) -> None:
        self.results = list(results)
        self.actuator = MagicMock()
        self.actuator.locate.return_value = MagicMock(name="submit-element")
        self.contexts: list[Any] = []
        self.hosts: list[str] = []

    def run(self, ctx: Any) -> FormRunResult:
        self.contexts.append(ctx)
        self.hosts.append(ctx.answers.host)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _workflow(engine: Any, *, gate: Any = None, pause: bool = True,
              config: dict[str, Any] | None = None, ats_registry: Any = None) -> ApplicationsWorkflow:
    browser = MagicMock()
    browser.current_url = _JOB.url
    browser.page_source = "<html><body>thank you for applying</body></html>"
    browser.title = "Applied"
    policy = MagicMock()
    policy.should_pause.side_effect = lambda checkpoint, ctx: (
        pause and checkpoint.name == "BEFORE_FORM_SUBMIT")
    interaction = MagicMock()
    interaction.click.return_value = None
    wf = ApplicationsWorkflow(
        profile=MagicMock(), browser=browser, perception_port=None,
        interaction_port=interaction, webpage_analyzer=None, field_classifier=None,
        semantic_filler=None, text_matcher=MagicMock(), file_handler=None,
        interruption_handler=None, dom_observer=None, ats_registry=ats_registry,
        job_repo=MagicMock(), task_queue=MagicMock(), event_bus=MagicMock(),
        interrupt_policy=policy, text_generation_port=None, browser_lease=None,
        config=config, plan=SessionPlan(session_id="t"), form_engine=engine,
    )
    if gate is not None:
        wf.set_approval_gate(gate)
    wf._reveal_form_content = lambda: None  # type: ignore[method-assign]
    wf._navigate = MagicMock()  # type: ignore[method-assign]
    return wf


def _apply(wf: ApplicationsWorkflow) -> ApplicationEvidence:
    return wf._apply_with_step_engine(_JOB, ApplicationEvidence())


# ── Selection ────────────────────────────────────────────────────────────────


def test_the_step_engine_runs_when_wired_and_the_page_loop_stays_selectable() -> None:
    assert _workflow(FakeEngine())._uses_step_engine()
    assert not _workflow(None)._uses_step_engine()
    legacy = _workflow(FakeEngine(), config={"applications": {"form_engine": "legacy"}})
    assert not legacy._uses_step_engine()


@pytest.mark.parametrize(("mode", "gate", "expected"), [
    ("auto", True, True),       # the person asked to review before submitting
    ("never", True, False),
    ("always", True, True),
    ("always", False, False),   # nobody to ask
])
def test_assist_mode(mode: str, gate: bool, expected: bool) -> None:
    wf = _workflow(FakeEngine(), gate=(lambda *a, **k: "skip") if gate else None,
                   config={"applications": {"assist_mode": mode}})
    assert wf._assist_allowed(_JOB) is expected


def test_auto_assist_is_off_when_the_person_asked_not_to_be_consulted() -> None:
    wf = _workflow(FakeEngine(), gate=lambda *a, **k: "skip", pause=False)
    assert wf._assist_allowed(_JOB) is False


# ── Status → outcome ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("status", "outcome"), [
    (BLOCKED, "FAILED_REQUIRED_FIELD"),
    (USER_SKIPPED, "USER_SKIPPED"),
    (ACCOUNT_REQUIRED, "ACCOUNT_REQUIRED"),
    (NO_FORM, "FAILED_NOTHING_FILLED"),
    (NO_ADVANCE, "FAILED_NO_SUBMIT_BUTTON"),
    (LOOP, "ERROR"),
    (MAX_STEPS, "ERROR"),
])
def test_every_engine_status_maps_to_one_outcome(status: str, outcome: str) -> None:
    gate = MagicMock(return_value="submit")
    engine = FakeEngine(_result(status, _outcome("filled"), unanswered=("Why us?",)))
    wf = _workflow(engine, gate=gate)
    evidence = _apply(wf)

    assert evidence.outcome == outcome
    assert evidence.submit_clicked is False
    assert evidence.form_engine == "steps"
    gate.assert_not_called()
    wf._interaction_port.click.assert_not_called()
    if status == BLOCKED:
        assert evidence.unknown_required_field == "Why us?"
    if status == ACCOUNT_REQUIRED:
        assert evidence.login_wall_encountered is True


def test_an_engine_error_is_recorded_not_raised() -> None:
    wf = _workflow(FakeEngine(RuntimeError("boom")), gate=MagicMock(return_value="submit"))
    evidence = _apply(wf)
    assert evidence.outcome == "ERROR" and "RuntimeError" in (evidence.error_message or "")


# ── Submission ───────────────────────────────────────────────────────────────


def test_nothing_is_submitted_when_no_question_holds_an_answer() -> None:
    gate = MagicMock(return_value="submit")
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, _outcome("left", "no-answer", ""),
                                      submit_button=_SUBMIT)), gate=gate)
    evidence = _apply(wf)
    assert evidence.outcome == "FAILED_NOTHING_FILLED"
    gate.assert_not_called()


def test_a_form_an_extension_filled_is_offered_for_submission() -> None:
    """Values AA kept (a browser extension, the site's résumé parse) count."""
    gate = MagicMock(return_value="skip")
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, _outcome("left", "prefilled", ""),
                                      submit_button=_SUBMIT)), gate=gate)
    evidence = _apply(wf)
    gate.assert_called_once()
    assert evidence.outcome == "USER_SKIPPED" and evidence.prefilled_kept == 1


def test_the_gate_decides_and_the_engines_submit_control_is_clicked() -> None:
    gate = MagicMock(return_value="submit")
    engine = FakeEngine(_result(READY_TO_SUBMIT, _outcome("filled"), submit_button=_SUBMIT))
    wf = _workflow(engine, gate=gate)
    evidence = _apply(wf)

    question, options = gate.call_args.args[:2]
    assert question.startswith("Submit application?\n")
    assert "AA filled 1 question(s) over 1 page(s)" in question
    assert options == ["submit", "skip"]
    engine.actuator.locate.assert_called_once_with(_SUBMIT.control)
    wf._interaction_port.click.assert_called_once_with(
        engine.actuator.locate.return_value, irreversible=True)
    assert evidence.submit_clicked is True
    assert evidence.submit_button_text == "Submit application"


def test_skip_at_the_gate_never_clicks() -> None:
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, _outcome("filled"),
                                      submit_button=_SUBMIT)),
                   gate=MagicMock(return_value="skip"))
    evidence = _apply(wf)
    wf._interaction_port.click.assert_not_called()
    assert evidence.outcome == "USER_SKIPPED"


def test_no_gate_with_a_required_pause_never_clicks() -> None:
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, _outcome("filled"),
                                      submit_button=_SUBMIT)), gate=None)
    evidence = _apply(wf)
    wf._interaction_port.click.assert_not_called()
    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"


def test_the_evidence_carries_counts_and_never_values() -> None:
    outcomes = (_outcome("filled"), _outcome("human", "answered-in-place", "human"),
                _outcome("left", "reader-decision:trap", ""), _outcome("failed", "x"))
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, *outcomes, submit_button=_SUBMIT)),
                   gate=MagicMock(return_value="skip"))
    evidence = _apply(wf)
    assert evidence.human_assisted_fields == 1 and evidence.traps_left == 1
    assert evidence.fill_failures == 1 and evidence.required_fields_filled == 2
    assert evidence.answer_sources == {"profile": 1, "human": 1}
    assert "First name" not in evidence.model_dump_json()


# ── Frames ───────────────────────────────────────────────────────────────────


def test_an_application_frame_is_opened_as_a_page_and_a_challenge_frame_never() -> None:
    frames = (
        FrameCandidate("https://www.google.com/recaptcha/api2/anchor?k=1", False, "loaded"),
        FrameCandidate("https://www.youtube.com/embed/abc", False, "loaded"),
        FrameCandidate("https://boards.example.com/acme/jobs/42/apply", False, "loaded"),
    )
    no_form = FormRunResult(NO_FORM, "the application form is inside a frame",
                            final_step=_step(frames))
    ready = _result(READY_TO_SUBMIT, _outcome("filled"), submit_button=_SUBMIT)
    wf = _workflow(FakeEngine(no_form, ready), gate=MagicMock(return_value="skip"))
    evidence = _apply(wf)

    wf._navigate.assert_called_once_with("https://boards.example.com/acme/jobs/42/apply")
    assert evidence.apply_route_hops == 1
    assert evidence.outcome == "USER_SKIPPED"


def test_no_plausible_frame_means_no_hop() -> None:
    frames = (FrameCandidate("https://challenges.cloudflare.com/turnstile/v0", False, "loaded"),
              FrameCandidate("https://cdn.example.com/widget", False, "loaded"))
    no_form = FormRunResult(NO_FORM, "no form", final_step=_step(frames))
    wf = _workflow(FakeEngine(no_form), gate=MagicMock(return_value="skip"))
    evidence = _apply(wf)
    wf._navigate.assert_not_called()
    assert evidence.outcome == "FAILED_NOTHING_FILLED"


# ── The research record ──────────────────────────────────────────────────────


def test_each_step_becomes_one_research_record() -> None:
    wf = _workflow(FakeEngine())
    observer = MagicMock()
    wf._research_observer = observer

    ref = ControlRef(path=(("c", 1),), tag="input", name="website", id="website")
    step = FormStep(_JOB.url, "Apply", "application", (
        FormQuestion("w", "Website", QuestionKind.TEXT, "website", (ref,), decision=TRAP),
        FormQuestion("r", "Resume *", QuestionKind.FILE, "resume", (ref,), required=REQUIRED),
    ), (), "fp")
    wf._observe_step(StepRecord(2, step, ()), _JOB)

    fs = observer.observe_form.call_args.args[0]
    assert fs.page_index == 2
    assert fs.form_structure.has_file_upload is True
    trap, resume = fs.form_structure.fields
    assert trap.is_honeypot and resume.is_required and resume.field_type == "file"


# ── Review findings: risky clicks, a form that vanished, no values in logs ───


@pytest.mark.parametrize(("pause", "gate_answer", "has_gate", "expected"), [
    (False, None, False, "click"),         # autonomous submission chosen by the person
    (True, "click it", True, "click"),
    (True, "skip", True, "skip"),
    (True, None, False, "blocked"),        # review required, nobody to ask
])
def test_a_risky_click_is_decided_like_the_submit_gate(
        pause: bool, gate_answer: str | None, has_gate: bool, expected: str) -> None:
    gate = MagicMock(return_value=gate_answer) if has_gate else None
    wf = _workflow(FakeEngine(), gate=gate, pause=pause)
    assert wf._confirm_risky_click(_JOB, "Submit and continue") == expected
    if has_gate:
        question = gate.call_args.args[0]  # type: ignore[union-attr]
        assert "Submit and continue" in question
        assert gate.call_args.kwargs["checkpoint"] == "BEFORE_FORM_SUBMIT"  # type: ignore[union-attr]


def test_a_policy_that_raises_blocks_a_risky_click() -> None:
    wf = _workflow(FakeEngine(), gate=MagicMock(return_value="click it"))
    wf._interrupt_policy.should_pause.side_effect = RuntimeError("broken policy")
    assert wf._confirm_risky_click(_JOB, "Review") == "blocked"


def test_the_engine_gets_the_risky_click_decision() -> None:
    engine = FakeEngine(_result(USER_SKIPPED))
    wf = _workflow(engine, gate=MagicMock(return_value="skip"))
    _apply(wf)
    assert engine.contexts[0].confirm_risky("Submit and continue") == "skip"


def test_a_form_that_vanished_after_next_is_ambiguous_not_empty() -> None:
    record = StepRecord(0, _step(), (_outcome("filled"),), advanced_by="Next")
    vanished = FormRunResult(NO_FORM, "no application form on this page", steps=(record,),
                             final_step=FormStep(_JOB.url, "Thanks", "none", (), (), "x"))
    wf = _workflow(FakeEngine(vanished), gate=MagicMock(return_value="skip"))
    evidence = _apply(wf)
    assert evidence.outcome == "AMBIGUOUS"
    assert "may have taken the application" in (evidence.error_message or "")
    assert evidence.submit_clicked is False


def test_an_engine_error_logs_where_not_what(caplog: pytest.LogCaptureFixture) -> None:
    wf = _workflow(FakeEngine(RuntimeError("typed: Ada Quill 555-123-4567")),
                   gate=MagicMock(return_value="submit"))
    with caplog.at_level(logging.DEBUG):
        evidence = _apply(wf)
    assert "RuntimeError" in caplog.text and "test_step_engine_path.py" in caplog.text
    assert "Ada" not in caplog.text and "555" not in caplog.text
    assert "Ada" not in (evidence.error_message or "")



def test_the_tab_is_closed_on_every_exit_including_an_engine_error() -> None:
    for engine in (FakeEngine(RuntimeError("boom")), FakeEngine(_result(BLOCKED))):
        wf = _workflow(engine, gate=MagicMock(return_value="skip"))
        wf._context_manager = MagicMock()
        _apply(wf)
        wf._context_manager.close_current_tab_and_return.assert_called_once()


def test_after_a_frame_hop_the_engine_knows_the_frames_host() -> None:
    frames = (FrameCandidate("https://boards.example.com/acme/jobs/42/apply", False, "loaded"),)
    no_form = FormRunResult(NO_FORM, "no form", final_step=_step(frames))
    engine = FakeEngine(no_form, _result(USER_SKIPPED))
    _apply(_workflow(engine, gate=MagicMock(return_value="skip")))
    assert engine.hosts[1] == "boards.example.com"


def test_the_gate_names_the_control_aa_will_click() -> None:
    gate = MagicMock(return_value="skip")
    wf = _workflow(FakeEngine(_result(READY_TO_SUBMIT, _outcome("filled"),
                                      submit_button=_SUBMIT)), gate=gate)
    _apply(wf)
    assert "\u201cSubmit application\u201d control" in gate.call_args.args[0]
