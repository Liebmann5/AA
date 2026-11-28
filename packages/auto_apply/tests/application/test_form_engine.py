"""Pins for the application step engine (read, decide, act, verify, advance).

The page here is an in-memory form behind ``FormPagePort`` and the tool is a
recording stand-in for ``PageActionService``: these pins hold the engine's
DECISIONS (order, what is asked, what is never touched, when a step counts as
progress, what ends a run). The same engine against real Chromium, through
both browser adapters, is pinned in
``tests/integration/test_form_engine_browsers.py``; neither is proof of
behaviour on live sites — live runs are.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from auto_apply.application.services.form_actuator import ControlActuator
from auto_apply.application.services.hitl_gate import gate_keywords
from auto_apply.domain.services.submit_token import ControlIdentity, TokenBook
from auto_apply.application.services.form_engine import (
    ACCOUNT_REQUIRED,
    BLOCKED,
    CLICK_UNCERTAIN,
    LOOP,
    NO_ADVANCE,
    NO_FORM,
    NOT_CLICKED,
    READY_TO_SUBMIT,
    USER_SKIPPED,
    FormEngineSettings,
    FormRunContext,
    FormStepEngine,
    GeneratedAnswerSource,
    StepRecord,
)
from auto_apply.domain.applications.answers import Answer, AnswerContext
from auto_apply.domain.applications.form_model import (
    OPTIONAL,
    REQUIRED,
    TRAP,
    UNKNOWN,
    ControlRef,
    ControlState,
    FormButton,
    FormOption,
    FormQuestion,
    FormStep,
    QuestionKind,
)

# ─────────────────────────────────────────────────────────────────────────────
# An in-memory form
# ─────────────────────────────────────────────────────────────────────────────

_ids = itertools.count(1)


def _ref(name: str, tag: str = "input", type_: str = "text") -> ControlRef:
    return ControlRef(path=(("c", next(_ids)),), tag=tag, type=type_, name=name, id=name)


@dataclass
class Live:
    """One live control."""

    visible: bool = True
    value: str = ""
    checked: bool | None = None
    files: int = 0
    disabled: bool = False
    invalid: bool = False
    message: str = ""
    accepts_typing: bool = True
    on_click: Callable[[], None] | None = None
    label_for: ControlRef | None = None


@dataclass
class Form:
    """Steps of questions and buttons over a table of live controls."""

    url: str = "https://jobs.example/apply"
    purpose: str = "application"
    steps: list[tuple[list[FormQuestion], list[FormButton], str]] = field(default_factory=list)
    current: int = 0
    live: dict[tuple[Any, ...], Live] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    on_upload: Callable[[], None] | None = None
    language: str = ""

    def add(self, ref: ControlRef, **kw: Any) -> ControlRef:
        self.live[ref.path] = Live(**kw)
        return ref

    def state(self, ref: ControlRef) -> Live:
        return self.live[ref.path]


class FakeElement:
    def __init__(self, form: Form, ref: ControlRef) -> None:
        self.form, self.ref = form, ref

    def send_keys(self, text: str) -> None:
        live = self.form.state(self.ref)
        if live.accepts_typing:
            live.value += text


class FakePage:
    """``FormPagePort`` over a ``Form``."""

    def __init__(self, form: Form) -> None:
        self.form = form

    def read_step(self) -> FormStep | None:
        f = self.form
        if f.current >= len(f.steps):
            return FormStep(f.url, "done", "other", (), (), "done")
        questions, buttons, label = f.steps[f.current]
        # A page with no question after the first one reads as a review page.
        purpose = f.purpose if questions or f.current == 0 else "review"
        return FormStep(f.url, "Apply", purpose, tuple(questions), tuple(buttons),
                        f"fp{f.current}", step_label=label, language=f.language)

    def read_states(self, refs: list[ControlRef]) -> list[ControlState]:
        out = []
        for r in refs:
            live = self.form.live.get(r.path)
            if live is None:
                out.append(ControlState(present=False))
                continue
            out.append(ControlState(
                present=True, visible=live.visible, value=live.value, checked=live.checked,
                files=live.files, disabled=live.disabled, invalid=live.invalid,
                message=live.message,
            ))
        return out

    def locate(self, ref: ControlRef) -> Any:
        return FakeElement(self.form, ref) if ref.path in self.form.live else None

    def listbox_options(self, ref: ControlRef) -> list[str]:
        return []

    def locate_option(self, ref: ControlRef, index: int) -> Any:
        return None

    def choose_native_option(self, ref: ControlRef, index: int) -> bool:
        for questions, _b, _l in self.form.steps:
            for q in questions:
                if q.primary == ref:
                    self.form.state(ref).value = q.options[index].label
                    self.form.log.append(f"select:{ref.name}")
                    return True
        return False

    def set_files(self, ref: ControlRef, path: str) -> bool:
        self.form.state(ref).files = 1
        self.form.log.append(f"upload:{ref.name}")
        if self.form.on_upload:
            self.form.on_upload()
        return True

    def set_value_by_script(self, ref: ControlRef, value: str) -> bool:
        self.form.state(ref).value = value
        self.form.log.append(f"script:{ref.name}")
        return True

    def control_census(self) -> tuple[Any, ...]:
        return tuple(sorted(str(p) for p, live in self.form.live.items() if live.visible))

    def focus(self, ref: ControlRef) -> bool:
        self.form.log.append(f"focus:{ref.name}")
        return ref.path in self.form.live

    def quiet_detector(self, quiet: int, t_max: float) -> Callable[[object, float], str]:
        """The port's settling contract: K equal readings, or T_max."""
        seen: list[object] = []

        def observe(signature: object, now: float) -> str:
            seen.append(signature)
            if len(seen) > quiet and all(x == signature for x in seen[-quiet - 1:]):
                return "settled"
            return "timeout" if now >= t_max else "settling"

        return observe


class FakeTool:
    """Records every action; operates the in-memory controls."""

    def __init__(self, form: Form) -> None:
        self.form = form

    def click(self, element: Any, *, irreversible: bool = False, expect: Any = None) -> bool:
        live = self.form.state(element.ref)
        self.form.log.append(f"click:{element.ref.name}")
        target = live.label_for
        if target is not None:
            live = self.form.state(target)
        if live.on_click is not None:
            live.on_click()
        elif live.checked is not None:
            live.checked = not live.checked
        return True

    def control_identity(self, element: Any) -> ControlIdentity:
        return ControlIdentity(tag="button", type="submit", name=element.ref.name)

    def type_text(self, element: Any, text: str) -> bool:
        self.form.log.append(f"type:{element.ref.name}")
        element.send_keys(text)
        return True

    def clear_and_type(self, element: Any, text: str) -> bool:
        self.form.log.append(f"retype:{element.ref.name}")
        live = self.form.state(element.ref)
        if live.accepts_typing:
            live.value = text
        return True

    def settle(self) -> None:
        pass

    def scroll_into_view(self, element: Any) -> bool:
        self.form.log.append(f"scroll:{element.ref.name}")
        return True

    def macro_pause(self, min_s: float | None = None, max_s: float | None = None) -> None:
        pass


def _text(form: Form, label: str, field_type: str, *, required: str = UNKNOWN,
          kind: str = QuestionKind.TEXT, decision: str = "FILL", sensitive: bool = False,
          **live: Any) -> FormQuestion:
    ref = form.add(_ref(label.split(maxsplit=1)[0].lower()), **live)
    return FormQuestion(key=label, label=label, kind=kind, field_type=field_type,
                        controls=(ref,), required=required, decision=decision,
                        sensitive=sensitive)


def _file(form: Form, label: str = "Resume", *, required: str = REQUIRED) -> FormQuestion:
    ref = form.add(_ref("resume", type_="file"), visible=False)
    return FormQuestion(key=label, label=label, kind=QuestionKind.FILE, field_type="resume",
                        controls=(ref,), required=required)


def _box(form: Form, label: str, *, required: str) -> FormQuestion:
    ref = form.add(_ref(label.split()[1].lower(), type_="checkbox"), checked=False)
    return FormQuestion(key=label, label=label, kind=QuestionKind.CHECKBOX,
                        field_type="checkbox", controls=(ref,), required=required,
                        options=(FormOption(label, control=ref),))


def _radio(form: Form, label: str, choices: tuple[str, ...], *, required: str = REQUIRED,
           field_type: str = "text", on: dict[str, Callable[[], None]] | None = None) -> FormQuestion:
    opts = []
    refs = []
    for c in choices:
        ref = form.add(_ref(f"{label.split(maxsplit=1)[0].lower()}_{c.lower()}", type_="radio"),
                       checked=False)
        refs.append(ref)
    for c, ref in zip(choices, refs):
        others = [r for r in refs if r != ref]

        def choose(ref: ControlRef = ref, others: list[ControlRef] = others, c: str = c) -> None:
            form.state(ref).checked = True
            for o in others:
                form.state(o).checked = False
            if on and c in on:
                on[c]()

        form.state(ref).on_click = choose
        opts.append(FormOption(c, control=ref))
    return FormQuestion(key=label, label=label, kind=QuestionKind.RADIO, field_type=field_type,
                        controls=tuple(refs), required=required, options=tuple(opts))


def _button(form: Form, text: str, role: str, on_click: Callable[[], None] | None = None,
            *, final: bool = False, button_type: str | None = None) -> FormButton:
    ref = form.add(_ref(text.lower().replace(" ", "_"), tag="button", type_="button"),
                   on_click=on_click or (lambda: None))
    btype = button_type if button_type is not None else (
        "submit" if role == "submit" else "button")
    return FormButton(role=role, text=text, control=ref, final=final, button_type=btype)


class Answers:
    """An answer source keyed by field type."""

    name = "profile"

    def __init__(self, **by_type: Answer) -> None:
        self.by_type = by_type

    def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
        return self.by_type.get(q.field_type)


_PROFILE = Answers(
    first_name=Answer(text="Ada", source="profile:first_name", confidence=0.95),
    email=Answer(text="ada@example.org", source="profile:email", confidence=0.95),
    phone=Answer(text="5551234567", source="profile:phone", confidence=0.95),
    resume=Answer(file_path="/tmp/resume.pdf", source="profile:resume", confidence=1.0),
    sponsorship=Answer(text="No", choices=("no",), source="profile:legal_info.requires_sponsorship",
                       confidence=0.95, sensitive=True, review=True),
)


def _engine(form: Form, *, sources: list[Any] | None = None, **settings: Any) -> FormStepEngine:
    ticks = itertools.count()
    defaults: dict[str, Any] = {"reading_pause_ms_per_char": 0, "upload_quiet_min_s": 0.0}
    defaults.update(settings)
    return FormStepEngine(FakePage(form), FakeTool(form), sources or [_PROFILE],
                          FormEngineSettings(**defaults), clock=lambda: float(next(ticks)))


def _ctx(gate: Callable[..., Any] | None = None, *, assist: bool = False,
         records: list[StepRecord] | None = None) -> FormRunContext:
    return FormRunContext(
        answers=AnswerContext(job_title="Data Analyst", company="Northwind", host="jobs.example"),
        gate=gate, assist_allowed=assist,
        on_step=(records.append if records is not None else None),
    )


def approving(inner: Callable[..., Any] | None = None) -> Callable[..., Any]:
    """A gate that approves the pre-write review (Phase 0, P0-5) and passes
    every other question to ``inner`` (none: "skip"). For tests about
    something else than the review itself."""
    def gate(question: str, options: list[str], *, checkpoint: str,
             timeout: float | None = None, **kw: Any) -> str:
        if checkpoint == "ANSWER_REVIEW" and "approve" in options:
            return "approve"
        if inner is None:
            return "skip"
        accepted = gate_keywords(inner)
        extra = {k: v for k, v in {"checkpoint": checkpoint, "timeout": timeout, **kw}.items()
                 if k in accepted}
        return inner(question, options, **extra)
    return gate


def _token_for(identity: ControlIdentity, fingerprint: str) -> Any:
    """What the workflow hands the engine for a confirmed click (P0-4)."""
    return TokenBook.mint(attempt_id="test-attempt", values=[], control=identity,
                          step_fingerprint=fingerprint, auth_source="person")


def _one_page(form: Form, *extra: FormQuestion) -> FormButton:
    submit = _button(form, "Submit application", "submit", final=True)
    questions = [
        _text(form, "First name *", "first_name", required=REQUIRED),
        _file(form),
        _text(form, "Email *", "email", required=REQUIRED),
        _text(form, "Website", "website", decision=TRAP),
        _box(form, "Send me job alerts", required=OPTIONAL),
        _box(form, "I certify this is true", required=REQUIRED),
        *extra,
    ]
    form.steps.append((questions, [submit], ""))
    return submit


# ─────────────────────────────────────────────────────────────────────────────
# One page
# ─────────────────────────────────────────────────────────────────────────────


def test_answer_sources_see_the_languages_the_form_may_be_in() -> None:
    """docs/adr/025: a rule that reads a question's wording in one language
    (the English legal rule) must know when the form may be in another."""
    seen: list[tuple[str, ...]] = []

    class Spy:
        name = "spy"

        def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
            seen.append(ctx.form_locales)
            return None

    form = Form(language="de")
    _one_page(form)
    _engine(form, sources=[Spy(), _PROFILE]).run(_ctx())
    assert seen and all("de" in locales and "en" in locales for locales in seen)


def test_a_one_page_form_is_filled_and_left_ready_to_submit() -> None:
    form = Form()
    submit = _one_page(form)
    result = _engine(form).run(_ctx(approving()))

    assert result.status == READY_TO_SUBMIT
    assert result.submit_button == submit
    # The résumé sits below the name on the page, yet goes in first.
    assert form.log[0] == "upload:resume", "the résumé goes in before anything is typed"
    assert form.state(form.steps[0][0][0].primary).value == "Ada"
    assert "click:submit_application" not in form.log, "the engine never submits"


def test_traps_and_optional_boxes_are_never_touched() -> None:
    form = Form()
    _one_page(form)
    _engine(form).run(_ctx(approving()))

    questions = form.steps[0][0]
    trap, alerts, certify = questions[3], questions[4], questions[5]
    assert not any(entry.endswith(":" + trap.primary.name) for entry in form.log)
    assert f"click:{alerts.primary.name}" not in form.log
    assert form.state(alerts.primary).checked is False
    assert form.state(certify.primary).checked is True


def test_values_already_in_the_form_are_kept() -> None:
    """A résumé parse (or a browser extension) filled the name: AA keeps it."""
    form = Form()
    _one_page(form)
    name = form.steps[0][0][0].primary

    def parse() -> None:
        form.state(name).value = "Ada (from resume)"

    form.on_upload = parse
    result = _engine(form).run(_ctx())

    assert form.state(name).value == "Ada (from resume)"
    assert "type:first" not in form.log
    assert result.counters()["prefilled"] == 1


def test_the_counters_carry_no_values() -> None:
    form = Form()
    _one_page(form)
    result = _engine(form).run(_ctx(approving()))
    flat = repr(result.counters()) + repr(result.review_items())
    assert "Ada" not in flat and "example.org" not in flat
    c = result.counters()
    assert c["uploads"] == 1 and c["required_filled"] == 4 and c["traps_left"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Asking the person
# ─────────────────────────────────────────────────────────────────────────────


def _with_unanswerable(form: Form) -> FormQuestion:
    q = _text(form, "How did you hear about this job? *", "referral", required=REQUIRED)
    _one_page(form, q)
    return q


def test_a_required_question_without_an_answer_blocks_when_asking_is_off() -> None:
    form = Form()
    _with_unanswerable(form)
    asked: list[str] = []

    def gate(*a: Any, **k: Any) -> str:
        asked.append("x")
        return "done"

    result = _engine(form).run(_ctx(gate=approving(gate), assist=False))

    assert result.status == BLOCKED
    assert asked == [], "with asking off, the person is never prompted"
    assert result.unanswered == ("How did you hear about this job? *",)


def test_the_person_answers_in_place_and_the_answer_is_remembered() -> None:
    form = Form()
    q = _with_unanswerable(form)
    asked: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str, timeout: float) -> str:
        asked.append(checkpoint)
        form.state(q.primary).value = "A friend"  # the person types in the browser
        return "done"

    engine = _engine(form)
    result = engine.run(_ctx(approving(gate), assist=True))
    assert result.status == READY_TO_SUBMIT
    assert asked == ["FORM_NEEDS_ANSWERS"]
    assert result.counters()["human"] == 1

    # The next application asks the same question: answered without asking.
    form2 = Form()
    q2 = _with_unanswerable(form2)
    q2 = replace(q2)  # same label, new control
    engine2 = FormStepEngine(FakePage(form2), FakeTool(form2), [_PROFILE],
                             FormEngineSettings(reading_pause_ms_per_char=0,
                                                upload_quiet_min_s=0.0),
                             memory=engine.memory, clock=itertools.count().__next__)
    asked.clear()
    result2 = engine2.run(_ctx(approving(gate), assist=True))
    assert result2.status == READY_TO_SUBMIT and asked == []
    assert form2.state(form2.steps[0][0][-1].primary).value == "A friend"


def test_skip_at_the_prompt_ends_the_application_as_skipped() -> None:
    form = Form()
    _with_unanswerable(form)
    result = _engine(form).run(_ctx(lambda *a, **k: "skip", assist=True))
    assert result.status == USER_SKIPPED


def test_a_gate_that_raises_is_a_skip_not_a_crash() -> None:
    form = Form()
    _with_unanswerable(form)

    def broken(*a: Any, **k: Any) -> str:
        raise RuntimeError("UI went away")

    assert _engine(form).run(_ctx(broken, assist=True)).status == USER_SKIPPED


def test_a_gate_without_a_timeout_keyword_is_not_asked() -> None:
    """The gate contract (round 3): a gate that cannot promise to return is
    never called — and never left running on a thread. The question stays
    unanswered and the run ends honestly."""
    form = Form()
    q = _with_unanswerable(form)
    calls: list[int] = []

    def old_gate(question: str, options: list[str], *, checkpoint: str) -> str:
        calls.append(1)
        form.state(q.primary).value = "A friend"
        return "done"

    result = _engine(form).run(_ctx(old_gate, assist=True))
    assert calls == [] and result.status == USER_SKIPPED


# ─────────────────────────────────────────────────────────────────────────────
# Several steps
# ─────────────────────────────────────────────────────────────────────────────


def _wizard(form: Form, *, validate: Callable[[], bool] = lambda: True) -> FormQuestion:
    def go_next() -> None:
        if validate():
            form.current += 1

    years = _text(form, "Years of experience", "text", required=UNKNOWN)
    s1 = [
        _text(form, "First name *", "first_name", required=REQUIRED),
        years,
    ]
    s2 = [_radio(form, "Will you require sponsorship? *", ("Yes", "No"), field_type="sponsorship")]
    for ref_q in s2:
        for r in ref_q.controls:
            form.state(r).visible = False
    nxt = _button(form, "Next", "next", go_next)
    submit = _button(form, "Submit", "submit", final=True)
    form.state(submit.control).visible = False
    form.steps.append((s1, [nxt, submit], "Step 1 of 2"))
    form.steps.append((s2, [nxt, submit], "Step 2 of 2"))

    # Rendering: only the current step's controls are visible.
    def show() -> None:
        for i, (qs, _b, _l) in enumerate(form.steps):
            for q in qs:
                for r in q.controls:
                    form.state(r).visible = i == form.current
        form.state(nxt.control).visible = form.current == 0
        form.state(submit.control).visible = form.current == 1

    form.__dict__["show"] = show
    show()
    return years


class _RenderingPage(FakePage):
    def read_step(self) -> FormStep | None:
        show = self.form.__dict__.get("show")
        if show:
            show()
        return super().read_step()


def _wizard_engine(form: Form, **settings: Any) -> FormStepEngine:
    defaults: dict[str, Any] = {"reading_pause_ms_per_char": 0, "upload_quiet_min_s": 0.0}
    defaults.update(settings)
    return FormStepEngine(_RenderingPage(form), FakeTool(form), [_PROFILE],
                          FormEngineSettings(**defaults), clock=itertools.count().__next__)


def test_a_wizard_advances_only_on_proven_progress_and_records_each_step() -> None:
    form = Form()
    _wizard(form)
    records: list[StepRecord] = []
    result = _wizard_engine(form).run(_ctx(approving(), records=records))

    assert result.status == READY_TO_SUBMIT
    assert [r.index for r in records] == [0, 1], "one research record per step"
    assert records[0].advanced_by == "Next"
    assert result.submit_button is not None and result.submit_button.text == "Submit"


def test_a_rejected_step_is_reported_with_the_pages_own_message() -> None:
    form = Form()
    years: list[FormQuestion] = []

    def validate() -> bool:
        live = form.state(years[0].primary)
        ok = live.value.isdigit()
        live.invalid = not ok
        live.message = "" if ok else "Please enter a whole number."
        return ok

    years.append(_wizard(form, validate=validate))
    result = _wizard_engine(form).run(_ctx())

    assert result.status == BLOCKED
    assert result.unanswered == ("Years of experience (Please enter a whole number.)",)


def test_the_person_fixes_a_rejected_step_and_the_friction_is_recorded() -> None:
    form = Form()
    years: list[FormQuestion] = []

    def validate() -> bool:
        live = form.state(years[0].primary)
        ok = live.value.isdigit()
        live.invalid = not ok
        live.message = "" if ok else "Please enter a whole number."
        return ok

    years.append(_wizard(form, validate=validate))

    def gate(question: str, options: list[str], **kw: Any) -> str:
        form.state(years[0].primary).value = "5"
        return "done"

    records: list[StepRecord] = []
    result = _wizard_engine(form).run(_ctx(approving(gate), assist=True, records=records))

    assert result.status == READY_TO_SUBMIT
    assert records[0].errors == ("Years of experience (Please enter a whole number.)",)
    assert result.counters()["validation_errors"] == 1


class _ClickingTool(FakeTool):
    """A tool whose click on one control misbehaves: ``"refuse"`` reports no
    click (and the page moves on by itself meanwhile, as an auto-advancing
    or timed page can), ``"raise"`` fails mid-click without moving the page."""

    def __init__(self, form: Form, name: str, how: str) -> None:
        super().__init__(form)
        self.name, self.how, self.calls = name, how, 0

    def click(self, element: Any, *, irreversible: bool = False, expect: Any = None) -> bool:
        if element.ref.name != self.name:
            return super().click(element, irreversible=irreversible, expect=expect)
        self.calls += 1
        self.form.log.append(f"click:{element.ref.name}")
        if self.how == "raise":
            raise RuntimeError("the click broke")
        self.form.current += 1  # the page moved, but not because of AA
        return False


def _misclick_engine(form: Form, how: str) -> tuple[FormStepEngine, _ClickingTool]:
    _wizard(form)
    nxt = next(b for qs, buttons, _ in form.steps for b in buttons if b.text == "Next")
    tool = _ClickingTool(form, nxt.control.name, how)
    engine = FormStepEngine(_RenderingPage(form), tool, [_PROFILE],
                            FormEngineSettings(reading_pause_ms_per_char=0,
                                               upload_quiet_min_s=0.0),
                            clock=itertools.count().__next__)
    return engine, tool


def test_a_click_the_tool_says_did_not_happen_is_never_progress() -> None:
    """Round-3 review: the page moving after a click AA did not make is not
    AA's progress. The run ends honestly; the record says no click happened."""
    form = Form()
    engine, tool = _misclick_engine(form, "refuse")
    records: list[StepRecord] = []
    result = engine.run(_ctx(records=records))

    assert result.status == NO_ADVANCE
    assert "could not click" in result.reason
    assert records[0].click == NOT_CLICKED
    assert records[0].advanced_by == ""
    assert tool.calls == 1


def test_a_click_that_raised_is_never_repeated() -> None:
    """A click that failed mid-way may have reached the page: clicking it
    again could act twice (submit twice). AA stops and says so."""
    form = Form()
    engine, tool = _misclick_engine(form, "raise")
    records: list[StepRecord] = []
    result = engine.run(_ctx(records=records))

    assert result.status == BLOCKED
    assert "may or may not have happened" in result.reason
    assert records[0].click == CLICK_UNCERTAIN
    assert tool.calls == 1, "an uncertain click is never repeated"


def test_a_form_that_keeps_returning_to_the_same_step_is_a_loop() -> None:
    form = Form()
    a = [_text(form, "First name *", "first_name", required=REQUIRED)]
    b = [_text(form, "Email *", "email", required=REQUIRED)]

    def flip() -> None:
        form.current = 1 - form.current
        for q in a:
            form.state(q.primary).visible = form.current == 0
        for q in b:
            form.state(q.primary).visible = form.current == 1

    nxt = _button(form, "Continue", "next", flip)
    form.state(b[0].primary).visible = False
    form.steps += [(a, [nxt], ""), (b, [nxt], "")]
    assert _engine(form).run(_ctx()).status == LOOP


def test_review_each_step_lets_the_person_stop() -> None:
    form = Form()
    _wizard(form)
    seen: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str, **kw: Any) -> str:
        seen.append(checkpoint)
        return "skip"

    result = _wizard_engine(form, review_each_step=True).run(_ctx(gate))
    assert result.status == USER_SKIPPED
    assert seen == ["AFTER_STEP_FILLED"]
    assert form.current == 0, "nothing advanced after the person said stop"


# ─────────────────────────────────────────────────────────────────────────────
# Conditional questions, widgets, walls
# ─────────────────────────────────────────────────────────────────────────────


def test_a_choice_that_reveals_a_question_gets_the_new_question_handled() -> None:
    form = Form()
    employee_id = _text(form, "Former employee ID *", "text", required=REQUIRED, visible=False)
    worked = _radio(form, "Have you worked here before? *", ("Yes", "No"),
                    on={"Yes": lambda: setattr(form.state(employee_id.primary), "visible", True)})
    answers = Answers(text=Answer(text="Yes", choices=("yes",), source="profile:x",
                                  confidence=0.95))
    submit = _button(form, "Submit", "submit", final=True)
    form.steps.append(([worked, employee_id], [submit], ""))

    result = _engine(form, sources=[answers]).run(_ctx())

    # The revealed question was read and handled (here: answered "Yes" too,
    # since the stand-in source answers every "text" question).
    assert form.state(employee_id.primary).value == "Yes"
    assert result.status == READY_TO_SUBMIT


def test_typing_that_does_not_take_falls_back_to_script_and_says_so() -> None:
    form = Form()
    phone = _text(form, "Phone *", "phone", required=REQUIRED, accepts_typing=False)
    form.steps.append(([phone], [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form).run(_ctx())
    assert result.counters()["rungs"] == {"script": 1}


def test_with_script_fallback_off_a_failed_fill_is_reported_not_hidden() -> None:
    form = Form()
    phone = _text(form, "Phone *", "phone", required=REQUIRED, accepts_typing=False)
    form.steps.append(([phone], [_button(form, "Submit", "submit", final=True)], ""))
    settings = FormEngineSettings.from_config({"applications": {"script_fill_fallback": False}})
    engine = FormStepEngine(FakePage(form), FakeTool(form), [_PROFILE],
                            replace(settings, reading_pause_ms_per_char=0),
                            clock=itertools.count().__next__)
    result = engine.run(_ctx())
    assert result.status == BLOCKED
    assert result.counters()["failed"] == 1


def test_an_account_wall_ends_the_run_without_assistance() -> None:
    form = Form(purpose="login")
    pw = form.add(_ref("password", type_="password"))
    q = FormQuestion(key="pw", label="Password", kind=QuestionKind.PASSWORD,
                     field_type="password", controls=(pw,))
    form.steps.append(([q], [_button(form, "Sign in", "other")], ""))
    result = _engine(form).run(_ctx())
    assert result.status == ACCOUNT_REQUIRED
    assert not any(e.startswith(("type:", "retype:")) for e in form.log), "AA never types a password"


def test_the_person_signs_in_and_the_run_continues() -> None:
    form = Form(purpose="login")
    pw = form.add(_ref("password", type_="password"))
    login_q = FormQuestion(key="pw", label="Password", kind=QuestionKind.PASSWORD,
                           field_type="password", controls=(pw,))
    form.steps.append(([login_q], [_button(form, "Sign in", "other")], ""))
    _one_page(form)

    def gate(question: str, options: list[str], *, checkpoint: str, **kw: Any) -> str:
        assert checkpoint == "ACCOUNT_REQUIRED"
        form.purpose = "application"
        form.current = 1
        form.state(pw).visible = False
        return "signed in"

    assert _engine(form).run(_ctx(approving(gate), assist=True)).status == READY_TO_SUBMIT


def test_a_page_without_an_application_form_is_no_form() -> None:
    form = Form()
    form.steps.append(([], [], ""))
    assert _engine(form).run(_ctx()).status == NO_FORM


def test_settings_come_from_the_applications_block() -> None:
    s = FormEngineSettings.from_config({"applications": {
        "max_pages": 4, "assist_timeout_s": 60, "review_each_step": True,
        "min_answer_confidence": 0.9, "overwrite_prefilled": True,
        "acknowledge_required": False, "script_fill_fallback": False,
        "option_match_threshold": 0.7, "type_chunk_threshold": 100,
    }})
    assert s.max_steps == 4 and s.assist_timeout_s == 60.0 and s.review_each_step
    assert s.fill.min_confidence == 0.9 and s.fill.overwrite_prefilled
    assert not s.fill.acknowledge_required
    assert not s.actuator.script_fallback and s.actuator.option_threshold == 0.7
    assert s.actuator.chunk_threshold == 100
    assert FormEngineSettings.from_config({}) == FormEngineSettings()


@pytest.mark.parametrize("bad", [None, "x", {"applications": "x"}, {"applications": {"max_pages": "lots"}}])
def test_malformed_settings_fall_back_to_defaults(bad: Any) -> None:
    assert FormEngineSettings.from_config(bad).max_steps == 12


# ─────────────────────────────────────────────────────────────────────────────
# No submit without consent (review finding: a Next that may submit)
# ─────────────────────────────────────────────────────────────────────────────


def _paged(form: Form, pages: list[tuple[list[FormQuestion], list[FormButton]]]) -> None:
    """Steps that show only their own questions and buttons."""
    form.steps = [(qs, bs, f"Step {i + 1} of {len(pages)}") for i, (qs, bs) in enumerate(pages)]

    def show() -> None:
        for i, (qs, bs, _l) in enumerate(form.steps):
            for q in qs:
                for r in q.controls:
                    form.state(r).visible = i == form.current
            for b in bs:
                form.state(b.control).visible = i == form.current

    form.__dict__["show"] = show
    show()


def _two_steps(form: Form, text: str, role: str, *, final: bool,
               button_type: str) -> FormButton:
    def go() -> None:
        form.current += 1

    forward = _button(form, text, role, go, final=final, button_type=button_type)
    submit = _button(form, "Submit", "submit", final=True)
    _paged(form, [
        ([_text(form, "First name *", "first_name", required=REQUIRED)], [forward]),
        ([_text(form, "Email *", "email", required=REQUIRED)], [submit]),
    ])
    return forward


@pytest.mark.parametrize(("text", "role", "final", "button_type"), [
    ("Submit and continue", "next", False, "submit"),   # pagecomp: next; its words: submit
    ("Continue", "next", True, "submit"),               # the reviewer's exact case
    ("Review", "submit", True, "submit"),               # says it moves on; may submit
])
def test_a_control_that_may_submit_is_never_clicked_unconfirmed(
        text: str, role: str, final: bool, button_type: str) -> None:
    form = Form()
    forward = _two_steps(form, text, role, final=final, button_type=button_type)
    result = _wizard_engine(form).run(_ctx())

    assert f"click:{forward.control.name}" not in form.log
    assert result.status == "NO_ADVANCE"
    assert "may send the application" in result.reason


def test_a_plain_next_of_html_type_submit_is_clicked_without_asking() -> None:
    """A <button> with no type is a submit button by the HTML default; most
    multi-step forms mark Next that way. pagecomp's evidence ("Next", role
    next, not final) is what makes it safe — not its type."""
    form = Form()
    forward = _two_steps(form, "Next", "next", final=False, button_type="submit")
    asked: list[str] = []
    ctx = _ctx()
    ctx.confirm_risky = lambda text: asked.append(text) or "click"  # type: ignore[func-returns-value]
    result = _wizard_engine(form).run(ctx)

    assert f"click:{forward.control.name}" in form.log
    assert asked == []
    assert result.status == READY_TO_SUBMIT and result.submit_button is not None
    assert "click:submit" not in form.log, "the final submit is the workflow's, after its gate"


@pytest.mark.parametrize(("verdict", "status"), [("click", READY_TO_SUBMIT),
                                                 ("skip", USER_SKIPPED)])
def test_the_person_decides_a_risky_click(verdict: str, status: str) -> None:
    form = Form()
    forward = _two_steps(form, "Submit and continue", "next", final=False,
                         button_type="submit")
    records: list[StepRecord] = []
    ctx = _ctx(records=records)
    ctx.confirm_risky = lambda text: verdict
    ctx.authorize_dispatch = _token_for
    result = _wizard_engine(form).run(ctx)

    assert result.status == status
    clicked = f"click:{forward.control.name}" in form.log
    assert clicked is (verdict == "click")
    if verdict == "click":
        assert records[0].confirmed_click is True


def test_the_actuator_itself_refuses_a_button_that_may_submit() -> None:
    form = Form()
    submit = _button(form, "Submit application", "submit", final=True)
    actuator = ControlActuator(FakePage(form), FakeTool(form))
    assert actuator.click_button(submit) == (False, "refused-may-submit")
    assert form.log == []
    # A confirmed click is a dispatch: no token, no click (P0-4).
    assert actuator.click_button(submit, confirmed=True) == (False, "refused-no-token")
    assert form.log == []
    ok, _ = actuator.click_button(submit, confirmed=True,
                                  authorize=lambda ident: _token_for(ident, "fp"))
    assert ok and form.log == [f"click:{submit.control.name}"]


def test_a_review_page_after_the_last_step_is_ready_to_submit() -> None:
    form = Form()

    def go() -> None:
        form.current += 1

    nxt = _button(form, "Continue", "next", go)
    submit = _button(form, "Submit application", "submit", final=True)
    _paged(form, [
        ([_text(form, "First name *", "first_name", required=REQUIRED)], [nxt]),
        ([], [submit]),            # "Review your application" — no questions
    ])
    result = _wizard_engine(form).run(_ctx())
    assert result.status == READY_TO_SUBMIT
    assert result.submit_button == submit
    assert [r.step.purpose for r in result.steps] == ["application", "review"]


def test_a_first_page_with_only_buttons_is_not_a_form() -> None:
    form = Form(purpose="review")
    form.steps.append(([], [_button(form, "Apply now", "submit", final=True)], ""))
    assert _engine(form).run(_ctx()).status == NO_FORM


# ─────────────────────────────────────────────────────────────────────────────
# Every required question is accounted for
# ─────────────────────────────────────────────────────────────────────────────


def test_required_questions_beyond_the_per_step_limit_block() -> None:
    """Review finding: an unexamined question is never treated as handled."""
    form = Form()
    late = _text(form, "Referral code *", "referral", required=REQUIRED)
    form.steps.append(([
        _text(form, "First name *", "first_name", required=REQUIRED),
        _text(form, "Email *", "email", required=REQUIRED),
        late,
    ], [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form, max_questions_per_step=2).run(_ctx())

    assert result.status == BLOCKED
    assert result.unanswered == ("Referral code *",)
    assert form.state(late.primary).value == ""


def test_a_question_revealed_by_a_later_answer_is_still_handled() -> None:
    """A question first read while hidden is handled once it is shown, even
    when it sits above the choice that revealed it."""
    form = Form()
    employee_id = _text(form, "Former employee ID *", "text", required=REQUIRED, visible=False)
    worked = _radio(form, "Have you worked here before? *", ("Yes", "No"),
                    on={"Yes": lambda: setattr(form.state(employee_id.primary), "visible", True)})
    answers = Answers(text=Answer(text="Yes", choices=("yes",), source="profile:x",
                                  confidence=0.95))
    form.steps.append(([employee_id, worked],
                       [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form, sources=[answers]).run(_ctx())

    assert form.state(employee_id.primary).value == "Yes"
    assert result.status == READY_TO_SUBMIT


# ─────────────────────────────────────────────────────────────────────────────
# Verification and bounds
# ─────────────────────────────────────────────────────────────────────────────


def test_a_checkbox_group_is_judged_by_its_final_state() -> None:
    """Review finding: a widget that unticks one box when another is ticked."""
    form = Form()
    a = form.add(_ref("skill_a", type_="checkbox"), checked=False)
    b = form.add(_ref("skill_b", type_="checkbox"), checked=False)

    def tick_b() -> None:
        form.state(b).checked = True
        form.state(a).checked = False   # the widget allows one only

    form.state(b).on_click = tick_b
    group = FormQuestion(key="skills", label="Skills", kind=QuestionKind.CHECKBOX_GROUP,
                         field_type="skills", controls=(a, b), required=OPTIONAL,
                         options=(FormOption("Python", control=a), FormOption("SQL", control=b)))
    form.steps.append(([group], [_button(form, "Submit", "submit", final=True)], ""))
    answers = Answers(skills=Answer(many=("Python", "SQL"), source="profile:skills",
                                    confidence=0.95))
    result = _engine(form, sources=[answers]).run(_ctx())

    assert result.counters()["failed"] == 1 and result.counters()["filled"] == 0


def test_waiting_for_a_form_to_settle_is_bounded() -> None:
    """Review finding: the wait ends by the clock whatever the detector says."""
    form = Form()
    q = _text(form, "First name", "first_name")
    form.steps.append(([q], [], ""))
    reads = itertools.count()

    class Restless(FakePage):
        def read_states(self, refs: Any) -> list[ControlState]:
            return [ControlState(present=True, visible=True, value=str(next(reads)))]

        def quiet_detector(self, quiet: int, t_max: float) -> Callable[[object, float], str]:
            return lambda signature, now: "settling"   # a detector that never gives up

    engine = FormStepEngine(Restless(form), FakeTool(form), [_PROFILE],
                            FormEngineSettings(upload_quiet_min_s=0.0),
                            clock=itertools.count().__next__)
    step = FakePage(form).read_step()
    assert step is not None
    assert engine._await_quiet(step, 5.0) is False
    assert next(reads) <= 7


def test_generated_drafts_never_answer_a_protected_question() -> None:
    calls: list[str] = []

    class Model:
        def generate(self, prompt: str, **kw: Any) -> str:
            calls.append(prompt)
            return "A draft."

    source = GeneratedAnswerSource(Model(), object())  # type: ignore[arg-type]
    ctx = AnswerContext(job_title="Analyst", company="Northwind")
    visa = FormQuestion(key="v", label="Describe your visa situation", kind=QuestionKind.TEXTAREA,
                        field_type="text", controls=(_ref("v"),))
    why = FormQuestion(key="w", label="Why this role?", kind=QuestionKind.TEXTAREA,
                       field_type="text", controls=(_ref("w"),))
    assert source.propose(visa, ctx) is None and calls == []
    draft = source.propose(why, ctx)
    assert draft is not None and draft.review and draft.source == "generated"


# ─────────────────────────────────────────────────────────────────────────────
# Second review (Gemini): nothing required is ever left behind; the control
# that may be the form's last button needs evidence before it is clicked
# ─────────────────────────────────────────────────────────────────────────────


def test_a_question_revealed_by_the_persons_own_answer_is_asked_too() -> None:
    """The person answers "Yes" in place, which reveals a required question:
    AA asks for that one as well, and never clicks on with it empty."""
    form = Form()
    employee_id = _text(form, "Former employee ID *", "text", required=REQUIRED, visible=False)
    worked = _radio(form, "Have you worked here before? *", ("Yes", "No"),
                    on={"Yes": lambda: setattr(form.state(employee_id.primary), "visible", True)})
    form.steps.append(([worked, employee_id], [_button(form, "Submit", "submit", final=True)],
                       ""))
    asked: list[str] = []

    def person(question: str, options: list[str], **kw: Any) -> str:
        asked.append(question)
        if len(asked) == 1:
            form.state(worked.options[0].control).on_click()  # type: ignore[union-attr, misc]
        return "done"

    result = _engine(form, sources=[]).run(_ctx(person, assist=True))
    assert len(asked) == 2 and "Former employee ID" in asked[1]
    assert result.status == BLOCKED, "the person did not answer it: never READY"
    assert result.unanswered == ("Former employee ID *",)


def test_a_choice_that_swaps_one_question_for_another_is_noticed() -> None:
    """The census is WHICH controls are shown, not how many."""
    form = Form()
    email = _text(form, "Contact email *", "email", required=REQUIRED)
    phone = _text(form, "Contact phone *", "phone", required=REQUIRED, visible=False)

    def swap() -> None:
        form.state(email.primary).visible = False
        form.state(phone.primary).visible = True

    contact = _radio(form, "Preferred contact *", ("Email", "Phone"), on={"Phone": swap})
    answers = Answers(text=Answer(text="Phone", choices=("phone",), source="profile:x",
                                  confidence=0.95),
                      phone=Answer(text="5551234567", source="profile:phone", confidence=0.95))
    form.steps.append(([contact, email, phone],
                       [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form, sources=[answers]).run(_ctx())

    assert form.state(phone.primary).value == "5551234567"
    assert result.status == READY_TO_SUBMIT


def test_a_required_password_inside_the_form_is_the_persons_to_type() -> None:
    form = Form()
    pw = form.add(_ref("new_password", type_="password"))
    q = FormQuestion(key="pw", label="Choose a password *", kind=QuestionKind.PASSWORD,
                     field_type="password", controls=(pw,), required=REQUIRED)
    form.steps.append(([_text(form, "First name *", "first_name", required=REQUIRED), q],
                       [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form)._work_step(0, FakePage(form).read_step(), _ctx())  # type: ignore[arg-type]
    assert result.unanswered == ("Choose a password *",)
    outcome = next(o for o in result.outcomes if o.key == "pw")
    assert (outcome.action, outcome.reason) == ("asked", "password")
    assert not any(e.endswith(":new_password") for e in form.log if e.startswith(("type", "retype")))


def _one_forward(form: Form, text: str, *, button_type: str, label: str = "",
                 extra_submit: bool = False, hidden_later: bool = False) -> FormButton:
    def go() -> None:
        form.current += 1

    forward = _button(form, text, "next", go, button_type=button_type)
    buttons = [forward]
    if extra_submit:
        buttons.append(_button(form, "Submit application", "submit", final=True))
    questions = [_text(form, "First name *", "first_name", required=REQUIRED)]
    if hidden_later:
        questions.append(_text(form, "Later question", "text", visible=False))
    form.steps.append((questions, buttons, label))
    form.steps.append(([_text(form, "Email *", "email", required=REQUIRED)],
                       [_button(form, "Send", "submit", final=True)], ""))
    return forward


def test_a_submit_type_continue_with_no_sign_of_more_steps_is_not_clicked() -> None:
    """Both reviews: <button type=submit>Continue</button> may be a form's
    last button. Without evidence of another step it is asked about."""
    form = Form()
    forward = _one_forward(form, "Continue", button_type="submit")
    result = _engine(form).run(_ctx())
    assert result.status == "NO_ADVANCE"
    assert f"click:{forward.control.name}" not in form.log


@pytest.mark.parametrize("evidence", ["label", "extra_submit", "label_de", "label_ja"])
def test_evidence_of_more_steps_makes_a_submit_type_continue_safe(evidence: str) -> None:
    labels = {"label": "Step 1 of 2", "label_de": "Schritt 1 von 2", "label_ja": "ステップ 1/2"}
    form = Form()
    forward = _one_forward(form, "Continue", button_type="submit",
                           label=labels.get(evidence, ""),
                           extra_submit=evidence == "extra_submit")
    asked: list[str] = []
    ctx = _ctx()
    ctx.confirm_risky = lambda text: asked.append(text) or "skip"  # type: ignore[func-returns-value]
    _engine(form).run(ctx)
    assert f"click:{forward.control.name}" in form.log and asked == []


def test_a_hidden_conditional_question_is_not_evidence_of_another_step() -> None:
    """Round-3 BLOCKER (ChatGPT): a question of the form that is not shown
    (a conditional one) says nothing about another step — it can be hidden on
    the last page as well as on any other. A submit-type "Continue" on such a
    page is asked about, never clicked unconfirmed."""
    form = Form()
    forward = _one_forward(form, "Continue", button_type="submit", hidden_later=True)
    asked: list[str] = []
    ctx = _ctx()
    ctx.confirm_risky = lambda text: asked.append(text) or "skip"  # type: ignore[func-returns-value]
    result = _engine(form).run(ctx)
    assert f"click:{forward.control.name}" not in form.log
    assert asked == ["Continue"] and result.status == "USER_SKIPPED"


def test_a_weak_separate_control_is_not_evidence_either() -> None:
    """Only a separate control that SAYS it submits establishes that the
    submit-type "Continue" is a step control; an unclassified "Save" does not."""
    form = Form()
    forward = _one_forward(form, "Continue", button_type="submit")
    form.steps[0][1].append(_button(form, "Save", "other", final=True, button_type="button"))
    asked: list[str] = []
    ctx = _ctx()
    ctx.confirm_risky = lambda text: asked.append(text) or "skip"  # type: ignore[func-returns-value]
    _engine(form).run(ctx)
    assert f"click:{forward.control.name}" not in form.log


@pytest.mark.parametrize("text", ["Confirm", "Save"])
def test_an_unclassified_last_button_is_offered_at_the_gate_not_dropped(text: str) -> None:
    """Gemini: an unclassified "Confirm" button gave NO_ADVANCE. "Confirm" now
    reads as a submit word; any other unclassified button that may submit
    ("Save") is offered at the gate as the last resort, by its text."""
    form = Form()
    last = _button(form, text, "other", final=True, button_type="button")
    form.steps.append(([_text(form, "First name *", "first_name", required=REQUIRED)],
                       [last], ""))
    result = _engine(form).run(_ctx())
    assert result.status == READY_TO_SUBMIT and result.submit_button == last
    assert f"click:{last.control.name}" not in form.log


def test_a_multi_select_is_all_or_nothing() -> None:
    form = Form()
    ref = form.add(_ref("langs", tag="select"))
    q = FormQuestion(key="langs", label="Languages", kind=QuestionKind.MULTI_SELECT,
                     field_type="text", controls=(ref,),
                     options=(FormOption("English"), FormOption("Spanish")))
    form.steps.append(([q], [], ""))
    out = ControlActuator(FakePage(form), FakeTool(form)).fill(
        q, Answer(many=("English", "Klingon"), source="profile:x", confidence=0.95))
    assert out.ok is False and out.reason == "partial"


def test_a_required_answer_the_page_cleared_is_caught_before_next() -> None:
    """The sweep: a required question already handled (here: kept as
    prefilled) that a later choice emptied, with no change in which controls
    are shown, is unresolved — never clicked past."""
    form = Form()
    city = _text(form, "City *", "city", required=REQUIRED, value="Springfield")

    def reset_city() -> None:
        form.state(city.primary).value = ""   # the site re-renders the address block

    country = _radio(form, "Country *", ("Canada", "USA"), on={"Canada": reset_city})
    answers = Answers(text=Answer(text="Canada", choices=("canada",), source="profile:x",
                                  confidence=0.95))
    form.steps.append(([city, country], [_button(form, "Submit", "submit", final=True)], ""))
    result = _engine(form, sources=[answers]).run(_ctx())
    assert result.status == BLOCKED and result.unanswered == ("City *",)


# ─────────────────────────────────────────────────────────────────────────────
# Accessibility (docs/adr/024) and languages (docs/adr/025)
# ─────────────────────────────────────────────────────────────────────────────


def _licence(form: Form) -> FormQuestion:
    q = _radio(form, "Do you hold a valid driving licence? *", ("Yes", "No"))
    _one_page(form, q)
    return q


def test_a_choice_question_is_answered_in_aa_s_window_and_checked() -> None:
    """answer_in_aa: the person picks from the form's own options in AA's
    window; AA selects it, reads it back, and records it as theirs."""
    form = Form()
    q = _licence(form)
    calls: list[dict[str, Any]] = []

    def gate(question: str, options: list[str], **kw: Any) -> str:
        calls.append({"options": options, **kw})
        return "No"

    result = _engine(form, answer_in_aa=True).run(_ctx(approving(gate), assist=True))
    assert result.status == READY_TO_SUBMIT
    assert form.state(q.options[1].control).checked is True  # type: ignore[arg-type]
    assert calls[0]["options"] == ["Yes", "No", "answer in the browser", "skip"]
    assert calls[0]["private"] is True
    outcome = next(o for s in result.steps for o in s.outcomes if o.key == q.key)
    assert (outcome.action, outcome.reason, outcome.review) == ("human", "answered-in-aa", True)
    assert result.counters()["human"] == 1


def test_a_free_text_question_is_typed_in_aa_s_window() -> None:
    form = Form()
    q = _with_unanswerable(form)

    def gate(question: str, options: list[str], *, checkpoint: str, timeout: float | None,
             kind: str = "choice", private: bool = False) -> str:
        assert kind == "text" and private and options == ["skip"]
        return "A former colleague"

    result = _engine(form, answer_in_aa=True).run(_ctx(approving(gate), assist=True))
    assert result.status == READY_TO_SUBMIT
    assert form.state(q.primary).value == "A former colleague"


def test_answering_in_the_browser_instead_moves_the_focus_there() -> None:
    form = Form()
    q = _licence(form)
    asked: list[str] = []

    def gate(question: str, options: list[str], **kw: Any) -> str:
        asked.append(question)
        if "answer in the browser" in options:
            return "answer in the browser"
        form.state(q.options[0].control).checked = True  # type: ignore[arg-type]
        return "done"

    result = _engine(form, answer_in_aa=True).run(_ctx(approving(gate), assist=True))
    assert result.status == READY_TO_SUBMIT and len(asked) == 2
    first = q.options[0].control.name  # type: ignore[union-attr]
    assert f"scroll:{first}" in form.log and f"focus:{first}" in form.log
    assert "keyboard focus" in asked[1]


def test_skip_in_aa_s_window_leaves_the_application() -> None:
    form = Form()
    _licence(form)
    result = _engine(form, answer_in_aa=True).run(_ctx(lambda *a, **k: "skip", assist=True))
    assert result.status == USER_SKIPPED


def test_the_focus_can_be_turned_off() -> None:
    form = Form()
    q = _with_unanswerable(form)

    def gate(*a: Any, **k: Any) -> str:
        form.state(q.primary).value = "A friend"
        return "done"

    _engine(form, focus_asked_field=False).run(_ctx(gate, assist=True))
    assert not any(e.startswith(("focus:", "scroll:")) for e in form.log)


def test_the_prompt_says_where_the_question_is_and_in_what_language() -> None:
    form = Form()
    form.language = "de"
    q = _text(form, "Wie haben Sie von uns erfahren? *", "referral", required=REQUIRED)
    nxt = _button(form, "Weiter", "next")
    sub = _button(form, "Absenden", "submit", final=True)
    _paged(form, [([q], [nxt]), ([], [sub])])
    asked: list[str] = []

    def gate(question: str, options: list[str], **kw: Any) -> str:
        asked.append(question)
        form.state(q.primary).value = "Freund"
        return "done"

    _engine(form).run(_ctx(gate, assist=True))
    assert "step 1 of 2" in asked[0]
    assert "Deutsch" in asked[0] and "Wie haben Sie von uns erfahren?" in asked[0]


def test_an_accommodation_question_is_never_answered_by_a_source() -> None:
    form = Form()
    q = _text(form, "Do you need any accommodation for the interview? *", "text",
              required=REQUIRED)
    _one_page(form, q)
    always = Answers(text=Answer(text="No", source="template", confidence=0.99))
    result = _engine(form, sources=[_PROFILE, always]).run(_ctx())
    outcome = next(o for s in result.steps for o in s.outcomes if o.key == q.key)
    assert outcome.sensitive and outcome.action != "filled"
    assert form.state(q.primary).value in ("", None)


def test_a_checkbox_that_updates_late_is_waited_for_not_clicked_twice() -> None:
    """Round-3 (ChatGPT): clicking the label after an input click that had
    not *yet* registered toggles the box twice. AA waits (bounded) for the
    late update and clicks the label only if the input never changed."""
    form = Form()
    ref = form.add(_ref("agree", type_="checkbox"), checked=False)
    label = form.add(_ref("agree_label", tag="label"), label_for=ref)
    late: list[Callable[[], None]] = []

    def toggle_later() -> None:
        st = form.state(ref)
        late.append(lambda: setattr(st, "checked", not st.checked))

    form.state(ref).on_click = toggle_later
    tool = FakeTool(form)

    def settle() -> None:
        while late:
            late.pop(0)()

    tool.settle = settle  # type: ignore[method-assign]
    q = FormQuestion(key="I agree *", label="I agree *", kind=QuestionKind.CHECKBOX,
                     field_type="checkbox", controls=(ref,), required=REQUIRED,
                     options=(FormOption("I agree", control=ref, click_target=label),))
    out = ControlActuator(FakePage(form), tool).fill(
        q, Answer(checked=True, source="test", confidence=1.0))
    settle()
    assert form.state(ref).checked is True, out
    assert form.log.count(f"click:{ref.name}") == 1
    assert f"click:{label.name}" not in form.log


class _UnreadablePage(FakePage):
    """A page whose state read for one control fails (the script raised)."""

    def __init__(self, form: Form, broken: ControlRef) -> None:
        super().__init__(form)
        self.broken = broken

    def read_states(self, refs: list[ControlRef]) -> list[ControlState]:
        states = super().read_states(refs)
        return [ControlState(present=False, read_failed=True) if r == self.broken else s
                for r, s in zip(refs, states)]


def test_a_required_question_that_cannot_be_read_is_never_treated_as_handled() -> None:
    """Round-3 (ChatGPT): a failed visibility read is UNKNOWN, not "not
    shown" — the step is never left with a required question unverified."""
    form = Form()
    _one_page(form)
    first = form.steps[0][0][0]
    ticks = itertools.count()
    engine = FormStepEngine(_UnreadablePage(form, first.primary), FakeTool(form), [_PROFILE],
                            FormEngineSettings(reading_pause_ms_per_char=0,
                                               upload_quiet_min_s=0.0),
                            clock=lambda: float(next(ticks)))
    result = engine.run(_ctx())
    assert result.status != READY_TO_SUBMIT
    assert any(first.label[:20] in u for u in result.unanswered)
    reasons = {o.reason for s in result.steps for o in s.outcomes if o.key == first.key}
    assert "state-unreadable" in reasons
