"""The engine's answer review, test pages, external steps and choice limits.

docs/adr/026. Built on the in-memory form of ``test_form_engine``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from auto_apply.application.services.form_engine import (
    ASSESSMENT,
    READY_TO_SUBMIT,
    USER_SKIPPED,
)
from auto_apply.domain.applications.answers import Answer
from auto_apply.domain.applications.form_model import (
    OPTIONAL,
    REQUIRED,
    FormLink,
    FormOption,
    FormQuestion,
    FormStep,
    QuestionKind,
)

from .test_form_engine import (
    _PROFILE,
    Answers,
    FakePage,
    Form,
    _button,
    _ctx,
    _engine,
    _ref,
    _text,
)


class _ExtrasPage(FakePage):
    """A page whose steps also carry links and test signals."""

    def __init__(self, form: Form, extras: dict[int, dict[str, Any]]) -> None:
        super().__init__(form)
        self.extras = extras

    def read_step(self) -> FormStep | None:
        step = super().read_step()
        extra = self.extras.get(self.form.current, {})
        if step is None or not extra:
            return step
        return replace(step, **extra)


def _engine_on(form: Form, extras: dict[int, dict[str, Any]], **settings: Any):
    engine = _engine(form, **settings)
    engine._page = _ExtrasPage(form, extras)  # noqa: SLF001 - test seam
    engine._actuator._page = engine._page  # noqa: SLF001
    return engine


def _gate(log: list[str], answer: str = "done"):
    def gate(question: str, options: list[str], *, checkpoint: str, **kw: Any) -> str:
        log.append(checkpoint)
        return answer if answer in options else options[0]
    return gate


def _saved_template(text: str = "I like the mission.") -> Answers:
    return Answers(open_text=Answer(text=text, source="saved", confidence=0.85, review=True),
                   first_name=Answer(text="Ada", source="profile:first_name",
                                     confidence=0.95))


def _open_page(form: Form) -> None:
    submit = _button(form, "Submit application", "submit", final=True)
    form.steps.append(([_text(form, "First name *", "first_name", required=REQUIRED),
                        _text(form, "Why this role? *", "open_text", required=REQUIRED,
                              kind=QuestionKind.TEXTAREA)], [submit], ""))


# ── answer review: trust ────────────────────────────────────────────────────


def _open_text_state(form: Form) -> Any:
    q = next(q for q in form.steps[0][0] if q.key == "Why this role? *")
    return form.state(q.primary)


def test_by_default_a_saved_answer_is_shown_before_it_is_written_and_a_name_is_not() -> None:
    """Phase 0 (P0-5), the pre-write gate: an answer that needs the person
    is shown with its value BEFORE anything is typed; a plain profile fact
    is not. TEETH: fails while the engine fills first and asks afterwards."""
    form = Form()
    _open_page(form)
    asked: list[tuple[str, str, bool]] = []

    def gate(question: str, options: list[str], *, checkpoint: str,
             private: bool = False, **kw: Any) -> str:
        # Nothing has been typed into the field when the person is asked.
        asked.append((checkpoint, _open_text_state(form).value, private))
        assert "I like the mission." in question, "the value is shown for approval"
        return "approve"

    result = _engine(form, sources=[_saved_template()]).run(_ctx(gate))
    assert result.status == READY_TO_SUBMIT
    assert asked == [("ANSWER_REVIEW", "", True)], "asked once, before the write, privately"
    assert _open_text_state(form).value == "I like the mission."
    assert result.pending_reviews() == []
    assert result.counters()["needs_review"] == 1 and result.counters()["reviewed"] == 1


def test_with_no_one_to_ask_an_answer_that_needs_the_person_is_never_written() -> None:
    """TEETH: fails while the engine writes the answer and holds it back."""
    form = Form()
    _open_page(form)
    result = _engine(form, sources=[_saved_template()]).run(_ctx())
    assert _open_text_state(form).value == "", "nothing the person has not seen is typed"
    assert result.status != READY_TO_SUBMIT
    outcome = next(o for s in result.steps for o in s.outcomes if o.key == "Why this role? *")
    assert (outcome.action, outcome.reason) == ("asked", "needs-review-no-gate")


def test_answer_myself_leaves_the_field_for_the_person() -> None:
    form = Form()
    _open_page(form)

    def gate(question: str, options: list[str], *, checkpoint: str, **kw: Any) -> str:
        if checkpoint == "ANSWER_REVIEW":
            return "answer myself"
        _open_text_state(form).value = "My own words"   # typed in the browser
        return "done"

    result = _engine(form, sources=[_saved_template()]).run(_ctx(gate, assist=True))
    assert result.status == READY_TO_SUBMIT
    assert _open_text_state(form).value == "My own words"
    outcome = next(o for s in result.steps for o in s.outcomes if o.key == "Why this role? *")
    assert outcome.action == "human"


def test_own_words_trust_sends_a_saved_answer_without_review() -> None:
    form = Form()
    _open_page(form)
    result = _engine(form, sources=[_saved_template()], answer_trust="own_words").run(_ctx())
    assert result.pending_reviews() == []


def test_an_unsure_answer_is_reviewed_at_every_trust_level() -> None:
    form = Form()
    _open_page(form)
    unsure = Answers(open_text=Answer(text="Maybe", source="saved", confidence=0.78),
                     first_name=Answer(text="Ada", source="profile:first_name",
                                       confidence=0.95))
    asked: list[str] = []
    result = _engine(form, sources=[unsure], answer_trust="drafts").run(_ctx(_gate(asked)))
    assert asked == ["ANSWER_REVIEW"], "below the confidence floor: shown at every trust level"
    assert result.pending_reviews() == []


# ── answer review: timing ───────────────────────────────────────────────────


def test_each_timing_asks_as_the_answer_is_filled() -> None:
    form = Form()
    _open_page(form)
    asked: list[str] = []
    result = _engine(form, sources=[_saved_template()], review_timing="each").run(
        _ctx(_gate(asked), assist=True))
    assert asked == ["ANSWER_REVIEW"]
    assert result.pending_reviews() == [] and result.counters()["reviewed"] == 1


def test_page_timing_asks_once_for_the_page() -> None:
    form = Form()
    submit = _button(form, "Submit application", "submit", final=True)
    form.steps.append(([_text(form, "Why this role? *", "open_text", required=REQUIRED,
                              kind=QuestionKind.TEXTAREA),
                        _text(form, "Why us? *", "open_text", required=REQUIRED,
                              kind=QuestionKind.TEXTAREA)], [submit], ""))
    asked: list[str] = []
    result = _engine(form, sources=[_saved_template()], review_timing="page").run(
        _ctx(_gate(asked), assist=True))
    assert asked == ["ANSWER_REVIEW"], "one question for the whole page"
    assert result.pending_reviews() == []


def test_a_person_who_skips_at_the_review_skips_the_application() -> None:
    form = Form()
    _open_page(form)
    asked: list[str] = []
    result = _engine(form, sources=[_saved_template()], review_timing="each").run(
        _ctx(_gate(asked, "skip"), assist=True))
    assert result.status == USER_SKIPPED


def test_with_no_one_to_ask_no_timing_writes_an_unseen_answer() -> None:
    """each/page/end cannot ask without a gate: the answer is not written
    at all (Phase 0 — before, it was written and held for the end)."""
    for timing in ("each", "page", "end"):
        form = Form()
        _open_page(form)
        _engine(form, sources=[_saved_template()], review_timing=timing).run(_ctx())
        assert _open_text_state(form).value == "", timing


# ── tests and external steps ────────────────────────────────────────────────


def test_a_test_page_with_no_one_to_hand_it_to_stops_the_application() -> None:
    form = Form()
    _open_page(form)
    result = _engine_on(form, {0: {"test_signals": ("role=timer",)}}).run(_ctx())
    assert result.status == ASSESSMENT
    assert "role=timer" in result.reason


def test_a_test_page_is_handed_to_the_person_and_the_form_goes_on() -> None:
    form = Form()
    _open_page(form)
    extras: dict[int, dict[str, Any]] = {0: {"test_signals": ("code-editor",)}}
    asked: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str, **kw: Any) -> str:
        asked.append(checkpoint)
        extras.clear()  # the person finished the test; the form is back
        return "done"

    result = _engine_on(form, extras, sources=[_PROFILE]).run(_ctx(gate, assist=True))
    assert asked[0] == "ASSESSMENT"
    assert result.status != ASSESSMENT


def test_assessment_links_are_reported_with_their_host_never_followed() -> None:
    form = Form()
    _open_page(form)
    links = (FormLink("https://www.hackerrank.com/test/abc123?token=secret", "Start the test",
                      "Complete the coding test at the link below. Applications without "
                      "it will not be reviewed."),
             FormLink("https://jobs.example/privacy", "Privacy", "Read our privacy policy"))
    result = _engine_on(form, {0: {"links": links}}).run(_ctx())
    assert [(e.kind, e.host, e.required) for e in result.external_steps] == [
        ("assessment", "hackerrank.com", True)]
    assert result.required_external_steps()
    assert form.log.count("click:start_the_test") == 0


# ── selection limits ────────────────────────────────────────────────────────


def _group(form: Form, label: str, choices: tuple[str, ...], *, low: int, high: int,
           required: str = REQUIRED) -> FormQuestion:
    opts = []
    refs = []
    for c in choices:
        ref = form.add(_ref(f"skill_{c.lower()}", type_="checkbox"), checked=False)

        def tick(ref=ref) -> None:
            form.state(ref).checked = not form.state(ref).checked
        form.state(ref).on_click = tick
        refs.append(ref)
        opts.append(FormOption(c, control=ref))
    return FormQuestion(key=label, label=label, kind=QuestionKind.CHECKBOX_GROUP,
                        field_type="skills", controls=tuple(refs), required=required,
                        options=tuple(opts), choose_min=low, choose_max=high)


def test_never_more_choices_than_the_question_allows() -> None:
    """'Pick the best 2' with three remembered choices: AA ticks none and
    asks the person (required), or leaves it (optional)."""
    form = Form()
    submit = _button(form, "Submit application", "submit", final=True)
    # No limit given: the engine reads it from the words ("best 2").
    q = _group(form, "Pick the best 2 *", ("Python", "SQL", "Go"), low=0, high=0)
    form.steps.append(([q], [submit], ""))
    three = Answers(skills=Answer(text="Python", many=("Python", "SQL", "Go"),
                                  source="session", confidence=0.9))
    result = _engine(form, sources=[three]).run(_ctx())
    outcome = result.steps[0].outcomes[0]
    assert outcome.action == "asked" and outcome.reason.startswith("selection-limit")
    assert not any(form.state(r).checked for r in q.controls)


def test_an_answer_that_fits_the_limit_is_ticked() -> None:
    form = Form()
    submit = _button(form, "Submit application", "submit", final=True)
    q = _group(form, "Pick up to 2", ("Python", "SQL", "Go"), low=0, high=2,
               required=OPTIONAL)
    form.steps.append(([q], [submit], ""))
    two = Answers(skills=Answer(text="Python", many=("Python", "SQL"), source="session",
                                confidence=0.9))
    _engine(form, sources=[two]).run(_ctx())
    assert [form.state(r).checked for r in q.controls] == [True, True, False]


# ── the per-page log line (live diagnosis) ──────────────────────────────────


def test_each_new_page_is_described_once_in_the_log_without_values(caplog) -> None:
    """The page is read again after the person answers; it is logged once."""
    form = Form()
    _open_page(form)
    asked: list[str] = []
    only_name = Answers(first_name=Answer(text="Ada", source="profile:first_name",
                                          confidence=0.95))
    with caplog.at_level(logging.INFO, logger="auto_apply.application.services.form_engine"):
        _engine(form, sources=[only_name]).run(_ctx(_gate(asked, "done"), assist=True))
    assert asked, "the person was asked, so the page was read more than once"
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("form engine: read")]
    assert len(lines) == 1, lines
    assert "'Why this role? *'*:textarea" in lines[0] and "'Submit application':submit" in lines[0]
    assert "Ada" not in lines[0], "never a value"
