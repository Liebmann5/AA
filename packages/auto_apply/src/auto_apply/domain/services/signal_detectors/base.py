"""
Base types for all research signal detectors.

All detectors are pure functions / stateless classes — zero I/O.
They receive a DetectionContext (plain data) and return ResearchSignal objects.
This makes every detector testable without a browser, a database, or a network.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from auto_apply.domain.constants import (
    RESEARCH_SALT_ENV_VAR,
    RESEARCH_SCHEMA_VERSION,
    SEVERITY_FLAG,
    SEVERITY_CONCERN,
    SEVERITY_VIOLATION,
)


@dataclass(frozen=True)
class ResearchSignal:
    """A single detected research signal event.

    Attributes:
        signal_id: UUID for this specific detection event.
        signal_type: e.g. "GJ-01", "DISC-01" — maps to spec constants.
        severity: "flag" / "concern" / "violation".
        confidence: 0.0–1.0 probability this is a genuine signal.
        evidence_text: Anonymized excerpt proving the signal (max 200 chars).
        platform: ATS/job-board where detected, e.g. "linkedin".
        jurisdiction: US state/city code, e.g. "CA", "NYC".
        company_id: HMAC-SHA256 of company name (anonymized).
        job_category: BLS SOC code when available.
        detected_date: Date this signal was logged.
        schema_version: For longitudinal data compatibility.
        posting_hash: Structural hash of the source posting, if known.
            Used for (a) deduplication — see run_all_detectors() in
            __init__.py, which derives a deterministic signal_id from
            (signal_type, posting_hash, detected_date) when this is set,
            so the SAME underlying fact observed via multiple code paths
            (e.g. job-posting observation AND form observation both
            noticing "no salary disclosed in CA") collapses to one row
            via INSERT OR IGNORE — and (b) joining signals back to
            job_lifecycles / salary_observations for corpus analysis.
    """
    signal_id: str
    signal_type: str
    severity: str
    confidence: float
    evidence_text: str
    platform: str | None = None
    jurisdiction: str | None = None
    company_id: str | None = None
    job_category: str | None = None
    detected_date: date = field(default_factory=date.today)
    schema_version: int = RESEARCH_SCHEMA_VERSION
    posting_hash: str | None = None

    @classmethod
    def create(
        cls,
        signal_type: str,
        severity: str,
        confidence: float,
        evidence_text: str,
        platform: str | None = None,
        jurisdiction: str | None = None,
        company_name: str | None = None,
        job_category: str | None = None,
    ) -> "ResearchSignal":
        """Factory that generates a UUID and anonymizes company name.

        Args:
            signal_type: The signal identifier (e.g. "GJ-01").
            severity: One of SEVERITY_FLAG / SEVERITY_CONCERN / SEVERITY_VIOLATION.
            confidence: Detection confidence 0.0–1.0.
            evidence_text: Raw text excerpt (will be truncated to 200 chars).
            platform: Job board or ATS platform identifier.
            jurisdiction: US state/city code.
            company_name: Company name (anonymized via HMAC-SHA256 before storage).
            job_category: BLS SOC code.

        Returns:
            A new ResearchSignal with anonymized company_id.
        """
        company_id: str | None = None
        if company_name:
            salt = os.environ.get(RESEARCH_SALT_ENV_VAR, "default_dev_salt")
            company_id = hmac.new(
                salt.encode(),
                company_name.lower().encode(),
                hashlib.sha256,
            ).hexdigest()[:16]

        return cls(
            signal_id=str(uuid.uuid4()),
            signal_type=signal_type,
            severity=severity,
            confidence=min(1.0, max(0.0, confidence)),
            evidence_text=evidence_text[:200],
            platform=platform,
            jurisdiction=jurisdiction,
            company_id=company_id,
            job_category=job_category,
        )


@dataclass
class DetectionContext:
    """All data available to signal detectors for a single job posting.

    Populated by the research pipeline before invoking detectors.
    Detectors must treat this as read-only.

    Attributes:
        job_title: Raw job title string.
        job_description: Full job description text.
        company_name: Raw company name (anonymized internally by ResearchSignal.create).
        location: Location string, e.g. "New York, NY" or "Remote".
        jurisdiction: Detected US jurisdiction code, e.g. "NYC", "CA".
        salary_min: Minimum salary in USD/year (None if not disclosed).
        salary_max: Maximum salary in USD/year (None if not disclosed).
        platform: Job board or ATS identifier.
        first_seen_date: When AA first observed this posting.
        current_date: Date of this detection run (for age calculations).
        days_live: Days between first_seen and current_date.
        form_field_count: Number of fields in the application form (if observed).
        form_has_salary_history_field: Whether form asked for prior salary.
        form_wcag_violations: List of WCAG violation codes from form analysis.
        posting_hash: Structural hash of description for deduplication.
        times_seen_cross_platform: How many platforms have this posting hash.
    """
    job_title: str = ""
    job_description: str = ""
    company_name: str | None = None
    location: str | None = None
    jurisdiction: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    platform: str | None = None
    first_seen_date: date | None = None
    current_date: date = field(default_factory=date.today)
    days_live: int | None = None
    form_field_count: int | None = None
    form_required_fields: int | None = None
    form_essay_count: int | None = None
    form_has_salary_history_field: bool = False
    form_wcag_violations: list[str] = field(default_factory=list)
    posting_hash: str | None = None
    times_seen_cross_platform: int = 1
    previous_posting_dates: list[date] = field(default_factory=list)
    company_has_warn_filing: bool = False
    estimated_completion_minutes: int | None = None

    # ── Extended fields (Research Module v2.1) ──────────────────────────────
    # GJ-04: Apply-with-no-ATS
    application_url_is_generic: bool = False  # Apply button -> homepage/email/404
    application_form_field_count: int | None = None  # 0 = no real form found

    # DISC-05: Geographic Pay Discrimination
    metro_area: str | None = None  # e.g. "San Francisco-Oakland-Berkeley, CA"
    cost_of_living_index: float | None = None  # 1.0 = national average

    # DP-05: Phantom Company
    company_linkedin_age_days: int | None = None
    company_domain_age_days: int | None = None
    company_has_web_presence: bool | None = None  # None = unknown/not checked

    # AH-01: ATS Knockout Question Pattern Analysis
    # Maps question type -> threshold value observed on the form, e.g.
    #   {"min_years_experience": 8, "min_salary_expectation": 150000}
    knockout_thresholds: dict[str, float] = field(default_factory=dict)

    # ST-03: Below-Market Salary (populated by signal_aggregator from corpus)
    salary_corpus_p25_for_role: float | None = None  # 25th percentile for this role/skillset
    salary_corpus_sample_size: int = 0

    @property
    def description_lower(self) -> str:
        """Lowercase description for case-insensitive matching."""
        return self.job_description.lower()

    @property
    def title_lower(self) -> str:
        """Lowercase title for case-insensitive matching."""
        return self.job_title.lower()


@runtime_checkable
class SignalDetector(Protocol):
    """Protocol that all signal detector classes must implement."""

    @property
    def signal_type(self) -> str:
        """The signal type this detector produces, e.g. 'GJ-01'."""
        ...

    def detect(self, ctx: DetectionContext) -> list[ResearchSignal]:
        """Run detection against the provided context.

        Args:
            ctx: All available data for the job posting.

        Returns:
            List of detected signals (empty if nothing found).
        """
        ...
