"""Structured evidence from an application submission attempt.

Research-grade application tracking needs more than True/False.
The difference between SUBMITTED and CAPTCHA_BLOCKED matters scientifically,
practically, and for user trust. These evidence records are:
  - Logged at INFO level so users can verify outcomes
  - Stored in the database alongside job records
  - Used by the session report to show what really happened
  - Fed to the research pipeline as high-quality outcome signals
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# Confirmation phrases moved to domain/services/page_phrases.py — locale-keyed
# data matched on visible text by the ONE page verdict. The per-ATS split is
# preserved there for translators; matching unions every ATS and locale. The
# weak phrases this table carried are curated out there, with reasons.


class ApplicationEvidence(BaseModel):
    """Structured evidence from a single application attempt.

    Produced by ApplicationsWorkflow._submit_application() and returned
    up through ApplicationsWorkflow.run().  Stored in the database.  Used
    by the session report and research pipeline.

    Truthiness: ``bool(evidence)`` delegates to :attr:`is_likely_success`,
    so existing orchestrator code that checks ``if result:`` continues to
    work without changes.
    """
    # R-7: unknown fields are REJECTED at construction instead of silently
    # dropped. This is the first extra="forbid" in the codebase — deliberate,
    # because this model is the research dataset's write path: a misspelled
    # field name here corrupts data with no signal (the job_url= incident).
    # EffectiveConfig keeps extra="ignore" on purpose — the merged config
    # legitimately carries keys beyond the schema. Do not "consistency-fix"
    # that one.
    #
    # Known blind spot (RV-1, recorded): model_copy(update={...}) bypasses
    # Pydantic validation entirely, so the ~15 model_copy(update=) sites in
    # applications_workflow.py are NOT covered by this guard, and mypy cannot
    # check those dict keys either. This layer guards direct construction —
    # literal kwargs, dict-splat, model_validate — which today is two sites
    # (orchestrator._buffer_application, applications_workflow.run) and
    # tomorrow is any deserialization the research pipeline adds.
    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── Pre-submit state ─────────────────────────────────────────────────
    attempt_id: str = ""   # joins this outcome to its per-page research rows
    pre_submit_url: str = ""
    page_title_before: str = ""
    ats_platform: str | None = None  # matched ATS name, of the LANDED page

    # ── Apply-route evidence (item 12B) ──────────────────────────────────
    # How AA got from the posting to the form — the hiring-friction record:
    # how many hops, through whom, before a job seeker reaches the
    # employer's application.
    posting_host: str = ""        # host of job.url (in live runs, a job board)
    apply_target_host: str = ""   # host of the learned/followed apply target
    landed_host: str = ""         # host of the page AA ended on
    apply_route_hops: int = 0     # navigations after the initial load

    # ── Form interaction evidence ────────────────────────────────────────
    fields_classified: int = 0
    required_fields_filled: int = 0
    optional_fields_filled: int = 0
    custom_fields_answered: int = 0
    pages_navigated: int = 0
    file_upload_attempted: bool = False
    file_upload_succeeded: bool = False
    used_gpt4all: bool = False

    # ── Step engine evidence (application step engine) ───────────────────
    # Counts only: no answer value and no field label is ever stored here.
    #: Which form filler ran: "steps" (the step engine), "" (the pre-2026-11
    #: page loop, still selectable as applications.form_engine: legacy).
    form_engine: str = ""
    #: Form steps the engine worked (a one-page form is 1).
    form_steps: int = 0
    #: Questions the person answered in place, in the browser, when asked.
    human_assisted_fields: int = 0
    #: Questions left as they were (optional with no answer, prefilled, ...).
    fields_left_blank: int = 0
    #: Of those, questions that already held a value AA kept (a résumé parse
    #: by the site, a browser extension, the person) — a measured prefill rate.
    prefilled_kept: int = 0
    #: Fills that did not survive their read-back.
    fill_failures: int = 0
    #: Trap (honeypot) fields AA recognised and left empty.
    traps_left: int = 0
    #: Validation problems the page reported after an attempt to advance.
    validation_errors: int = 0
    #: Verified answers by provenance: profile, saved, session, human,
    #: acknowledgement, generated.
    answer_sources: dict[str, int] = Field(default_factory=dict)
    #: Verified fills by how they were made: type, clear-and-type,
    #: type-chunked, native-select, combobox, pointer, set-files, script.
    fill_rungs: dict[str, int] = Field(default_factory=dict)
    #: How each question's meaning was known: "structure" (autocomplete,
    #: input type), "lexicon(<lang>)" (a word in that language), "widget"
    #: (only the widget's shape) — the form's language coverage.
    question_typing: dict[str, int] = Field(default_factory=dict)
    #: The language the form declares ("" when it declares none) and the
    #: languages AA matched its words in (form_language.resolve).
    form_language: str = ""
    form_locales: list[str] = Field(default_factory=list)
    #: The version of the word lists that read the form (form_lexicon).
    lexicon_version: str = ""
    #: Accessibility barriers observed on the form, counted, keyed by the
    #: WCAG 2.2 criterion they bear on (form_barriers). Observations, never a
    #: conformance verdict.
    accessibility_signals: dict[str, int] = Field(default_factory=dict)
    #: Questions the person answered in AA's own window (answer_in_aa).
    answered_in_aa: int = 0
    #: Answer review (docs/adr/026): the trust level and timing in force,
    #: how many filled answers needed the person's OK, and how many they saw.
    answer_trust: str = ""
    review_timing: str = ""
    answers_needing_review: int = 0
    answers_reviewed: int = 0
    #: Multi-choice answers withheld because the question allows fewer or
    #: more options ("pick the best 2").
    selection_limited: int = 0
    #: Assessments and other forms the application sent the person to:
    #: kind, host (never the full link — it can carry a candidate token),
    #: whether the page made it a condition, and how AA knew.
    external_steps: list[dict[str, Any]] = Field(default_factory=list)

    # ── Submit action evidence ───────────────────────────────────────────
    submit_button_found: bool = False
    submit_button_text: str = ""
    submit_clicked: bool = False
    #: Which click-ladder rung fired the submit ("pointer" | "keyboard" |
    #: "native" | "js" | ""), and the page effect observed after it — how AA
    #: believes it submitted, so a study can separate a trusted-pointer
    #: submission from a last-resort synthetic one. Empty when the workflow
    #: never reached the click or the interaction port returned no detail.
    submit_rung: str = ""
    submit_effect: str = ""

    # ── Post-submit state ────────────────────────────────────────────────
    post_submit_url: str = ""
    page_title_after: str = ""
    confirmation_text_found: list[str] = Field(default_factory=list)
    url_changed_after_submit: bool = False

    # ── Blocking events ──────────────────────────────────────────────────
    captcha_encountered: bool = False
    login_wall_encountered: bool = False
    unknown_required_field: str | None = None  # label of blocking field
    #: Signal vocabulary of the page verdict that shaped this attempt
    #: (computed by domain/services/page_assessment.py; the challenge signal
    #: vocabulary originates in domain/services/challenge_assessment.py).
    #: Empty when no challenge evidence was seen. Recorded so a disputed
    #: verdict says WHY, not just WHAT.
    challenge_signals: list[str] = Field(default_factory=list)

    # ── Final outcome classification ─────────────────────────────────────
    outcome: Literal[
        "SUBMITTED",                # Confident: confirmation phrase + URL change
        "PROBABLY_SUBMITTED",       # Likely: URL changed, no clear confirmation phrase
        "AMBIGUOUS",                # Uncertain: submit clicked, no clear post-state
        "UNKNOWN",                  # Cannot tell whether a dispatch reached the site
        "FAILED_NO_SUBMIT_BUTTON",  # No submit button found
        "FAILED_NOTHING_FILLED",    # Reached a page but filled no field: nothing to submit
        "FAILED_NAVIGATION",        # Could not navigate to the form
        "FAILED_REQUIRED_FIELD",    # Blocked by unknown required field
        "FAILED_FILE_UPLOAD",       # Required file upload failed
        "CAPTCHA_BLOCKED",          # Stopped by CAPTCHA challenge
        "LOGIN_WALL_BLOCKED",       # Stopped by login/sign-up requirement
        "ACCOUNT_REQUIRED",         # The apply route demands an account on the site
        "ASSESSMENT_REQUIRED",      # A page was a test; AA never takes tests for the person
        "USER_SKIPPED",             # User declined at HITL checkpoint
        "SUBMISSION_GATE_BLOCKED",  # Submission gate unsatisfied — never clicked
        "POLICY_BLOCKED",           # Admin policy or cooldown blocked
        "ERROR",                    # Unhandled exception
    ] = "AMBIGUOUS"

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error_message: str | None = None

    # ── Derived properties ───────────────────────────────────────────────

    @property
    def is_likely_success(self) -> bool:
        """Returns True if the evidence suggests a real application was submitted."""
        return self.outcome in ("SUBMITTED", "PROBABLY_SUBMITTED")

    @property
    def is_blocked(self) -> bool:
        """Returns True if a blocking event prevented submission."""
        return self.outcome in (
            "CAPTCHA_BLOCKED",
            "LOGIN_WALL_BLOCKED",
            "ACCOUNT_REQUIRED",
            "FAILED_REQUIRED_FIELD",
            "FAILED_FILE_UPLOAD",
        )

    def __bool__(self) -> bool:
        """Truthiness delegates to :attr:`is_likely_success`.

        This preserves backward compatibility with orchestrator code that
        checks ``if result:`` after calling ``ApplicationsWorkflow.run()``.
        """
        return self.is_likely_success

    # ── Logging helpers ──────────────────────────────────────────────────

    def to_log_string(self) -> str:
        """Single-line summary for INFO-level logging."""
        parts = [
            f"outcome={self.outcome}",
            f"confidence={self.confidence:.0%}",
            f"fields={self.required_fields_filled}/{self.fields_classified}",
        ]
        if self.confirmation_text_found:
            first = self.confirmation_text_found[0][:40]
            parts.append(f"confirmation='{first}'")
        if self.error_message:
            parts.append(f"error='{self.error_message[:60]}'")
        if self.ats_platform:
            parts.append(f"ats={self.ats_platform}")
        return " | ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# The outcome vocabulary — ONE table, ONE source (P0-2)
#
# job_history.status (via mark_applied), applied_jobs.outcome (via
# record_application_permanently) and cross-session dedup all derive from
# this table. Dedup blocks on any outcome whose blocking flag is set — in
# EITHER store. Until this table existed, two vocabularies were written by
# two paths and a submission AA could not rule out (AMBIGUOUS) was silently
# retriable. An outcome this table does not recognise maps to UNKNOWN's rule
# — fail closed, never silently retriable.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OutcomeRule:
    """One outcome's persistence and dedup semantics."""

    history_status: str          # written to job_history.status
    write_permanent_log: bool    # whether applied_jobs gets a row
    blocks_reapplication: bool   # cross-session dedup blocks a later attempt
    retriable: bool              # a later attempt is legitimate


OUTCOME_VOCABULARY: dict[str, OutcomeRule] = {
    "SUBMITTED": OutcomeRule("APPLIED", True, True, False),
    "PROBABLY_SUBMITTED": OutcomeRule("APPLIED", True, True, False),
    "AMBIGUOUS": OutcomeRule("UNKNOWN", True, True, False),
    "UNKNOWN": OutcomeRule("UNKNOWN", True, True, False),
    "USER_SKIPPED": OutcomeRule("SKIPPED", True, False, True),
    "SUBMISSION_GATE_BLOCKED": OutcomeRule("GATE_BLOCKED", False, False, True),
    "POLICY_BLOCKED": OutcomeRule("POLICY_BLOCKED", False, False, True),
    "CAPTCHA_BLOCKED": OutcomeRule("BLOCKED", True, False, True),
    "LOGIN_WALL_BLOCKED": OutcomeRule("BLOCKED", True, False, True),
    "ACCOUNT_REQUIRED": OutcomeRule("BLOCKED", True, False, True),
    "ASSESSMENT_REQUIRED": OutcomeRule("BLOCKED", True, False, True),
    "FAILED_NO_SUBMIT_BUTTON": OutcomeRule("FAILED", True, False, True),
    "FAILED_NOTHING_FILLED": OutcomeRule("FAILED", True, False, True),
    "FAILED_NAVIGATION": OutcomeRule("FAILED", True, False, True),
    "FAILED_REQUIRED_FIELD": OutcomeRule("FAILED", True, False, True),
    "FAILED_FILE_UPLOAD": OutcomeRule("FAILED", True, False, True),
    "ERROR": OutcomeRule("FAILED", True, False, True),
}

#: Raw outcomes (applied_jobs.outcome) that block re-application.
BLOCKING_OUTCOMES: frozenset[str] = frozenset(
    name for name, rule in OUTCOME_VOCABULARY.items() if rule.blocks_reapplication
)

#: Mapped job_history.status values that block re-application.
BLOCKING_HISTORY_STATUSES: frozenset[str] = frozenset(
    rule.history_status for rule in OUTCOME_VOCABULARY.values() if rule.blocks_reapplication
)

#: Click-ladder rungs that refuse BEFORE anything can dispatch. Anything after
#: a rung ran is UNKNOWN — the click may already have happened.
_PRE_DISPATCH_RUNGS: frozenset[str] = frozenset({"probe", "none"})


def outcome_rule_for(outcome: str) -> OutcomeRule:
    """The rule for an outcome; anything unrecognised maps to UNKNOWN's rule."""
    return OUTCOME_VOCABULARY.get(outcome, OUTCOME_VOCABULARY["UNKNOWN"])


def history_status_for(outcome: str) -> str:
    """The job_history.status for an evidence outcome."""
    return outcome_rule_for(outcome).history_status


def outcome_for_click_failure(*, raised: bool, rung: str | None) -> str:
    """The outcome for a submit click that did not report success.

    The rung decides whenever it is known — a probe/none refusal never
    dispatched (ERROR), whether it arrived as a returned failure or as an
    exception carrying the rung. Everything else is UNKNOWN: an exception
    with no rung, or any rung that ran, may already have dispatched.
    """
    if rung in _PRE_DISPATCH_RUNGS:
        return "ERROR"
    return "UNKNOWN"