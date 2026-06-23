"""
ResearchObserverPort — the contract between AA's workflows and the research
data collection pipeline.

ARCHITECTURE: Workflows (Discovery, Vetting, Applications) depend ONLY on
this Protocol — they never import ResearchSignalAggregator or any adapter
directly (Rule 1: domain/application never imports infrastructure/adapters).

The composition root wires the concrete ResearchSignalAggregator (or a
NullResearchObserver when research.enabled=false) and injects it as this
Protocol type into each workflow.

All methods are designed to be called synchronously from workflow code but
MUST be non-blocking — implementations enqueue work for a background thread
(see ResearchSignalAggregator's queue-plus-daemon pattern). This satisfies
the EventBus handler thread-safety contract even when called outside the
EventBus (direct injection is preferred over events here because the
DetectionContext requires rich data assembly that's awkward to serialize
into an event payload).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from auto_apply.domain.ports.page_understanding_port import FormStructure


@dataclass(frozen=True)
class JobPostingObservation:
    """Everything observed about a job posting, ready for signal detection.

    This is the data contract between workflows and the research pipeline.
    Workflows populate this from whatever data they have available — fields
    left as None/default simply mean those detectors won't fire for this
    posting (graceful degradation, not an error).

    Attributes:
        job_title: Job title text.
        job_description: Full job description text.
        company_name: Raw company name (anonymized downstream).
        location: Location string.
        jurisdiction: Detected US jurisdiction code.
        salary_min: Minimum disclosed salary, or None.
        salary_max: Maximum disclosed salary, or None.
        platform: Source platform identifier.
        first_seen_date: When AA first observed this exact posting.
        posting_hash: Structural hash for deduplication/lifecycle tracking.
        application_url_is_generic: Whether Apply resolves to a non-form page.
        metro_area: Normalized MSA name if determinable.
        company_linkedin_age_days: Enrichment data, if available.
        company_domain_age_days: Enrichment data, if available.
        company_has_web_presence: Enrichment data, if available.
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
    posting_hash: str | None = None
    application_url_is_generic: bool = False
    metro_area: str | None = None
    company_linkedin_age_days: int | None = None
    company_domain_age_days: int | None = None
    company_has_web_presence: bool | None = None


@dataclass(frozen=True)
class FormObservation:
    """Everything observed about an application form, ready for signal detection.

    Attributes:
        platform: ATS or job board identifier.
        company_name: Raw company name (anonymized downstream).
        job_title: Associated job title.
        jurisdiction: US state/city code for the role.
        posting_hash: Links this form to its job posting.
        form_structure: Full FormStructure from PageUnderstandingPort.
        knockout_thresholds: Detected knockout-question thresholds, e.g.
            {"min_years_experience": 8}.
        estimated_completion_minutes: Estimated time to complete the form.
        application_form_field_count: Total field count (0 = no real form).
    """
    platform: str = ""
    company_name: str | None = None
    job_title: str = ""
    jurisdiction: str | None = None
    posting_hash: str | None = None
    form_structure: FormStructure = field(default_factory=FormStructure)
    knockout_thresholds: dict[str, float] = field(default_factory=dict)
    estimated_completion_minutes: int | None = None
    application_form_field_count: int | None = None


@dataclass(frozen=True)
class ApplicationOutcomeObservation:
    """Outcome of a submitted application, for LM-02 black hole tracking.

    Attributes:
        platform: ATS or job board identifier.
        company_id: Anonymized company identifier (already hashed).
        submitted_date: Date the application was submitted.
        acknowledgment_received: Whether ANY response was received within 30 days.
        acknowledgment_date: Date of acknowledgment, if received.
    """
    platform: str
    company_id: str
    submitted_date: date
    acknowledgment_received: bool = False
    acknowledgment_date: date | None = None


@runtime_checkable
class ResearchObserverPort(Protocol):
    """Contract for research data collection, injected into workflows.

    Implementations:
        ResearchSignalAggregator (adapters/secondary/research/) — real implementation
        NullResearchObserver (this module) — no-op when research is disabled

    All methods MUST be non-blocking (<1ms) and MUST NOT raise.
    """

    def observe_job_posting(self, observation: JobPostingObservation) -> None:
        """Submit a job posting for signal detection.

        Args:
            observation: All available data about the posting.
        """
        ...

    def observe_form(self, observation: FormObservation) -> None:
        """Submit an application form for signal detection.

        Args:
            observation: All available data about the form.
        """
        ...

    def observe_application_outcome(
        self, observation: ApplicationOutcomeObservation
    ) -> None:
        """Record an application outcome for black-hole tracking (LM-02).

        Args:
            observation: Outcome data.
        """
        ...

    @property
    def is_enabled(self) -> bool:
        """Whether research collection is currently active (consent given)."""
        ...


class NullResearchObserver:
    """No-op ResearchObserverPort for when research.enabled=false.

    Used by composition_root.py as the default. Every method is a no-op.
    This is the worst-case-user-safe default — research collection never
    runs unless the user has explicitly opted in via consent.
    """

    def observe_job_posting(self, observation: JobPostingObservation) -> None:
        pass

    def observe_form(self, observation: FormObservation) -> None:
        pass

    def observe_application_outcome(
        self, observation: ApplicationOutcomeObservation
    ) -> None:
        pass

    @property
    def is_enabled(self) -> bool:
        return False
