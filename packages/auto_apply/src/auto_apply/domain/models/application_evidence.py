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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# ATS-specific confirmation patterns — organized by ATS platform.
# These are the phrases that appear on confirmation pages.
# Used by ApplicationsWorkflow._submit_application().
# ─────────────────────────────────────────────────────────────────────────────

ATS_CONFIRMATION_PATTERNS: dict[str, list[str]] = {
    "greenhouse": [
        "thank you for applying",
        "application submitted",
        "/confirmations/",
        "we'll review",
    ],
    "lever": [
        "thank you for applying",
        "application received",
        "/thank-you",
        "we'll be in touch",
    ],
    "workday": [
        "thank you for your interest",
        "application submitted",
        "your application has been submitted",
        "we have received",
    ],
    "ashby": [
        "thanks for applying",
        "application submitted",
        "received your application",
    ],
    "icims": [
        "application was submitted",
        "thank you",
        "successfully submitted",
        "/system/templates/selfapply/",
    ],
    "taleo": [
        "application submission is confirmed",
        "thank you for completing",
        "application was submitted",
    ],
    "smartrecruiters": [
        "thank you",
        "application received",
        "we received",
    ],
    "brassring": [
        "your application has been submitted",
        "thank you",
    ],
    "jobvite": [
        "thank you",
        "application submitted",
        "/web#action/ViewJobPostings",
    ],
    "generic": [
        "thank you for applying",
        "application submitted",
        "application received",
        "we'll be in touch",
        "successfully submitted",
        "thank you for your interest",
        "your application",
        "we have received your",
    ],
}


class ApplicationEvidence(BaseModel):
    """Structured evidence from a single application attempt.

    Produced by ApplicationsWorkflow._submit_application() and returned
    up through ApplicationsWorkflow.run().  Stored in the database.  Used
    by the session report and research pipeline.

    Truthiness: ``bool(evidence)`` delegates to :attr:`is_likely_success`,
    so existing orchestrator code that checks ``if result:`` continues to
    work without changes.
    """
    model_config = ConfigDict(frozen=True)

    # ── Pre-submit state ─────────────────────────────────────────────────
    attempt_id: str = ""   # joins this outcome to its per-page research rows
    pre_submit_url: str = ""
    page_title_before: str = ""
    ats_platform: str | None = None  # matched ATS name (e.g. "greenhouse")

    # ── Form interaction evidence ────────────────────────────────────────
    fields_classified: int = 0
    required_fields_filled: int = 0
    optional_fields_filled: int = 0
    custom_fields_answered: int = 0
    pages_navigated: int = 0
    file_upload_attempted: bool = False
    file_upload_succeeded: bool = False
    used_gpt4all: bool = False

    # ── Submit action evidence ───────────────────────────────────────────
    submit_button_found: bool = False
    submit_button_text: str = ""
    submit_clicked: bool = False

    # ── Post-submit state ────────────────────────────────────────────────
    post_submit_url: str = ""
    page_title_after: str = ""
    confirmation_text_found: list[str] = Field(default_factory=list)
    url_changed_after_submit: bool = False

    # ── Blocking events ──────────────────────────────────────────────────
    captcha_encountered: bool = False
    login_wall_encountered: bool = False
    unknown_required_field: str | None = None  # label of blocking field

    # ── Final outcome classification ─────────────────────────────────────
    outcome: Literal[
        "SUBMITTED",                # Confident: confirmation phrase + URL change
        "PROBABLY_SUBMITTED",       # Likely: URL changed, no clear confirmation phrase
        "AMBIGUOUS",                # Uncertain: submit clicked, no clear post-state
        "FAILED_NO_SUBMIT_BUTTON",  # No submit button found
        "FAILED_NAVIGATION",        # Could not navigate to the form
        "FAILED_REQUIRED_FIELD",    # Blocked by unknown required field
        "FAILED_FILE_UPLOAD",       # Required file upload failed
        "CAPTCHA_BLOCKED",          # Stopped by CAPTCHA challenge
        "LOGIN_WALL_BLOCKED",       # Stopped by login/sign-up requirement
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