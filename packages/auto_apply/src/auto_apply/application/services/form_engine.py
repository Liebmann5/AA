"""The application step engine: read, decide, act, verify, advance. Application layer.

This is the form-filling half of the Applications engine (Track A slices
S5-S9). ``ApplicationsWorkflow`` gets the browser to the application and owns
the irreversible submit; this engine owns everything between: every step of
the form, every question on each step, the person's help when it is needed,
and the proof that each answer took.

One step, in order:

1. **Read** the step (pagecomp, through ``FormPagePort``), apply AA's
   knowledge of the form's language (``form_localization.localize_step``,
   docs/adr/025: structure first, words as data, the person last) and read
   every control back live: what is visible on *this* step, what already
   holds a value, what is disabled.
2. **Uploads first.** The résumé goes in before anything is typed, because
   most applicant-tracking systems parse it and pre-fill the form; the step is
   then read again and only what is still empty is filled.
3. **Each question, in page order:** a short reading pause (the tool's
   pacing), an answer from the configured sources, the policy's decision
   (``domain/applications/fill_policy.py``), the act and the read-back
   (``form_actuator.py``). A choice that can reveal or withdraw questions is
   followed by a cheap census of rendered controls; a change triggers a fresh
   read and the new questions join the agenda (pagecomp's conditional-field
   fixpoint, CT-ALG-ConditionalLoop, applied live).
4. **Ask** for what AA cannot answer — only when asking is allowed
   (``applications.assist_mode``) — while the browser shows the very page the
   questions are on, with the keyboard focus on the first of them. The person
   answers in the browser and says "done", or — their accommodation choice,
   docs/adr/024 — answers in AA's own window and AA enters it; either way the
   engine reads the page again and verifies. Every question says where it is
   ("step 2 of 4"), in the person's language, and that the form is in
   another language when it is. Their answers are remembered for the rest of
   the session (in memory only) so the same question on the next application
   is not asked again.
5. **Advance** with the step's Next control only when every question the
   reader marked required holds a value, and only count it as progress when
   the page proves it: the set of visible questions changed or the address
   changed. Questions the reader could not classify as required are left to
   the page's own validation: a step that did not move is read for its
   validation messages, which are bound to their questions; the person is
   asked about those, or the application ends honestly. ``READY_TO_SUBMIT``
   therefore means "every question AA knew to be required holds a value",
   never "the site will accept it".

**No submit without consent.** The engine clicks a button only to move the
form on, and only through ``ControlActuator.click_button``, which refuses any
button that may submit (:attr:`FormButton.may_submit`: pagecomp's
conservative ``final`` verdict — CT-INV-004 — a ``submit`` role, or submit
words in its text in any language, as in "Submit and continue" or
"Envoyer"). When the only way on is such a button, the
person is asked first (``FormRunContext.confirm_risky``, which the workflow
answers exactly like its submit gate); without that, the run ends
``NO_ADVANCE``. The final submit is never clicked here: the run ends
``READY_TO_SUBMIT`` and the workflow applies the fail-closed submit gate.

A step with no questions after an advance is a review page ("check your
answers", then Submit): its Next or Submit control is handled the same way.

Account walls. A step that asks for a password is a sign-in or account step:
AA never types a password and never creates an account. With assistance
allowed, the person is asked to sign in or create the account in the browser
window; otherwise the run ends ``ACCOUNT_REQUIRED``.

Determinism: the engine's decisions depend only on the page and the person's
data; all timing and randomness live in the interaction tool.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from auto_apply.application.services.form_actuator import (
    ActuatorSettings,
    ControlActuator,
    FillOutcome,
    FormTool,
)
from auto_apply.application.services.hitl_gate import (
    SKIP,
    ask_gate,
    ask_text,
    can_ask_text,
)
from auto_apply.application.services.i18n import (
    current_language,
    get_text,
    language_name,
)
from auto_apply.domain.applications.answer_review import (
    DEFAULT_FLOOR,
    needs_review,
    normal_timing,
    normal_trust,
)
from auto_apply.domain.applications.answers import (
    Answer,
    AnswerContext,
    SessionAnswerMemory,
    is_protected,
    question_text,
)
from auto_apply.domain.applications.external_steps import (
    ExternalStep,
    external_steps,
    is_test_step,
)
from auto_apply.domain.applications.fill_policy import (
    ASK,
    FILL_ACTION,
    FillSettings,
    decide,
)
from auto_apply.domain.applications.form_language import best_class, primary_tag, says
from auto_apply.domain.applications.form_localization import localize_step
from auto_apply.domain.applications.form_model import (
    FILL,
    REQUIRED,
    UNKNOWN,
    ControlState,
    FormButton,
    FormQuestion,
    FormStep,
    QuestionKind,
    says_submit,
)
from auto_apply.domain.applications.option_matching import is_placeholder
from auto_apply.domain.ports.form_page_port import AnswerSourcePort, FormPagePort
from auto_apply.domain.ports.text_generation_port import TextGenerationPort

logger = logging.getLogger(__name__)

READY_TO_SUBMIT = "READY_TO_SUBMIT"
NO_FORM = "NO_FORM"
ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
BLOCKED = "BLOCKED"
USER_SKIPPED = "USER_SKIPPED"
LOOP = "LOOP"
NO_ADVANCE = "NO_ADVANCE"
MAX_STEPS = "MAX_STEPS"
#: The page is a test (a timer, a code editor): AA never takes tests for the
#: person, and no one could be asked to take it (docs/adr/026).
ASSESSMENT = "ASSESSMENT"

#: Last-resort bound on readings while waiting for a form to settle.
_QUIET_MAX_READS = 400
#: The answer sources that carry the person's own declaration: the only ones
#: a protected question may be answered from (``FormStepEngine._resolve``).
_DECLARED_SOURCES = ("profile:legal_info.", "profile:eeo_info.",
                     "profile:personal_info.pronouns", "session", "human")
#: Options AA adds to a question it asks in its own window (protocol tokens;
#: the interface shows them in the person's language: ``i18n.option_label``).
IN_BROWSER = "answer in the browser"
TICK = "tick it"
LEAVE_UNTICKED = "leave it unticked"
#: At most this many options are offered in AA's window; a longer list
#: (every country of the world) is answered in the browser, where the form's
#: own search helps.
_MAX_AA_OPTIONS = 30
#: How a click on a forward control went (``StepRecord.click``).
CLICKED = "clicked"
NOT_CLICKED = "not-clicked"
CLICK_UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class FormEngineSettings:
    """Knobs of the step engine (``applications.*`` in runtime_defaults.yaml)."""

    max_steps: int = 12
    max_questions_per_step: int = 80
    max_assists_per_step: int = 2
    assist_timeout_s: float = 900.0
    review_each_step: bool = False
    remember_answers: bool = True
    reading_pause_ms_per_char: float = 18.0
    reading_pause_max_s: float = 2.0
    upload_settle_s: float = 8.0
    upload_quiet_min_s: float = 1.5
    advance_settle_s: float = 8.0
    #: Accessibility (``accessibility.*``): offer the questions AA cannot
    #: answer in AA's own window, and move the browser's keyboard focus to a
    #: question AA asks the person to answer there.
    answer_in_aa: bool = False
    focus_asked_field: bool = True
    max_questions_in_aa: int = 12
    #: Which answers the person must see before they are sent, and when
    #: (``domain/applications/answer_review.py``; docs/adr/026). Independent
    #: of the submission setting.
    answer_trust: str = "never"
    review_timing: str = "end"
    review_below_confidence: float = DEFAULT_FLOOR
    fill: FillSettings = field(default_factory=FillSettings)
    actuator: ActuatorSettings = field(default_factory=ActuatorSettings)

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> FormEngineSettings:
        app = cfg.get("applications") if isinstance(cfg, Mapping) else None
        a: Mapping[str, Any] = app if isinstance(app, Mapping) else {}
        acc = cfg.get("accessibility") if isinstance(cfg, Mapping) else None
        x: Mapping[str, Any] = acc if isinstance(acc, Mapping) else {}

        def num(key: str, default: float) -> float:
            try:
                return float(a.get(key, default))
            except (TypeError, ValueError):
                return default

        return cls(
            max_steps=int(num("max_pages", 12)),
            max_questions_per_step=int(num("max_questions_per_step", 80)),
            max_assists_per_step=int(num("max_assists_per_step", 2)),
            assist_timeout_s=num("assist_timeout_s", 900.0),
            review_each_step=bool(a.get("review_each_step", False)),
            remember_answers=bool(a.get("remember_answers", True)),
            reading_pause_ms_per_char=num("reading_pause_ms_per_char", 18.0),
            reading_pause_max_s=num("reading_pause_max_s", 2.0),
            upload_settle_s=num("upload_settle_s", 8.0),
            upload_quiet_min_s=num("upload_quiet_min_s", 1.5),
            advance_settle_s=num("dom_stabilization_timeout_s", 8.0),
            answer_in_aa=bool(x.get("answer_in_aa", False)),
            focus_asked_field=bool(x.get("focus_asked_field", True)),
            answer_trust=normal_trust(a.get("answer_trust")),
            review_timing=normal_timing(a.get("review_timing")),
            review_below_confidence=num("review_below_confidence", DEFAULT_FLOOR),
            fill=FillSettings(
                min_confidence=num("min_answer_confidence", 0.75),
                overwrite_prefilled=bool(a.get("overwrite_prefilled", False)),
                acknowledge_required=bool(a.get("acknowledge_required", True)),
            ),
            actuator=ActuatorSettings(
                script_fallback=bool(a.get("script_fill_fallback", True)),
                chunk_threshold=int(num("type_chunk_threshold", 240)),
                option_threshold=num("option_match_threshold", 0.6),
            ),
        )


@dataclass(frozen=True)
class QuestionOutcome:
    """One question's fate on one step. Never carries the answer's value."""

    key: str
    label: str
    kind: str
    field_type: str
    required: str
    sensitive: bool
    action: str            # filled | left | asked | human | failed
    reason: str
    source: str = ""
    rung: str = ""
    review: bool = False
    #: How the question's meaning was known: ``structure`` (autocomplete,
    #: input type), ``lexicon(<lang>)`` (a word in that language), ``widget``
    #: (only the widget's shape) — the run's language coverage, as evidence.
    typed_by: str = ""
    #: The person must see this answer before it is sent (answer_review), and
    #: whether they have.
    needs_review: bool = False
    reviewed: bool = False


def typed_by(q: FormQuestion) -> str:
    """The evidence category of a question's type (see ``QuestionOutcome``)."""
    src = q.type_source or ""
    if src.startswith(("autocomplete", "type=email", "type=tel", "type=url", "type=file",
                       "type=date", "type=password", "type=number")):
        return "structure"
    if src.startswith("lexicon("):
        return src.split("+", 1)[0]
    return "widget"


@dataclass(frozen=True)
class StepRecord:
    index: int
    step: FormStep
    outcomes: tuple[QuestionOutcome, ...]
    advanced_by: str = ""
    errors: tuple[str, ...] = ()
    seconds: float = 0.0
    #: The control used to move on may have submitted; the person (or their
    #: autonomous-submission setting) confirmed the click.
    confirmed_click: bool = False
    #: How the click on ``advanced_by`` went: ``clicked``, ``uncertain`` (the
    #: tool failed mid-click: it may have happened) or ``not-clicked``.
    click: str = ""


@dataclass(frozen=True)
class FormRunResult:
    status: str
    reason: str = ""
    submit_button: FormButton | None = None
    final_step: FormStep | None = None
    steps: tuple[StepRecord, ...] = ()
    unanswered: tuple[str, ...] = ()
    #: Assessments and other forms the application sends the person to.
    external_steps: tuple[ExternalStep, ...] = ()

    def pending_reviews(self) -> list[str]:
        """Answers the person must still see before the application is sent."""
        out: list[str] = []
        for s in self.steps:
            for o in s.outcomes:
                if o.action == "filled" and o.needs_review and not o.reviewed:
                    label = o.label.strip() or o.field_type
                    if label not in out:
                        out.append(label)
        return out

    def required_external_steps(self) -> list[ExternalStep]:
        return [e for e in self.external_steps if e.required]

    def counters(self) -> dict[str, Any]:
        """Aggregate counts for the evidence record (no values, no labels)."""
        c: Counter[str] = Counter()
        by_source: Counter[str] = Counter()
        rungs: Counter[str] = Counter()
        typing: Counter[str] = Counter()
        for s in self.steps:
            for o in s.outcomes:
                c[o.action] += 1
                if o.typed_by:
                    typing[o.typed_by] += 1
                if o.action in ("filled", "human"):
                    if o.required == REQUIRED:
                        c["required_filled"] += 1
                    else:
                        c["optional_filled"] += 1
                    by_source[o.source.split(":", 1)[0] or "unknown"] += 1
                if o.rung:
                    rungs[o.rung] += 1
                if o.action == "left" and o.reason.startswith("reader-decision:trap"):
                    c["traps_left"] += 1
                if o.action == "left" and o.reason == "prefilled":
                    c["prefilled"] += 1
                if o.action == "filled" and o.field_type in ("resume", "cover_letter") \
                        and o.kind == QuestionKind.FILE:
                    c["uploads"] += 1
                if o.action == "filled" and o.needs_review:
                    c["needs_review"] += 1
                    if o.reviewed:
                        c["reviewed"] += 1
                if o.reason.startswith("selection-limit"):
                    c["selection_limited"] += 1
            c["validation_errors"] += len(s.errors)
        return {
            "steps": len(self.steps),
            "filled": c["filled"],
            "human": c["human"],
            "left": c["left"],
            "failed": c["failed"],
            "required_filled": c["required_filled"],
            "optional_filled": c["optional_filled"],
            "traps_left": c["traps_left"],
            "prefilled": c["prefilled"],
            "uploads": c["uploads"],
            "validation_errors": c["validation_errors"],
            "by_source": dict(by_source),
            "rungs": dict(rungs),
            "typed_by": dict(typing),
            "needs_review": c["needs_review"],
            "reviewed": c["reviewed"],
            "selection_limited": c["selection_limited"],
            "external_steps": dict(Counter(e.kind for e in self.external_steps)),
        }

    def review_items(self) -> list[str]:
        """Labels worth pointing out at the submit gate (sensitive or derived)."""
        out: list[str] = []
        for s in self.steps:
            for o in s.outcomes:
                if o.action in ("filled", "human") and (o.review or o.sensitive):
                    label = o.label.strip() or o.field_type
                    if label not in out:
                        out.append(label)
        return out


@dataclass
class _StepOutcome:
    status: str
    step: FormStep
    outcomes: tuple[QuestionOutcome, ...]
    unanswered: tuple[str, ...] = ()
    reason: str = ""


def describe_step(step: FormStep, cap: int = 1800) -> str:
    """One log line for what was read on a page: each question's words,
    kind, requiredness and options, and the buttons. Never a value: the
    page's own words only (live diagnosis, 2026-11-26)."""
    def short(text: str, n: int = 70) -> str:
        text = " ".join((text or "").split())
        return text if len(text) <= n else text[:n - 1] + "…"

    qs = []
    for q in step.questions:
        mark = "*" if q.is_required else ("?" if q.required == UNKNOWN else "")
        opts = f" [{'|'.join(short(o.label, 20) for o in q.options[:6])}]" if q.options else ""
        qs.append(f"{short(q.label)!r}{mark}:{getattr(q.kind, 'value', q.kind)}{opts}")
    buttons = ",".join(f"{short(b.text, 30)!r}:{b.role}" for b in step.buttons[:8])
    host = step.url.split("?", 1)[0].split("#", 1)[0]
    line = (f"{host} purpose={step.purpose} step={step.step_now}/{step.step_total} "
            f"questions={len(step.questions)} {'; '.join(qs)} | buttons {buttons}")
    return line if len(line) <= cap else line[:cap - 1] + "…"


class _PersonSkipped(Exception):
    """The person chose to skip the application while reviewing an answer."""


def _chosen_count(answer: Answer) -> int:
    """How many options an answer ticks."""
    if answer.many:
        return len(answer.many)
    return 1 if (answer.text or answer.choices or answer.checked) else 0


def _mark_reviewed(outcomes: Sequence[QuestionOutcome]) -> tuple[QuestionOutcome, ...]:
    return tuple(replace(o, reviewed=True) if o.needs_review and not o.reviewed else o
                 for o in outcomes)


@dataclass
class FormRunContext:
    """Per-application inputs from the workflow."""

    answers: AnswerContext
    gate: Callable[..., Any] | None = None
    assist_allowed: bool = False
    on_step: Callable[[StepRecord], None] | None = None
    #: Asked before clicking a control that may submit but is the only way
    #: on ("Submit and continue"). Answers ``"click"``, ``"skip"`` (the
    #: person declined) or ``"blocked"``. None: never clicked.
    confirm_risky: Callable[[str], str] | None = None


class GeneratedAnswerSource:
    """Drafts open-ended answers with the local text model. Off by default.

    Only for open-ended free-text questions that are not protected
    (:func:`is_protected` — whatever the reader classified), only when ``applications.generated_answers`` is on, and every
    draft is flagged for the pre-submit review: a model asked to write can add
    claims the person never made (CAP-1), so a person reads it before it is
    sent. The prompt gives the model only the person's own summary and
    experience.
    """

    name = "generated"

    def __init__(self, generator: TextGenerationPort, profile: Any, *,
                 max_tokens: int = 150) -> None:
        self._gen = generator
        self._profile = profile
        self._max_tokens = max_tokens

    def propose(self, q: FormQuestion, ctx: AnswerContext) -> Answer | None:
        if q.kind != QuestionKind.TEXTAREA or is_protected(q):
            return None
        summary = str(getattr(self._profile, "career_summary", "") or "")
        jobs = getattr(self._profile, "work_experience", None) or []
        lines = [f"- {getattr(j, 'title', '')} at {getattr(j, 'company', '')}: "
                 f"{(getattr(j, 'description', '') or '')[:300]}" for j in jobs[:3]]
        prompt = (
            "Write a short first-person answer to a job-application question, using ONLY "
            "the facts below. Do not add skills, employers, dates, numbers or credentials "
            "that are not stated. Two to four sentences.\n\n"
            f"Role applied for: {ctx.job_title} at {ctx.company}\n"
            f"Summary: {summary}\nExperience:\n" + "\n".join(lines) +
            f"\n\nQuestion: {question_text(q)}\nAnswer:"
        )
        try:
            text = self._gen.generate(prompt, max_tokens=self._max_tokens)
        except Exception:
            return None
        text = (text or "").strip()
        if not text:
            return None
        return Answer(text=text, source="generated", confidence=0.76, review=True)


class FormStepEngine:
    """Fills an application form step by step; never submits."""

    def __init__(
        self,
        page: FormPagePort,
        tool: FormTool,
        sources: Sequence[AnswerSourcePort],
        settings: FormEngineSettings | None = None,
        *,
        memory: SessionAnswerMemory | None = None,
        wait_ready: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._page = page
        self._tool = tool
        self._settings = settings or FormEngineSettings()
        self._memory = memory if memory is not None else SessionAnswerMemory()
        sources = list(sources)
        if self._settings.remember_answers and not any(
            getattr(s, "name", "") == SessionAnswerMemory.name for s in sources
        ):
            sources.insert(0, self._memory)
        self._sources: list[AnswerSourcePort] = sources
        self._wait_ready = wait_ready
        self._clock = clock
        self._actuator = ControlActuator(page, tool, self._settings.actuator, wait_ready)
        self._last_described = ""

    @property
    def memory(self) -> SessionAnswerMemory:
        return self._memory

    @property
    def settings(self) -> FormEngineSettings:
        return self._settings

    @property
    def actuator(self) -> ControlActuator:
        return self._actuator

    # ------------------------------------------------------------------
    def run(self, ctx: FormRunContext) -> FormRunResult:
        externals: list[ExternalStep] = []
        result = self._run(ctx, externals)
        return replace(result, external_steps=tuple(externals))

    def _run(self, ctx: FormRunContext, externals: list[ExternalStep]) -> FormRunResult:
        records: list[StepRecord] = []
        seen: Counter[str] = Counter()
        step = self._read()
        if step is None:
            return FormRunResult(NO_FORM, "the page could not be read")
        for index in range(max(1, self._settings.max_steps)):
            started = self._clock()
            self._collect_external(step, externals)
            signals = is_test_step(step)
            if signals:
                # A test, not an application step: AA never takes it for the
                # person (docs/adr/026). Hand it over, or stop here.
                after = self._test_wall(step, ctx, signals)
                if after == USER_SKIPPED:
                    return FormRunResult(USER_SKIPPED, "the person chose to skip this "
                                         "application at a test", final_step=step,
                                         steps=tuple(records))
                if not isinstance(after, FormStep):
                    return FormRunResult(ASSESSMENT, "this page is a test ("
                                         + ", ".join(signals) + "); AA does not take tests "
                                         "for the person", final_step=step,
                                         steps=tuple(records))
                step = after
                seen[self._visible_fingerprint(step)] += 1
                if seen[self._visible_fingerprint(step)] > 2:
                    return FormRunResult(LOOP, "the form kept returning to the test",
                                         final_step=step, steps=tuple(records))
                continue
            review_page = step.purpose == "review" and bool(records)
            if not step.has_form and step.purpose != "login" and not review_page:
                return FormRunResult(NO_FORM, "no application form on this page",
                                     final_step=step, steps=tuple(records))
            if step.form_in_frame:
                return FormRunResult(NO_FORM, "the application form is inside a frame",
                                     final_step=step, steps=tuple(records))
            if step.purpose == "login" or self._has_visible_password(step):
                step2 = self._account_wall(step, ctx)
                if step2 is None:
                    return FormRunResult(ACCOUNT_REQUIRED, "this application needs an account "
                                         "on the site (sign-in or account creation)",
                                         final_step=step, steps=tuple(records))
                step = step2
                continue
            visible_fp = self._visible_fingerprint(step)
            seen[visible_fp] += 1
            if seen[visible_fp] > 2:
                return FormRunResult(LOOP, "the form kept returning to the same step",
                                     final_step=step, steps=tuple(records))

            outcome = (_StepOutcome("ok", step, ()) if review_page
                       else self._work_step(index, step, ctx))
            step = outcome.step
            record = StepRecord(index, step, outcome.outcomes,
                                seconds=round(self._clock() - started, 3))
            if outcome.status == USER_SKIPPED:
                records.append(record)
                self._emit(ctx, record)
                return FormRunResult(USER_SKIPPED, outcome.reason, final_step=step,
                                     steps=tuple(records))
            if outcome.unanswered:
                records.append(record)
                self._emit(ctx, record)
                return FormRunResult(BLOCKED, outcome.reason, final_step=step,
                                     steps=tuple(records), unanswered=outcome.unanswered)

            if self._settings.review_each_step and ctx.gate is not None:
                choice = self._ask(ctx, self._review_text(index, step, outcome.outcomes, ctx),
                                   ["continue", "skip"], "AFTER_STEP_FILLED")
                if choice != "continue":
                    records.append(record)
                    self._emit(ctx, record)
                    return FormRunResult(USER_SKIPPED, "the person stopped after reviewing a "
                                         "step", final_step=step, steps=tuple(records))
                # The page review showed every answer, including those that
                # needed the person's OK: they have now seen them.
                outcome.outcomes = _mark_reviewed(outcome.outcomes)
                record = replace(record, outcomes=outcome.outcomes)

            states = self._button_states(step)
            nxt, risky = self._forward_button(step, states)
            submit = self._submit_button(step, states)
            if nxt is not None and not risky and nxt.button_type in ("submit", "image") \
                    and not self._more_steps_evident(step, nxt, submit):
                # "Continue" as a form's submit button with nothing to show more
                # steps follow: it may be the form's last button. Not a guess.
                risky = True
            if nxt is not None and risky and submit is not None:
                nxt = None  # a clear submit control: the gate decides, not a guess
            if nxt is None:
                records.append(record)
                self._emit(ctx, record)
                if submit is None:
                    return FormRunResult(NO_ADVANCE, "no Next or Submit control on this step",
                                         final_step=step, steps=tuple(records))
                return FormRunResult(READY_TO_SUBMIT, "", submit_button=submit,
                                     final_step=step, steps=tuple(records))
            if risky:
                verdict = ctx.confirm_risky(nxt.text) if ctx.confirm_risky else "blocked"
                if verdict != "click":
                    records.append(record)
                    self._emit(ctx, record)
                    if verdict == "skip":
                        return FormRunResult(USER_SKIPPED, "the person chose not to click "
                                             f"\u201c{nxt.text[:40]}\u201d", final_step=step,
                                             steps=tuple(records))
                    return FormRunResult(NO_ADVANCE, f"the only control to go on "
                                         f"(\u201c{nxt.text[:40]}\u201d) may send the "
                                         "application, and no one confirmed it",
                                         final_step=step, steps=tuple(records))

            advanced, new_step, errors, click = self._advance(step, nxt, ctx, confirmed=risky)
            if new_step is not None:
                self._collect_external(new_step, externals)
            record = StepRecord(index, step, outcome.outcomes,
                                advanced_by=nxt.text[:60] if click != NOT_CLICKED else "",
                                errors=errors, seconds=round(self._clock() - started, 3),
                                confirmed_click=risky, click=click)
            records.append(record)
            self._emit(ctx, record)
            if click == NOT_CLICKED:
                # Nothing AA did moved the page: whatever happened next is not
                # the result of a click, and is never recorded as one.
                return FormRunResult(NO_ADVANCE, f"AA could not click \u201c{nxt.text[:40]}"
                                     "\u201d", final_step=new_step or step,
                                     steps=tuple(records))
            if new_step is None:
                return FormRunResult(NO_FORM, "the page could not be read after advancing",
                                     steps=tuple(records))
            if advanced is None:
                return FormRunResult(USER_SKIPPED, "the person chose to skip this application",
                                     final_step=new_step, steps=tuple(records))
            if not advanced and click == CLICK_UNCERTAIN:
                return FormRunResult(BLOCKED, "the click on \u201c" + nxt.text[:40] + "\u201d "
                                     "may or may not have happened and the page did not "
                                     "move; AA does not click it again", final_step=new_step,
                                     steps=tuple(records), unanswered=errors)
            if not advanced:
                labels = tuple(e for e in errors) or ("the page did not move on",)
                return FormRunResult(BLOCKED, "the step did not advance; the page reported "
                                     "problems AA could not resolve", final_step=new_step,
                                     steps=tuple(records), unanswered=labels)
            step = new_step
        return FormRunResult(MAX_STEPS, f"more than {self._settings.max_steps} steps",
                             final_step=step, steps=tuple(records))

    # ------------------------------------------------------------------
    def _emit(self, ctx: FormRunContext, record: StepRecord) -> None:
        if ctx.on_step is None:
            return
        try:
            ctx.on_step(record)
        except Exception as exc:
            logger.debug("form engine: step observer failed: %s", type(exc).__name__)

    def _read(self) -> FormStep | None:
        """Read the step and apply AA's language knowledge to it (any page,
        any perception behind the port: ``form_localization.localize_step``)."""
        try:
            step = self._page.read_step()
        except Exception as exc:  # the port never raises; contain anyway
            logger.debug("form engine: read failed: %s", type(exc).__name__)
            return None
        if step is None:
            return None
        try:
            step = localize_step(step)
        except Exception as exc:
            logger.warning("form engine: language step failed (%s); using the raw reading",
                           type(exc).__name__)
        if step.fingerprint != self._last_described:
            self._last_described = step.fingerprint
            logger.info("form engine: read %s", describe_step(step))
        return step

    def _settle(self, seconds: float) -> None:
        if self._wait_ready is not None:
            try:
                self._wait_ready(seconds)
                return
            except Exception:
                pass
        self._tool.settle()

    def _await_quiet(self, step: FormStep, budget_s: float) -> bool:
        """Poll the step's controls until their values stop changing.

        The settling rule (K equal readings in a row, within ``T_max``) is the
        reading library's, behind ``FormPagePort.quiet_detector``; the time
        between polls is the tool's settle. A minimum window
        (``upload_quiet_min_s``) covers a parser that starts late. Bounded
        here regardless of the detector: by wall clock, and by a read cap.
        Returns True when quiet, False when the budget ran out.
        """
        min_s = self._settings.upload_quiet_min_s
        limit = max(budget_s, min_s)
        detector = self._page.quiet_detector(2, max(0.1, budget_s))
        start = self._clock()
        refs = step.all_refs()
        for _ in range(_QUIET_MAX_READS):
            states = self._page.read_states(refs)
            signature = tuple((s.value, s.checked, s.files) for s in states)
            now = self._clock() - start
            verdict = detector(signature, now)
            if verdict == "settled" and now >= min_s:
                return True
            if verdict == "timeout" or now >= limit:
                return False
            self._tool.settle()
        return False

    def _states(self, step: FormStep) -> dict[str, ControlState]:
        refs = step.all_refs()
        states = self._page.read_states(refs)
        out: dict[str, ControlState] = {}
        i = 0
        for q in step.questions:
            mine = states[i:i + len(q.controls)]
            i += len(q.controls)
            out[q.key] = _merge_states(q, mine)
        return out

    def _visible_fingerprint(self, step: FormStep) -> str:
        states = self._states(step)
        keys = sorted(q.key for q in step.questions if states.get(q.key, _ABSENT).visible)
        return step.url.split("#", 1)[0] + "|" + "|".join(keys) + "|" + step.step_label

    def _has_visible_password(self, step: FormStep) -> bool:
        pw = [q for q in step.questions if q.kind == QuestionKind.PASSWORD]
        if not pw:
            return False
        states = self._states(step)
        return any(states.get(q.key, _ABSENT).visible for q in pw)

    def _think(self, q: FormQuestion) -> None:
        per = self._settings.reading_pause_ms_per_char
        cap = self._settings.reading_pause_max_s
        if per <= 0 or cap <= 0:
            return
        hi = min(cap, len(q.label) * per / 1000.0)
        if hi <= 0.05:
            return
        try:
            self._tool.macro_pause(hi * 0.5, hi)
        except Exception:
            pass

    def _resolve(self, q: FormQuestion, ctx: FormRunContext,
                 locales: tuple[str, ...] = ()) -> Answer | None:
        """The best answer the sources propose. A protected question (only
        the person may answer it) takes an answer only from the person's own
        declaration — their profile's legal and self-identification
        sections, their pronouns, or an answer they gave in this session —
        whatever any other source proposes: the rule holds here, centrally,
        not only inside each source."""
        best: Answer | None = None
        protected = is_protected(q)
        answers_ctx = replace(ctx.answers, form_locales=tuple(locales)) if locales else ctx.answers
        for src in self._sources:
            try:
                a = src.propose(q, answers_ctx)
            except Exception as exc:
                logger.debug("form engine: source %s raised %s",
                             getattr(src, "name", "?"), type(exc).__name__)
                continue
            if a is None:
                continue
            if protected and not a.source.startswith(_DECLARED_SOURCES):
                logger.debug("form engine: %s may not answer a protected question",
                             getattr(src, "name", "?"))
                continue
            if a.file_path or a.confidence >= self._settings.fill.min_confidence:
                return a
            if a.source.endswith("_missing"):
                return a
            if best is None or a.confidence > best.confidence:
                best = a
        return best

    # ------------------------------------------------------------------
    def _work_step(self, index: int, step: FormStep, ctx: FormRunContext) -> _StepOutcome:
        outcomes: dict[str, QuestionOutcome] = {}
        to_ask: dict[str, FormQuestion] = {}
        off_step: set[str] = set()

        def record(q: FormQuestion, action: str, reason: str, *, source: str = "",
                   rung: str = "", review: bool = False, needs: bool = False,
                   reviewed: bool = False) -> None:
            outcomes[q.key] = QuestionOutcome(q.key, q.label, q.kind, q.field_type, q.required,
                                              is_protected(q), action, reason, source, rung,
                                              review, typed_by(q), needs, reviewed)

        def handle(q: FormQuestion, state: ControlState) -> FillOutcome | None:
            answer = self._resolve(q, ctx, step.locales)
            if answer is not None and not self._within_limit(q, answer):
                # "Pick the best 2" with three remembered choices: never tick
                # more (or fewer) than the question allows; the person decides.
                reason = (f"selection-limit:{_chosen_count(answer)} chosen, "
                          f"{q.choose_min or 0}-{q.choose_max or 'any'} allowed")
                if q.is_required:
                    record(q, "asked", reason)
                    to_ask[q.key] = q
                else:
                    record(q, "left", reason)
                return None
            d = decide(q, state, answer, self._settings.fill)
            if d.action == FILL_ACTION and d.answer is not None:
                self._think(q)
                result = self._actuator.fill(q, d.answer)
                if result.ok:
                    needs = needs_review(d.answer, self._settings.answer_trust,
                                         self._settings.review_below_confidence)
                    record(q, "filled", d.reason, source=d.answer.source, rung=result.rung,
                           review=d.answer.review, needs=needs)
                    if needs and self._settings.review_timing == "each" and self._can_ask(ctx):
                        if not self._review_now([q], step, ctx):
                            raise _PersonSkipped
                        outcomes[q.key] = replace(outcomes[q.key], reviewed=True)
                else:
                    record(q, "failed", result.reason, source=d.answer.source, rung=result.rung)
                    if q.is_required:
                        to_ask[q.key] = q
                return result
            if d.action == ASK:
                record(q, "asked", d.reason)
                to_ask[q.key] = q
                return None
            if d.reason in _OFF_STEP:
                off_step.add(q.key)
            elif q.key not in outcomes:
                record(q, "left", d.reason)
            return None

        # Uploads first: the ATS may parse the résumé and pre-fill the form.
        states = self._states(step)
        uploaded = False
        for q in step.questions:
            if q.kind == QuestionKind.FILE:
                res = handle(q, states.get(q.key, _ABSENT))
                uploaded = uploaded or bool(res and res.ok)
        if uploaded:
            # Many trackers parse the résumé and fill the form a moment later.
            # Wait until the controls stop changing (bounded), then read again,
            # so AA never types into a field the parser is still writing.
            self._settle(self._settings.upload_settle_s)
            self._await_quiet(step, self._settings.upload_settle_s)
            fresh = self._read()
            if fresh is not None and fresh.has_form:
                step = fresh

        done: set[str] = set(outcomes)
        census = self._page.control_census()
        actions = 0

        def work_questions() -> None:
            """Handle every question not handled yet, in page order; after a
            choice that changed which controls are shown, read the step again
            and go on with what is new."""
            nonlocal step, census, actions
            restart = True
            while restart:
                restart = False
                states = self._states(step)
                for q in step.questions:
                    if q.key in done:
                        continue
                    st = states.get(q.key, _ABSENT)
                    if actions >= self._settings.max_questions_per_step:
                        # Never treat an unexamined question as handled: the
                        # sweep below makes a shown, required one unresolved.
                        if st.visible and q.key not in outcomes:
                            record(q, "left", "over-question-limit")
                        continue
                    off_step.discard(q.key)
                    res = handle(q, st)
                    if q.key in off_step:
                        continue  # not shown now; a later reveal may bring it back
                    done.add(q.key)
                    actions += 1
                    if res is not None and res.ok and q.kind in QuestionKind.REVEALING:
                        now = self._page.control_census()
                        if now != census:
                            census = now
                            fresh = self._read()
                            if fresh is not None and fresh.has_form:
                                step = fresh
                                restart = True
                                break

        def sweep() -> None:
            """Every question the reader marked required (and FILL) that is
            shown, enabled and still empty is unresolved — whatever left it so:
            revealed while the person answered, swapped in by a choice, beyond
            the per-step limit. Next is never clicked over one."""
            states = self._states(step)
            for q in step.questions:
                if not q.is_required or q.decision != FILL or q.key in to_ask:
                    continue
                st = states.get(q.key, _ABSENT)
                if st.read_failed:
                    # Visibility unknown is not "not shown": never handled.
                    record(q, "asked", "state-unreadable")
                    to_ask[q.key] = q
                    continue
                if not st.present or st.disabled or st.filled:
                    continue
                if not st.visible and q.kind != QuestionKind.FILE:
                    continue
                if outcomes.get(q.key) is None or outcomes[q.key].action not in ("asked", "failed"):
                    record(q, "asked", "required-still-empty")
                to_ask[q.key] = q

        # Work, check, and ask in place for what AA could not answer; the
        # person's answers can reveal more questions, handled the next round.
        assists = 0
        for _round in range(self._settings.max_assists_per_step + 2):
            try:
                work_questions()
            except _PersonSkipped:
                return _StepOutcome(USER_SKIPPED, step, tuple(outcomes.values()),
                                    reason="the person chose to skip this application")
            sweep()
            missing = self._still_missing(step, to_ask)
            if not missing:
                break
            if not ctx.assist_allowed or ctx.gate is None or \
                    assists >= self._settings.max_assists_per_step:
                break
            assists += 1
            if self._settings.answer_in_aa:
                verdict = self._answer_in_aa(missing, step, ctx, record)
                if verdict == USER_SKIPPED:
                    for q in self._still_missing(step, to_ask):
                        record(q, "asked", "person-skipped")
                    return _StepOutcome(USER_SKIPPED, step, tuple(outcomes.values()),
                                        reason="the person chose to skip this application")
                for key in verdict:
                    to_ask.pop(key, None)
                    done.add(key)
                missing = self._still_missing(step, to_ask)
                if not missing:
                    continue  # all answered in AA: the next round re-checks the step
            focused = (self._settings.focus_asked_field
                       and self._focus(missing[0]))
            choice = self._ask(ctx, self._assist_text(missing, ctx, step, focused),
                               ["done", "skip"], "FORM_NEEDS_ANSWERS")
            if choice != "done":
                for q in missing:
                    record(q, "asked", "person-skipped")
                return _StepOutcome(USER_SKIPPED, step, tuple(outcomes.values()),
                                    reason="the person chose to skip this application")
            fresh = self._read()
            if fresh is not None and fresh.has_form:
                step = fresh
            states = self._states(step)
            for key, q in list(to_ask.items()):
                q_now = step.question(key) or q
                st = states.get(key, _ABSENT)
                if st.filled:
                    record(q_now, "human", "answered-in-place", source="human", review=True)
                    self._remember(q_now, st, ctx.answers.company)
                    to_ask.pop(key)
                    done.add(key)

        sweep()
        unanswered = self._still_missing(step, to_ask) if to_ask else []
        labels = tuple((q.label or q.field_type)[:120] for q in unanswered)
        reason = ""
        if labels:
            reason = ("required question(s) without an answer: " + "; ".join(labels[:5]))
        elif (self._settings.review_timing == "page" and not self._settings.review_each_step
              and self._can_ask(ctx)):
            # The page's answers that need the person, all at once, before
            # AA moves on (the page review, when on, already shows them).
            pending = [q for q in step.questions
                       if (o := outcomes.get(q.key)) is not None and o.action == "filled"
                       and o.needs_review and not o.reviewed]
            if pending:
                if not self._review_now(pending, step, ctx):
                    return _StepOutcome(USER_SKIPPED, step, tuple(outcomes.values()),
                                        reason="the person chose to skip this application")
                for q in pending:
                    outcomes[q.key] = replace(outcomes[q.key], reviewed=True)
        return _StepOutcome("ok", step, tuple(outcomes.values()), labels, reason)

    @staticmethod
    def _can_ask(ctx: FormRunContext) -> bool:
        return ctx.assist_allowed and ctx.gate is not None

    @staticmethod
    def _within_limit(q: FormQuestion, answer: Answer) -> bool:
        """Does the answer respect the question's selection bound?"""
        if not (q.choose_min or q.choose_max) or answer.file_path:
            return True
        n = _chosen_count(answer)
        if q.choose_min and n < q.choose_min:
            return False
        return not (q.choose_max and n > q.choose_max)

    def _review_now(self, questions: Sequence[FormQuestion], step: FormStep,
                    ctx: FormRunContext) -> bool:
        """Show the person answers AA filled that need their OK; True when
        they are done checking (and may have changed them in the form)."""
        focused = self._settings.focus_asked_field and self._focus(questions[0])
        lines = "\n".join(f"  - {(q.label or q.field_type)[:100]}" for q in questions[:8])
        more = ("\n" + get_text("form_engine.more", count=len(questions) - 8)
                if len(questions) > 8 else "")
        parts = [get_text("form_engine.review_answers", count=len(questions),
                          where=self._where(step), application=self._application(ctx)),
                 lines + more]
        if focused:
            parts.append(get_text("form_engine.focus_note"))
        parts.append(get_text("form_engine.review_answers_instructions"))
        return self._ask(ctx, "\n".join(parts), ["done", "skip"], "ANSWER_REVIEW") == "done"

    def _collect_external(self, step: FormStep, externals: list[ExternalStep]) -> None:
        try:
            found = external_steps(step)
        except Exception as exc:  # recognition never breaks a run
            logger.debug("form engine: external-step recognition failed: %s",
                         type(exc).__name__)
            return
        known = {(e.kind, e.host, e.text) for e in externals}
        for e in found:
            if (e.kind, e.host, e.text) not in known:
                externals.append(e)
                known.add((e.kind, e.host, e.text))

    def _test_wall(self, step: FormStep, ctx: FormRunContext,
                   signals: Sequence[str]) -> FormStep | str | None:
        """Hand a test page to the person: AA never takes tests for them.
        Returns the page after they are back, ``USER_SKIPPED``, or None
        (no one to hand it to, or still a test)."""
        if not self._can_ask(ctx):
            return None
        choice = self._ask(ctx, get_text("form_engine.test_page",
                                         application=self._application(ctx)),
                           ["done", "skip"], "ASSESSMENT")
        if choice != "done":
            return USER_SKIPPED
        self._settle(self._settings.advance_settle_s)
        fresh = self._read()
        if fresh is None or is_test_step(fresh):
            return None
        return fresh

    def _still_missing(self, step: FormStep, to_ask: Mapping[str, FormQuestion]) -> list[FormQuestion]:
        states = self._states(step)
        out = []
        for key, q in to_ask.items():
            q_now = step.question(key) or q
            st = states.get(key, _ABSENT)
            if st.read_failed:
                out.append(q_now)  # cannot be verified: still missing
                continue
            if not st.present or (not st.visible and q_now.kind != QuestionKind.FILE):
                continue  # gone from this step (withdrawn, or the page moved on)
            if not st.filled:
                out.append(q_now)
        return out

    def _remember(self, q: FormQuestion, state: ControlState, company: str) -> None:
        if not self._settings.remember_answers or q.kind == QuestionKind.FILE:
            return
        if q.kind == QuestionKind.CHECKBOX:
            self._memory.remember(q, "", checked=bool(state.checked), company=company)
            return
        if q.kind in (QuestionKind.RADIO, QuestionKind.CHECKBOX_GROUP):
            chosen = self._checked_labels(q)
            if chosen:
                self._memory.remember(q, chosen[0], many=tuple(chosen), company=company)
            return
        self._memory.remember(q, state.value.strip(), company=company)

    def _checked_labels(self, q: FormQuestion) -> list[str]:
        refs = [o.control for o in q.options if o.control is not None]
        states = self._page.read_states(refs)
        labels = [o.label for o in q.options if o.control is not None]
        return [labels[i] for i, s in enumerate(states) if s.checked]

    # ------------------------------------------------------------------
    def _ask(self, ctx: FormRunContext, text: str, options: list[str], checkpoint: str,
             *, private: bool = False) -> str:
        return ask_gate(ctx.gate, text, options, checkpoint=checkpoint,
                        timeout=self._settings.assist_timeout_s, private=private)

    # -- the person's words: plain, located, in their language (i18n) ----
    @staticmethod
    def _where(step: FormStep) -> str:
        if step.step_now and step.step_total:
            return get_text("form_engine.where_step", now=step.step_now, total=step.step_total)
        return get_text("form_engine.where_page")

    @staticmethod
    def _application(ctx: FormRunContext) -> str:
        return get_text("form_engine.application",
                        company=ctx.answers.company or ctx.answers.host or "?")

    @staticmethod
    def _language_note(step: FormStep) -> str:
        """Say so when the form is in another language than AA speaks to the
        person in: the questions are shown as the form words them, never
        translated (AA does not answer what it has not read as written)."""
        page = primary_tag(step.language)
        if not page or page == primary_tag(current_language()):
            return ""
        return get_text("form_engine.language_note", language=language_name(page))

    def _assist_text(self, missing: Sequence[FormQuestion], ctx: FormRunContext,
                     step: FormStep | None = None, focused: bool = False) -> str:
        where = self._where(step) if step is not None else get_text("form_engine.where_page")
        required = get_text("form_engine.required_suffix")
        lines = "\n".join(
            f"  - {(q.label or q.field_type)[:100]}{required if q.is_required else ''}"
            for q in missing[:8]
        )
        more = ("\n" + get_text("form_engine.more", count=len(missing) - 8)
                if len(missing) > 8 else "")
        parts = [get_text("form_engine.assist_intro", count=len(missing), where=where,
                          application=self._application(ctx)), lines + more]
        note = self._language_note(step) if step is not None else ""
        if note:
            parts.append(note)
        if focused:
            parts.append(get_text("form_engine.focus_note"))
        parts.append(get_text("form_engine.assist_instructions"))
        return "\n".join(parts)

    def _review_text(self, index: int, step: FormStep, outcomes: Sequence[QuestionOutcome],
                     ctx: FormRunContext) -> str:
        filled = sum(1 for o in outcomes if o.action in ("filled", "human"))
        left = sum(1 for o in outcomes if o.action in ("left", "failed"))
        label = f" ({step.step_label})" if step.step_label else ""
        text = get_text("form_engine.review_step", index=index + 1, label=label,
                        application=self._application(ctx), filled=filled, left=left)
        check = [(o.label or o.field_type)[:60] for o in outcomes
                 if o.action == "filled" and o.needs_review and not o.reviewed]
        if check:
            text += "\n" + get_text("form_engine.review_step_check", items="; ".join(check[:8]))
        return text

    def _focus(self, q: FormQuestion) -> bool:
        """Bring the question into view and give it the keyboard focus."""
        return self._actuator.focus_question(q)

    def _answer_in_aa(self, missing: Sequence[FormQuestion], step: FormStep,
                      ctx: FormRunContext,
                      record: Callable[..., None]) -> tuple[str, ...] | str:
        """Ask each missing question in AA's own window and enter the answer.

        An accommodation (``accessibility.answer_in_aa``): a person who
        cannot easily operate a site's widgets — a screen-reader user facing
        an unlabelled custom dropdown, a switch user facing a date picker —
        answers in AA's interface, which they can use, and AA operates the
        widget and checks that the answer took (the actuator's read-back).
        A choice question offers the form's own options, exactly as worded;
        a free-text question takes a typed answer when the gate can take one.
        The answer is the person's, so it is asked ``private``: never logged,
        never stored as approval evidence. Uploads, passwords, long option
        lists and anything AA could not enter go to the browser prompt.

        Returns the keys answered here, or ``USER_SKIPPED``.
        """
        answered: list[str] = []
        todo = list(missing)[: max(0, self._settings.max_questions_in_aa)]
        where = self._where(step)
        application = self._application(ctx)
        note = self._language_note(step)
        for n, q in enumerate(todo, start=1):
            heading = get_text("form_engine.aa_heading", index=n, count=len(todo), where=where,
                               application=application,
                               required=get_text("form_engine.required_suffix")
                               if q.is_required else "")
            body = [heading, (q.label or q.field_type)[:300]]
            if q.description:
                body.append(q.description[:300])
            if is_protected(q):
                body.append(get_text("form_engine.aa_protected"))
            if note:
                body.append(note)
            answer: Answer | None = None
            if q.kind in (QuestionKind.SELECT, QuestionKind.RADIO) and q.options:
                labels = [o.label for o in q.options if o.label.strip()
                          and not is_placeholder(o.label)]
                if not labels or len(labels) > _MAX_AA_OPTIONS or \
                        {IN_BROWSER, SKIP} & set(labels) or len(set(labels)) != len(labels):
                    continue
                body.append(get_text("form_engine.aa_choice"))
                choice = self._ask(ctx, "\n".join(body), labels + [IN_BROWSER, SKIP],
                                   "FORM_NEEDS_ANSWERS", private=True)
                if choice == SKIP:
                    return USER_SKIPPED
                if choice == IN_BROWSER:
                    continue
                answer = Answer(text=choice, choices=(choice,), source="human",
                                confidence=1.0, sensitive=is_protected(q), review=True)
            elif q.kind == QuestionKind.CHECKBOX and len(q.controls) == 1:
                body.append(get_text("form_engine.aa_checkbox"))
                choice = self._ask(ctx, "\n".join(body), [TICK, LEAVE_UNTICKED, IN_BROWSER, SKIP],
                                   "FORM_NEEDS_ANSWERS", private=True)
                if choice == SKIP:
                    return USER_SKIPPED
                if choice not in (TICK, LEAVE_UNTICKED):
                    continue
                answer = Answer(checked=choice == TICK, source="human", confidence=1.0,
                                sensitive=is_protected(q), review=True)
            elif q.kind in (QuestionKind.TEXT, QuestionKind.TEXTAREA) and can_ask_text(ctx.gate):
                body.append(get_text("form_engine.aa_text"))
                typed = ask_text(ctx.gate, "\n".join(body), checkpoint="FORM_NEEDS_ANSWERS",
                                 timeout=self._settings.assist_timeout_s, private=True)
                if typed is None:
                    continue
                answer = Answer(text=typed, source="human", confidence=1.0,
                                sensitive=is_protected(q), review=True)
            if answer is None:
                continue
            result = self._actuator.fill(q, answer)
            if result.ok:
                record(q, "human", "answered-in-aa", source="human", rung=result.rung,
                       review=True)
                state = self._states(step).get(q.key, _ABSENT)
                self._remember(q, state, ctx.answers.company)
                answered.append(q.key)
            else:
                # Not entered as asked: the person answers it in the browser.
                record(q, "asked", f"answered-in-aa-not-entered:{result.reason}",
                       source="human", rung=result.rung)
        return tuple(answered)

    def _account_wall(self, step: FormStep, ctx: FormRunContext) -> FormStep | None:
        """Ask the person to sign in or create the account themselves."""
        if not ctx.assist_allowed or ctx.gate is None:
            return None
        choice = self._ask(
            ctx,
            get_text("form_engine.account_wall", host=ctx.answers.host or "?"),
            ["signed in", "skip"], "ACCOUNT_REQUIRED",
        )
        if choice != "signed in":
            return None
        self._settle(self._settings.advance_settle_s)
        fresh = self._read()
        if fresh is None or fresh.purpose == "login" or self._has_visible_password(fresh):
            return None
        return fresh

    # ------------------------------------------------------------------
    def _button_states(self, step: FormStep) -> dict[int, ControlState]:
        states = self._page.read_states([b.control for b in step.buttons])
        return {i: s for i, s in enumerate(states)}

    def _forward_button(self, step: FormStep,
                        states: Mapping[int, ControlState]) -> tuple[FormButton | None, bool]:
        """The control that moves this step on, and whether it may submit.

        A control moves the step on when its role is ``next``/``review`` (the
        reader's, or AA's words in the page's language) or its text has such
        a word ("Review and submit", "Submit and continue"). A plain one is
        preferred; one that may submit (:attr:`FormButton.may_submit`) is
        returned with ``risky=True`` — clicked only after confirmation. A
        control that says it does something else ("Upload", "Hochladen",
        "添付") is not a way on unless its role is ``next``.
        """
        safe: FormButton | None = None
        risky: FormButton | None = None
        locales = step.locales or ("en",)
        for i, b in enumerate(step.buttons):
            st = states.get(i, _ABSENT)
            if not st.visible or st.disabled or b.role == "back":
                continue
            nav = best_class(b.text, ("next", "review", "back"), locales)
            moves_on = b.role in ("next", "review") or (nav is not None and nav[0] != "back")
            if not moves_on:
                continue
            if says(b.text, "not_submit") and b.role != "next":
                continue
            if b.may_submit:
                risky = b
            else:
                safe = b
        if safe is not None:
            return safe, False
        return risky, risky is not None

    @staticmethod
    def _more_steps_evident(step: FormStep, nxt: FormButton, submit: FormButton | None) -> bool:
        """Positive evidence that a submit-type Next moves to another step:
        the step's position shows more steps follow (``aria-current=step`` or
        a visible "Step N of M" in any language, N < M), or a separate control
        on the same step says, in words, that it submits. A question of the
        form not shown yet is NOT evidence: a conditional question can be
        hidden on the last page as well as on any other."""
        if step.step_now and step.step_total and step.step_now < step.step_total:
            return True
        return submit is not None and submit.control != nxt.control and says_submit(submit.text)

    def _submit_button(self, step: FormStep, states: Mapping[int, ControlState]) -> FormButton | None:
        best: FormButton | None = None
        best_score = 0.0
        locales = step.locales or ("en",)
        for i, b in enumerate(step.buttons):
            st = states.get(i, _ABSENT)
            if not st.visible or st.disabled or b.role in ("next", "back", "review"):
                continue
            if says(b.text, "not_submit") or says(b.text, "back"):
                continue
            nav = best_class(b.text, ("next", "review"), locales)
            if nav is not None:
                continue  # says it moves on ("Review"): handled as a forward control
            score = 0.0
            if says_submit(b.text):
                score = 2.0
            elif b.role == "submit" or b.button_type in ("submit", "image"):
                score = 1.0
            elif b.final and b.text.strip():
                # Unclassified, and may submit (CT-INV-004): offered at the
                # submit gate as a last resort, with its text shown there.
                score = 0.5
            if score and score >= best_score:
                best, best_score = b, score
        return best

    def _advance(self, step: FormStep, button: FormButton, ctx: FormRunContext, *,
                 confirmed: bool = False
                 ) -> tuple[bool | None, FormStep | None, tuple[str, ...], str]:
        """Click Next; progress only when the page proves it.

        Returns ``(advanced, page_after, problems, click)``. ``advanced`` is
        None when the person chose to skip the application. ``click`` says
        what AA knows about its own click: ``clicked``; ``not-clicked`` (the
        control was refused, not found, or the tool reported it did not
        click — a page change then is not AA's doing and is never counted as
        progress); ``uncertain`` (the tool failed mid-click: it may have
        happened, so AA never clicks it again). ``problems`` lists every
        validation problem the page reported on the way, including ones the
        person then fixed — for the research record, the step's friction.
        """
        before_fp = self._visible_fingerprint(step)
        before_url = step.url.split("#", 1)[0]
        seen: list[str] = []
        for attempt in range(2):
            ok, _detail = self._actuator.click_button(button, confirmed=confirmed)
            if ok is False:
                return False, self._read(), tuple(seen), NOT_CLICKED
            click = CLICKED if ok else CLICK_UNCERTAIN
            self._settle(self._settings.advance_settle_s)
            new = self._read()
            if new is None:
                return False, None, tuple(seen), click
            if new.url.split("#", 1)[0] != before_url or not new.has_form:
                return True, new, tuple(seen), click
            if self._visible_fingerprint(new) != before_fp:
                return True, new, tuple(seen), click
            errors = self._errors(new)
            seen.extend(e for e in errors if e not in seen)
            if click == CLICK_UNCERTAIN:
                return False, new, tuple(seen) or ("the page did not move on",), click
            if attempt == 1 or not errors or not ctx.assist_allowed or ctx.gate is None:
                return False, new, tuple(seen) if seen else ("the page did not move on",), click
            choice = self._ask(
                ctx,
                get_text("form_engine.not_accepted",
                         problems="\n".join(f"  - {e}" for e in errors[:8])),
                ["done", "skip"], "FORM_NEEDS_ANSWERS",
            )
            if choice != "done":
                return None, new, tuple(seen), click
            step = new
            button = self._same_button(new, button) or button
        return False, step, tuple(seen), CLICKED

    def _errors(self, step: FormStep) -> list[str]:
        states = self._states(step)
        out = []
        for q in step.questions:
            st = states.get(q.key, _ABSENT)
            if not st.present or not st.visible:
                continue
            if st.invalid or (q.is_required and not st.filled):
                msg = f" ({st.message[:80]})" if st.message else ""
                out.append(f"{(q.label or q.field_type)[:100]}{msg}")
        return out

    @staticmethod
    def _same_button(step: FormStep, button: FormButton) -> FormButton | None:
        for b in step.buttons:
            if b.role == button.role and b.text == button.text:
                return b
        return None


_ABSENT = ControlState(present=False)
#: Reasons that mean "this question is not part of the step being filled":
#: no outcome is recorded for them on this step (they belong to another).
_OFF_STEP = frozenset({"not-on-this-step", "not-found", "reader-decision:hidden"})


def _merge_states(q: FormQuestion, states: Sequence[ControlState]) -> ControlState:
    """One state per question: a group is present/visible if any member is,
    and filled when any member is checked."""
    if not states:
        return _ABSENT
    if len(states) == 1 and q.kind not in (QuestionKind.RADIO, QuestionKind.CHECKBOX_GROUP):
        return states[0]
    present = any(s.present for s in states)
    visible = any(s.visible for s in states)
    checked = any(bool(s.checked) for s in states)
    return ControlState(
        present=present, visible=visible, value="", checked=checked,
        disabled=all(s.disabled for s in states if s.present) if present else False,
        invalid=any(s.invalid for s in states),
        value_missing=any(bool(s.value_missing) for s in states),
        message=next((s.message for s in states if s.message), ""),
    )
