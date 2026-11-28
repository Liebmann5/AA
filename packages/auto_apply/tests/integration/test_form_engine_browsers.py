"""The application step engine against real Chromium, through both adapters.

Three forms built from three very different application patterns (owner
ruling: design from three very different examples):

* ``plain_single_page.html`` — a one-page form in the plain-HTML style
  (labels with ``for``, a native select, a visually hidden file input, a
  radio fieldset, a CSS-hidden trap field, an optional opt-in box and a
  required certify box);
* ``custom_widgets.html`` — the React style (comboboxes whose listbox is
  portalled to ``<body>``, controlled inputs that revert values set without
  input events, a résumé "parser" that fills the name a moment after upload);
* ``shadow_wizard.html`` — a four-step wizard inside an open shadow root
  (visually replaced radios, a conditional question, a masked phone input,
  a field the page validates with its own script and message, and a last
  step with nothing to answer before Submit);
* ``two_page_review.html`` — a server-style flow whose second page is a
  review page with no question at all, only the button that sends it;
* ``adapter_edges.html`` — reader/actuator edges the code reviews found: a
  combobox beside its label, radios drawn by labels over hidden inputs, a
  choice that swaps questions without changing their number, and two custom
  widgets side by side in one container;
* ``combobox_popup.html`` — an ARIA 1.2 combobox whose popup is a dialog
  holding the option list, open, in the same box as the shown selection;
* ``german_wizard.html`` — a two-step form declared German (docs/adr/025).

These pins guard the code; they are not proof of behaviour on live sites —
live runs are. Skipped when a browser stack is missing.
"""

from __future__ import annotations

import functools
import http.server
import os
import socketserver
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("pagecomp")

from auto_apply.adapters.secondary.perception.pagecomp_form import (
    PagecompFormPage,  # noqa: E402
)
from auto_apply.application.services.form_engine import (  # noqa: E402
    READY_TO_SUBMIT,
    FormEngineSettings,
    FormRunContext,
    FormRunResult,
    FormStepEngine,
)
from auto_apply.application.services.page_action.service import (
    PageActionService,  # noqa: E402
)
from auto_apply.domain.applications.answers import (  # noqa: E402
    AnswerContext,
    ProfileAnswerSource,
    TemplateAnswerSource,
)
from auto_apply.domain.applications.external_steps import external_steps  # noqa: E402
from auto_apply.domain.applications.form_localization import localize_step  # noqa: E402
from auto_apply.domain.models.profile import UserProfile  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "form_engine"


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    srv = _Server(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(FIX)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class _NoMatch:
    """A TextSimilarityPort stand-in: the step engine never asks it."""

    def find_best_match(self, text: str, candidates: Any) -> tuple[str, float]:
        return "", 0.0

    def similarity(self, a: str, b: str) -> float:
        return 0.0


def _registry() -> MagicMock:
    """Real tool, no long waits (the tool's pacing is pinned elsewhere)."""
    r = MagicMock()
    r.get_all_effective_config.return_value = {
        "enable_human_timing": False, "occlusion_guard": True, "navigation_retries": 1,
        "macro_pause_min_s": 0.0, "macro_pause_max_s": 0.0, "settle_min_s": 0.02,
        "settle_max_s": 0.05, "min_action_delay_ms": 0, "low_resource_mode": False,
        "infinite_scroll_settle_s": 0.1,
    }
    return r


class Stack:
    """A browser adapter plus a way to act as the person in the window."""

    def __init__(self, adapter: Any, js: Callable[[str], Any], close: Callable[[], None]) -> None:
        self.adapter, self.js, self.close = adapter, js, close


def _playwright() -> Stack:
    pw = pytest.importorskip("playwright.sync_api")
    from auto_apply.adapters.secondary.browser.playwright_adapter import (
        PlaywrightAdapter,
    )

    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(executable_path=os.environ.get("PAGECOMP_CHROMIUM") or None)
    except Exception as exc:  # no browser in this environment
        pytest.skip(f"chromium unavailable: {exc}")
    page = browser.new_page()

    def close() -> None:
        browser.close()
        p.stop()

    return Stack(PlaywrightAdapter(page, browser, p),
                 lambda body: page.evaluate("() => {" + body + "}"), close)


def _selenium() -> Stack:
    webdriver = pytest.importorskip("selenium.webdriver")
    from auto_apply.adapters.secondary.browser.selenium_adapter import SeleniumAdapter

    opts = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage"):
        opts.add_argument(arg)
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as exc:
        pytest.skip(f"Cannot create Chrome driver: {exc}")
    return Stack(SeleniumAdapter(driver), driver.execute_script, driver.quit)


@pytest.fixture(scope="module", params=["playwright", "selenium"])
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    s = _playwright() if request.param == "playwright" else _selenium()
    yield s
    s.close()


@pytest.fixture(scope="module")
def profile(tmp_path_factory: pytest.TempPathFactory) -> UserProfile:
    resume = tmp_path_factory.mktemp("docs") / "ada_quill_resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% test resume\n")
    return UserProfile(**{
        "profile_name": "Test Person",
        "personal_info": {
            "first_name": "Ada", "last_name": "Quill", "email": "ada.quill@example.org",
            "phone_number": "5551234567", "street_address": "1 Main St", "city": "Chicago",
            "state": "IL", "zip_code": "60601", "country": "United States",
            "resume_path": str(resume),
        },
        "links": {"linkedin": "https://www.linkedin.com/in/ada-quill",
                  "portfolio": "https://ada-quill.example.org"},
        "career_summary": "Analyst with five years of logistics data experience.",
        "search_preferences": {"desired_job_titles": ["Data Analyst"]},
        "legal_info": {"has_work_authorization": True, "requires_sponsorship": False},
        "eeo_info": {"gender": "Female"},
    })


def _engine(stack: Stack, profile: UserProfile) -> tuple[FormStepEngine, PageActionService]:
    tool = PageActionService(browser=stack.adapter, registry=_registry())
    engine = FormStepEngine(
        PagecompFormPage(stack.adapter, access={"level": "dom"}),
        tool,
        [ProfileAnswerSource(profile), TemplateAnswerSource(profile)],
        FormEngineSettings(reading_pause_ms_per_char=0),
        wait_ready=lambda seconds: tool.settle(),
    )
    return engine, tool


def _set_text(selector: str, value: str, root: str = "document") -> str:
    """JS the person's typing amounts to: a value plus the input event."""
    return (
        f"const e = {root}.querySelector({selector!r});"
        f"if (e && !e.value) {{ e.focus(); e.value = {value!r};"
        " e.dispatchEvent(new Event('input', {bubbles: true})); e.blur(); }"
    )


#: Pre-write review prompts the last run approved (never asserted on values).
REVIEWED: list[str] = []


def _run(stack: Stack, profile: UserProfile, url: str,
         person: Callable[[str, str], str]) -> tuple[FormRunResult, list[str]]:
    stack.adapter.get(url)
    engine, _tool = _engine(stack, profile)
    asked: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str = "", **kw: Any) -> str:
        if checkpoint == "ANSWER_REVIEW" and "approve" in options:
            # Phase 0 (P0-5): answers that need the person are shown before
            # they are written; these tests approve them and are about the
            # rest of the run.
            REVIEWED.append(question)
            return "approve"
        asked.append(checkpoint)
        return person(checkpoint, question)

    result = engine.run(FormRunContext(
        answers=AnswerContext("Data Analyst", "Northwind", "127.0.0.1"),
        gate=gate, assist_allowed=True,
    ))
    return result, asked


# ─────────────────────────────────────────────────────────────────────────────


def test_a_plain_one_page_form(stack: Stack, profile: UserProfile, base_url: str) -> None:
    def person(checkpoint: str, question: str) -> str:
        assert checkpoint == "FORM_NEEDS_ANSWERS"
        assert "How did you hear about this job?" in question
        stack.js(_set_text("#heard", "LinkedIn"))
        return "done"

    result, asked = _run(stack, profile, f"{base_url}/plain_single_page.html", person)

    assert result.status == READY_TO_SUBMIT, result.reason
    assert result.submit_button is not None and result.submit_button.text == "Submit application"
    assert asked == ["FORM_NEEDS_ANSWERS"]
    values = stack.js(
        "const f = document.forms.application; return {"
        " first: f.first_name.value, email: f.email.value, country: f.country.value,"
        " resume: f.resume.files.length,"
        " auth: (f.querySelector('input[name=authorized]:checked') || {}).value || '',"
        " trap: f.website_url.value, alerts: f.alerts.checked, certify: f.certify.checked,"
        " extra: f.additional_info.value,"
        " offpage: f.homepage ? f.homepage.value : 'missing' };"
    )
    assert values == {
        "first": "Ada", "email": "ada.quill@example.org", "country": "US", "resume": 1,
        "auth": "yes", "trap": "", "alerts": False, "certify": True, "extra": "",
        "offpage": "",
    }, "both traps (CSS-hidden, and inserted off the page after upload) stay empty"
    c = result.counters()
    assert c["uploads"] == 1 and c["human"] == 1 and c["failed"] == 0


def test_react_style_widgets_and_a_resume_parse(stack: Stack, profile: UserProfile,
                                               base_url: str) -> None:
    def person(checkpoint: str, question: str) -> str:
        assert checkpoint == "FORM_NEEDS_ANSWERS"
        stack.js(_set_text("#why", "Because I like robots."))
        return "done"

    result, _asked = _run(stack, profile, f"{base_url}/custom_widgets.html", person)

    assert result.status == READY_TO_SUBMIT, result.reason
    shown = stack.js(
        "const v = k => document.querySelector('input[name=question_' + k + ']').value;"
        " return { auth: v('auth'), sponsor: v('sponsor'), location: v('location'),"
        " gender: v('gender'), hispanic: v('hispanic'), veteran: v('veteran'),"
        " first: document.getElementById('first_name').value,"
        " email: document.getElementById('email').value };"
    )
    assert shown == {
        "auth": "Yes", "sponsor": "No", "location": "Chicago, IL, USA",
        "gender": "Female", "hispanic": "", "veteran": "",
        "first": "Ada", "email": "ada.quill@example.org",
    }, "undeclared demographics stay blank; declared ones are chosen"
    c = result.counters()
    assert c["prefilled"] >= 2, "the names the parser filled were kept, not retyped"
    assert c["rungs"].get("combobox", 0) >= 4


def test_a_shadow_root_wizard_with_the_pages_own_validation(stack: Stack, profile: UserProfile,
                                                          base_url: str) -> None:
    shadow = "document.querySelector('apply-wizard').shadowRoot"
    prompts: list[str] = []

    def person(checkpoint: str, question: str) -> str:
        prompts.append(question)
        if "did not accept" in question:
            assert "Years of logistics experience" in question
            assert "whole number" in question, "the page's own message is shown"
            stack.js(_set_text("#yrs", "5", root=shadow))
        else:
            stack.js(f"{shadow}.querySelector('label[for=w_no]').click();")
        return "done"

    result, _asked = _run(stack, profile, f"{base_url}/shadow_wizard.html", person)

    assert result.status == READY_TO_SUBMIT, result.reason
    assert [s.step.step_label for s in result.steps] == [
        "Step 1 of 4", "Step 2 of 4", "Step 3 of 4", "Step 4 of 4"]
    assert result.submit_button is not None and result.submit_button.text == "Submit"
    assert result.steps[1].errors and "Years of logistics experience" in result.steps[1].errors[0]
    values = stack.js(
        f"const r = {shadow}; return {{ phone: r.getElementById('ph').value,"
        " visa: (r.querySelector('input[name=visa]:checked') || {}).value || '',"
        " terms: r.getElementById('terms').checked };"
    )
    assert values == {"phone": "(555) 123-4567", "visa": "no", "terms": True}


def test_a_review_page_with_nothing_to_answer(stack: Stack, profile: UserProfile,
                                              base_url: str) -> None:
    result, asked = _run(stack, profile, f"{base_url}/two_page_review.html",
                         lambda checkpoint, question: "skip")

    assert result.status == READY_TO_SUBMIT, result.reason
    assert [s.step.purpose for s in result.steps] == ["application", "review"]
    assert result.submit_button is not None
    assert result.submit_button.text == "Submit application"
    assert asked == []
    assert stack.js("return location.pathname") == "/review", "nothing was sent"


def test_the_reader_and_actuator_edges_from_the_reviews(stack: Stack, profile: UserProfile,
                                                        base_url: str) -> None:
    """Combobox label never read as a value; label-drawn radios clicked on
    their label; a swap of questions noticed although the count is equal."""
    from auto_apply.application.services.form_actuator import ControlActuator
    from auto_apply.domain.applications.answers import Answer

    stack.adapter.get(f"{base_url}/adapter_edges.html")
    engine, tool = _engine(stack, profile)
    page = PagecompFormPage(stack.adapter, access={"level": "dom"})
    step = page.read_step()
    assert step is not None and step.has_form
    country = next(q for q in step.questions if q.label.startswith("Country"))
    contact = next(q for q in step.questions if q.label.startswith("Preferred contact"))

    state = page.read_states([country.primary])[0]
    assert state.value == "" and not state.filled, "the label is not the selection"

    radio_state = page.read_states([contact.options[0].control])[0]  # type: ignore[list-item]
    assert radio_state.visible and radio_state.own_visible is False

    before = page.control_census()
    outcome = ControlActuator(page, tool).fill(
        contact, Answer(text="Phone", choices=("phone",), source="profile:x", confidence=0.95))
    assert outcome.ok, outcome.reason
    assert stack.js("return document.getElementById('c_phone').checked") is True
    assert stack.js("return [document.getElementById('email_box').style.display,"
                    " document.getElementById('phone_box').style.display].join()") \
        == "none,block"
    assert page.control_census() != before, "same number of controls, different ones"


def test_round_three_adapter_edges(stack: Stack, profile: UserProfile, base_url: str) -> None:
    """Round-3 review: two custom widgets side by side are separate fields
    (the checkbox's text is not the combobox's value); the census changes
    when a control's name changes under the same element; focus lands on the
    control without the page script scrolling."""
    stack.adapter.get(f"{base_url}/adapter_edges.html")
    _engine_, tool = _engine(stack, profile)
    page = PagecompFormPage(stack.adapter, access={"level": "dom"})
    step = page.read_step()
    assert step is not None and step.language == "en"
    seniority = next(q for q in step.questions if q.label.startswith("Seniority"))
    state = page.read_states([seniority.primary])[0]
    assert state.value == "" and not state.filled, "the neighbour's text is not a value"

    before = page.control_census()
    stack.js("document.querySelector('label[for=contact_email]').textContent = 'Work email';")
    assert page.control_census() != before, "same element, different question"

    from auto_apply.application.services.form_actuator import ControlActuator

    assert ControlActuator(page, tool).focus_question(seniority)
    assert stack.js("return document.activeElement && document.activeElement.id") == "seniority"


def test_a_comboboxs_own_popup_is_neither_a_boundary_nor_its_value(
        stack: Stack, base_url: str) -> None:
    """The selection a combobox shows beside its open popup is its value;
    the popup (a dialog holding the list, named by ``aria-controls``) is
    the widget's own — not another field, and its text is not the value."""
    stack.adapter.get(f"{base_url}/combobox_popup.html")
    page = PagecompFormPage(stack.adapter, access={"level": "dom"})
    step = page.read_step()
    assert step is not None
    city = next(q for q in step.questions if q.label.startswith("City"))
    state = page.read_states([city.primary])[0]
    assert state.value == "Berlin", state.value
    assert state.filled


def test_a_german_two_step_form(stack: Stack, profile: UserProfile, base_url: str) -> None:
    """docs/adr/025: a form AA has never seen in English — declared German,
    no autocomplete tokens, a submit-type "Fortfahren" the reader does not
    know, ISO country codes behind German names, and a gender question only
    the person answers."""
    prompts: list[str] = []

    def person(checkpoint: str, question: str) -> str:
        prompts.append(question)
        assert checkpoint == "FORM_NEEDS_ANSWERS"
        assert "Geschlecht" in question
        stack.js("const s = document.getElementById('gs'); s.value = 'Weiblich';"
                 " s.dispatchEvent(new Event('change', {bubbles: true}));")
        return "done"

    result, asked = _run(stack, profile, f"{base_url}/german_wizard.html", person)

    assert result.status == READY_TO_SUBMIT, result.reason
    assert asked == ["FORM_NEEDS_ANSWERS"], "Fortfahren was clicked without a confirmation"
    assert [(s.step.step_now, s.step.step_total) for s in result.steps] == [(1, 2), (2, 2)]
    first = result.steps[0].step
    assert first.language == "de" and "de" in first.locales
    assert result.submit_button is not None
    assert result.submit_button.text == "Bewerbung absenden"
    values = stack.js(
        "const v = id => document.getElementById(id).value;"
        " return {vn: v('vn'), nn: v('nn'), em: v('em'), land: v('land'), gs: v('gs')};")
    assert values == {"vn": "Ada", "nn": "Quill", "em": "ada.quill@example.org",
                      "land": "US", "gs": "Weiblich"}
    assert "Deutsch" in prompts[0], "the person is told the form is in German"
    assert result.counters()["typed_by"].get("lexicon(de)", 0) >= 3
    assert not stack.js("return !!window.__sent"), "nothing was sent"


# ─────────────────────────────────────────────────────────────────────────────
# The whole attempt: the workflow, the engine and the submit gate
# ─────────────────────────────────────────────────────────────────────────────


def test_the_workflow_submits_only_through_the_gate(stack: Stack, profile: UserProfile,
                                                     base_url: str) -> None:
    from auto_apply.adapters.secondary.interaction.human_like_adapter import (
        InteractionExecutor,
    )
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.job import Job
    from auto_apply.domain.models.session_plan import SessionPlan
    from auto_apply.domain.ports.interrupt_policy_port import (
        ProfileBasedInterruptPolicy,
    )

    engine, tool = _engine(stack, profile)
    workflow = ApplicationsWorkflow(
        profile=profile, browser=stack.adapter, perception_port=None,
        interaction_port=InteractionExecutor(stack.adapter, page_action=tool),
        webpage_analyzer=None, field_classifier=None, semantic_filler=None,
        text_matcher=_NoMatch(), file_handler=None, interruption_handler=None,
        dom_observer=None, ats_registry=None, job_repo=MagicMock(), task_queue=MagicMock(),
        event_bus=MagicMock(), interrupt_policy=ProfileBasedInterruptPolicy(None),
        navigation=tool, text_generation_port=None, browser_lease=None,
        plan=SessionPlan(session_id="engine-live"), form_engine=engine,
    )
    observer = MagicMock()
    workflow._research_observer = observer
    asked: list[tuple[str, str]] = []

    reviewed: list[str] = []

    def gate(question: str, options: list[str], *, checkpoint: str = "", **kw: Any) -> str:
        if checkpoint == "ANSWER_REVIEW":
            # P0-5: shown with their values, privately, before anything is typed.
            assert kw.get("private") is True
            reviewed.append(question)
            return "approve"
        asked.append((checkpoint, question))
        if checkpoint == "FORM_NEEDS_ANSWERS":
            stack.js(_set_text("#why", "Because I like robots."))
            return "done"
        assert checkpoint == "BEFORE_FORM_SUBMIT"
        return "submit"

    workflow.set_approval_gate(gate)
    job = Job(title="Platform Engineer", company="Acme Robotics",
              url=f"{base_url}/custom_widgets.html", source="test_fixture")
    evidence = workflow.run(job, session_id="engine-live")

    assert [c for c, _ in asked] == ["FORM_NEEDS_ANSWERS", "BEFORE_FORM_SUBMIT"]
    summary = asked[-1][1]
    assert summary.startswith("Submit application?")
    assert "Please check these answers" in summary and "Ada" not in summary
    assert evidence.outcome == "SUBMITTED", evidence.error_message
    assert evidence.submit_clicked is True
    assert evidence.form_engine == "steps" and evidence.form_steps == 1
    assert evidence.human_assisted_fields == 1 and evidence.file_upload_succeeded
    assert evidence.prefilled_kept >= 2
    assert stack.js("return (window.__submitted || {}).auth || ''") == "Yes"
    assert observer.observe_form.call_count == 1
    assert observer.observe_form.call_args.args[0].page_index == 0


def test_the_workflow_never_submits_when_the_person_says_skip(stack: Stack, profile: UserProfile,
                                                              base_url: str) -> None:
    from auto_apply.adapters.secondary.interaction.human_like_adapter import (
        InteractionExecutor,
    )
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )
    from auto_apply.domain.models.job import Job
    from auto_apply.domain.models.session_plan import SessionPlan
    from auto_apply.domain.ports.interrupt_policy_port import (
        ProfileBasedInterruptPolicy,
    )

    engine, tool = _engine(stack, profile)
    workflow = ApplicationsWorkflow(
        profile=profile, browser=stack.adapter, perception_port=None,
        interaction_port=InteractionExecutor(stack.adapter, page_action=tool),
        webpage_analyzer=None, field_classifier=None, semantic_filler=None,
        text_matcher=_NoMatch(), file_handler=None, interruption_handler=None,
        dom_observer=None, ats_registry=None, job_repo=MagicMock(), task_queue=MagicMock(),
        event_bus=MagicMock(), interrupt_policy=ProfileBasedInterruptPolicy(None),
        navigation=tool, text_generation_port=None, browser_lease=None,
        plan=SessionPlan(session_id="engine-live"), form_engine=engine,
    )

    def gate(question: str, options: list[str], *, checkpoint: str = "", **kw: Any) -> str:
        if checkpoint == "FORM_NEEDS_ANSWERS":
            stack.js(_set_text("#heard", "LinkedIn"))
            return "done"
        return "skip"

    workflow.set_approval_gate(gate)
    job = Job(title="Data Analyst", company="Northwind",
              url=f"{base_url}/plain_single_page.html", source="test_fixture")
    evidence = workflow.run(job, session_id="engine-live")

    assert evidence.outcome == "USER_SKIPPED"
    assert evidence.submit_clicked is False
    assert stack.js("return location.pathname") == "/plain_single_page.html"


# ── assessments, external steps, choice limits (docs/adr/026) ──────────────


def test_a_required_coding_test_link_and_a_choice_limit_are_read(
        stack: Stack, profile: UserProfile, base_url: str) -> None:
    stack.adapter.get(f"{base_url}/assessment_and_limits.html")
    raw = PagecompFormPage(stack.adapter, access={"level": "dom"}).read_step()
    assert raw is not None
    step = localize_step(raw)  # the engine's reading: words, limits
    hosts = {link.text: link.href for link in step.links}
    assert "Start the coding test" in hosts and "privacy notice" in hosts
    found = external_steps(step)
    assert [(e.kind, e.host, e.required) for e in found] == [
        ("assessment", "contoso.hackerrank.com", True)], "the privacy link is not a condition"
    group = next(q for q in step.questions if "Pick the best 2" in q.label)
    assert (group.choose_min, group.choose_max) == (2, 2)

    result, _asked = _run(stack, profile, f"{base_url}/assessment_and_limits.html",
                          lambda checkpoint, question: "skip")
    assert result.required_external_steps()
    assert stack.js("return location.hostname") == "127.0.0.1", "the link was never followed"
    assert stack.js("return document.querySelectorAll('input[name=areas]:checked').length") <= 2


def test_a_timed_test_page_is_never_answered(stack: Stack, profile: UserProfile,
                                            base_url: str) -> None:
    stack.adapter.get(f"{base_url}/timed_test.html")
    engine, _tool = _engine(stack, profile)
    result = engine.run(FormRunContext(answers=AnswerContext("Data Analyst", "Contoso",
                                                             "127.0.0.1")))
    assert result.status == "ASSESSMENT", result.reason
    assert "role=timer" in result.reason and "code-editor" in result.reason
    assert stack.js("return document.getElementById('answer_name').value") == "", \
        "nothing on a test page is filled"


# ── label shapes from a live ATS form (2026-11-26) ─────────────────────────


def test_icon_fallback_text_and_wrapped_radios(stack: Stack, profile: UserProfile,
                                               base_url: str) -> None:
    """An icon's hidden SVG fallback text is never a question's name, an
    empty upload-icon label gives way to aria-labelledby ("Resume"), and a
    role="radio" box around a native radio is one option, not a question."""
    asked_about: list[str] = []

    def person(checkpoint: str, question: str) -> str:
        asked_about.append(question)
        stack.js("document.getElementById('w_yes').click();")
        return "done"

    result, asked = _run(stack, profile, f"{base_url}/icon_labels_and_wrapped_radios.html",
                         person)

    assert result.status == READY_TO_SUBMIT, result.reason
    assert asked == ["FORM_NEEDS_ANSWERS"]
    text = asked_about[0]
    assert "SVGs not supported" not in text
    assert "3 years of Python experience?" in text
    assert "Python experience? YES" not in text and "Python experience? NO" not in text
    state = stack.js(
        "const f = document.forms.application;"
        " const pick = n => (f.querySelector('input[name=' + n + ']:checked') || {}).value || '';"
        " return { address: f.address.value, resume: f.querySelector('#resume_file').files.length,"
        " python: pick('q1'), sponsor: pick('q2'),"
        " sponsor_box: document.getElementById('w_sp_no').getAttribute('aria-checked') };"
    )
    assert state == {"address": state["address"] or "?", "resume": 1, "python": "yes",
                     "sponsor": "no", "sponsor_box": "true"}, state
    assert state["address"], "the address field was recognised and filled"
