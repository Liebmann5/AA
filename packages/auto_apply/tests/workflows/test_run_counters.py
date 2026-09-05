"""Pins for run counters surviving every outcome (Stage 7e).

The live run walked all three pages of the wizard — two `Next →` clicks, both
returning `ok`, three distinct button snapshots proving the DOM changed twice —
and reported `pages_navigated=0`.

The counter was never the problem. `self._pages_navigated` increments
unconditionally on the line after a successful click, and a browser-free guard
already proved that. What lost it was the *evidence*: the counters were stamped
only on the path that reaches a submit attempt, so every early return recorded
zeros. The submission gate I added in Stage 1 is one of those early returns.

Which makes this worse than a test artefact: **gate-blocked is the default
outcome for an install with no approver wired**, so the research dataset lost
these counters on exactly the runs a cautious user produces.
"""
import pathlib

import pytest
from unittest.mock import MagicMock

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.ports.interrupt_policy_port import ProfileBasedInterruptPolicy

WORKFLOW_SRC = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "application"
    / "workflows"
    / "applications_workflow.py"
)

_JOB = Job(
    title="Senior Software Engineer",
    company="Acme Corp",
    url="https://acme.example.com/apply",
    source="test_fixture",
)


class _WizardBrowser:
    """A fake browser that behaves like the three-page mock under clicking.

    Each click advances a step, and `find_elements` reports button texts the way
    Selenium does: the current page's controls have text, hidden ones return "".
    That is what makes the engine's walk reproducible without a browser.
    """

    def __init__(self, pages: int = 3):
        self.pages = pages
        self.step = 1
        self.page_source = "<html><body>form</body></html>"
        self.current_url = _JOB.url
        self.title = "Apply"

    def get(self, url):
        return None

    def find_elements(self, by, selector):
        buttons = []
        for step in range(1, self.pages + 1):
            visible = step == self.step
            if step < self.pages:
                buttons.append(self._button("Next \u2192" if visible else "", self))
            if step > 1:
                buttons.append(self._button("\u2190 Back" if visible else "", self))
        buttons.append(
            self._button(
                "Submit Application" if self.step == self.pages else "", self
            )
        )
        return buttons

    def find_element(self, by, selector):
        return None

    def execute_script(self, script, *args):
        return None

    class _button:
        def __init__(self, text, owner):
            self.text = text
            self._owner = owner

        def click(self):
            if self.text.startswith("Next"):
                self._owner.step = min(self._owner.step + 1, self._owner.pages)

        def get_attribute(self, name):
            return ""

        def get_size(self):
            return (60, 21) if self.text else (0, 0)


class _Matcher:
    def find_best_match(self, query, candidates):
        import difflib

        text = (query or "").strip().lower()
        best, best_score = "", 0.0
        for candidate in candidates:
            target = candidate.strip().lower()
            score = 1.0 if target and target in text else difflib.SequenceMatcher(
                None, text, target
            ).ratio()
            if score > best_score:
                best, best_score = candidate, score
        return best, best_score


def _workflow(browser):
    from auto_apply.application.workflows.applications_workflow import (
        ApplicationsWorkflow,
    )

    interaction = MagicMock()
    interaction.click.side_effect = lambda element: element.click()

    return ApplicationsWorkflow(
        profile=MagicMock(),
        browser=browser,
        perception_port=None,
        interaction_port=interaction,
        webpage_analyzer=None,
        field_classifier=None,
        semantic_filler=None,
        text_matcher=_Matcher(),
        file_handler=None,
        interruption_handler=None,
        dom_observer=None,
        ats_registry=None,
        job_repo=MagicMock(),
        task_queue=MagicMock(),
        event_bus=MagicMock(),
        interrupt_policy=ProfileBasedInterruptPolicy(None),
        text_generation_port=None,
        browser_lease=None,
        plan=SessionPlan(session_id="test"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE INCREMENT REACHES THE EVIDENCE
# ─────────────────────────────────────────────────────────────────────────────


def test_a_three_page_walk_is_counted_in_the_evidence():
    """The pin Nick asked for: the increment, pinned against the click.

    Reproduces the live scenario without a browser — two Next clicks, the gate
    blocking submission at the end — and asserts the count survives the early
    return.
    """
    browser = _WizardBrowser(pages=3)
    workflow = _workflow(browser)

    evidence = workflow.run(_JOB, session_id="test")

    assert browser.step == 3, "the fake wizard did not advance; the pin is vacuous"
    assert workflow._pages_navigated == 2
    assert evidence.pages_navigated == 2, (
        "the counter incremented but the evidence lost it — the exact bug the "
        "live run surfaced"
    )


def test_the_gate_blocked_outcome_still_carries_the_counters():
    """Gate-blocked is the DEFAULT for an install with no approver wired."""
    workflow = _workflow(_WizardBrowser(pages=3))

    evidence = workflow.run(_JOB, session_id="test")

    assert evidence.outcome == "SUBMISSION_GATE_BLOCKED"
    assert evidence.pages_navigated == 2
    assert evidence.submit_clicked is False


def test_a_single_page_form_counts_zero_advances():
    """Zero is the right answer when nothing advanced — not the only answer."""
    browser = _WizardBrowser(pages=1)
    workflow = _workflow(browser)

    evidence = workflow.run(_JOB, session_id="test")

    assert evidence.pages_navigated == 0
    assert browser.step == 1


# ─────────────────────────────────────────────────────────────────────────────
# EVERY EARLY RETURN, NOT JUST THE GATE
# ─────────────────────────────────────────────────────────────────────────────


def test_the_statistics_helper_reports_the_live_counters():
    workflow = _workflow(_WizardBrowser())
    workflow._pages_navigated = 4
    workflow._fields_classified = 12
    workflow._required_fields_filled = 7
    workflow._gpt4all_invoked = True

    stats = workflow._run_statistics()

    assert stats == {
        "pages_navigated": 4,
        "fields_classified": 12,
        "required_fields_filled": 7,
        "used_gpt4all": True,
    }


def test_every_evidence_update_carries_the_counters():
    """Structural invariant: no outcome may report zeros for work that happened.

    Every `model_copy(update={...})` on the evidence must carry the counters
    either by splat (`**self._run_statistics()`) or inline (the submit-success
    path, which has always stamped them directly). Counting return statements
    was the wrong model — the CAPTCHA path assigns and returns separately.
    """
    source = WORKFLOW_SRC.read_text(encoding="utf-8", errors="ignore")

    chunks = source.split("model_copy(update={")[1:]
    assert chunks, "no evidence updates found at all"

    missing = []
    for chunk in chunks:
        body = chunk.split("})")[0]
        # Only terminal outcomes matter: a mid-flow enrichment (ats_platform,
        # submit_button_found) is followed by an update that does stamp them.
        if '"outcome":' not in body:
            continue
        if (
            "**self._run_statistics()," not in body
            and '"pages_navigated": self._pages_navigated,' not in body
        ):
            missing.append(body.strip().splitlines()[0].strip())

    assert not missing, (
        f"evidence updates that would report zeros for real work: {missing}"
    )


def test_the_submit_path_still_stamps_its_counters():
    """Regression guard on the one path that always had them."""
    source = WORKFLOW_SRC.read_text(encoding="utf-8", errors="ignore")

    assert '"pages_navigated": self._pages_navigated,' in source