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
        salary_min: Minimum disclosed salary, annualised USD, or None when
            no US-dollar pay figure was found (see
            domain/services/salary_extraction.py).
        salary_max: Maximum disclosed salary, annualised USD, or None.
        salary_source_text: The pay span as stated on the page (with an
            "[OTE]" tag for on-target earnings), or None. The audit trail
            for the two annualised figures; the aggregator stores it as
            salary_observations.source_text.
        platform: Source platform identifier.
        first_seen_date: When AA first observed this exact posting.
        posting_hash: Structural hash for deduplication/lifecycle tracking.
        application_url_is_generic: Whether Apply resolves to a non-form page.
        metro_area: Normalized MSA name if determinable.
        company_linkedin_age_days: Enrichment data, if available.
        company_domain_age_days: Enrichment data, if available.
        company_has_web_presence: Enrichment data, if available.
        page_copy_id: Fingerprint of the cleaned page copy kept on this
            device for this posting (item 6), or None when page copies are
            off or no copy was kept. Never the copy, never its address.
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
    page_copy_id: str | None = None
    salary_source_text: str | None = None


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
        attempt_id: Joins every page of one application attempt to the
            outcome record for that attempt. Without it a partial attempt's
            rows are indistinguishable from a completed one's, and friction
            data reads as successful applications.
        page_index: Zero-based step within a multi-page application. One
            observation is emitted per wizard page, so a five-step form
            produces five records with indices 0-4. A merged record would
            lose which fields lived on which step, and for research the
            per-step structure is the interesting part.
    """
    platform: str = ""
    company_name: str | None = None
    job_title: str = ""
    jurisdiction: str | None = None
    posting_hash: str | None = None
    form_structure: FormStructure = field(default_factory=FormStructure)
    knockout_thresholds: dict[str, float] = field(default_factory=dict)
    estimated_completion_minutes: int | None = None
    page_index: int = 0
    attempt_id: str = ""
    application_form_field_count: int | None = None


@dataclass(frozen=True)
class ApplicationOutcomeObservation:
    """Outcome of a submitted application, for LM-02 black hole tracking.

    Attributes:
        platform: ATS or job board identifier.
        company_id: Anonymized company identifier (already hashed), or None
            when the posting carried no usable company name. None is
            deliberate: the retired hashing site digested the empty string,
            so an absent company arrived in the corpus as a real, joinable
            identity shared by every company-less posting. The same holds for
            the placeholder display strings producers invent when extraction
            fails ("Unknown", "N/A"): compute_company_id recognises them as
            absence and mints None, so the sentinel cannot re-create the
            phantom one layer up. The column is nullable.
        submitted_date: Date the application was submitted.
        acknowledgment_received: Whether ANY response was received within 30 days.
        acknowledgment_date: Date of acknowledgment, if received.
    """
    platform: str
    company_id: str | None
    submitted_date: date
    acknowledgment_received: bool = False
    acknowledgment_date: date | None = None


# ---------------------------------------------------------------------------
# Discovery-surface observations (§4b).
#
# These records are observations about *employers, platforms, and pages* —
# never about the user. They carry no search URLs, no query strings, and no
# user-identifying fields. Structural variables only: card architecture,
# resolution routes, sponsored/organic placement, syndication topology
# (destination hosts and anchor texts), and block verdicts. AA does not infer
# protected characteristics anywhere in this record, and nothing here can
# support such an inference.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryCandidateObservation:
    """One URL candidate's outcome for one card.

    Attributes:
        original_url: The href as found on the page.
        resolved_url: The absolute URL after resolution/unwrap.
        resolved_host: Host of the resolved URL (syndication topology datum).
        anchor_text: Anchor text (carries apply-intent and source attribution).
        source: static | revealed | navigation.
        outcome: selected | candidate | rejected.
        rejection_reason: Why it was rejected, or "" when kept.
        ad_evidence: Concrete advertising signals when rejected as advertising.
        apply_intent: Whether the anchor text expressed apply intent.
        title_overlap: Title-alignment score used in selection.
        method: Unwrap description or "top-level navigation".
    """

    original_url: str = ""
    resolved_url: str = ""
    resolved_host: str = ""
    anchor_text: str = ""
    source: str = ""
    outcome: str = ""
    rejection_reason: str = ""
    ad_evidence: tuple[str, ...] = ()
    apply_intent: bool = False
    title_overlap: float = 0.0
    method: str = ""


@dataclass(frozen=True)
class DiscoveryCardObservation:
    """One card's resolution record on the search surface.

    Attributes:
        card_index: Index within the detected group.
        title: Job title as displayed (public posting data).
        resolution_state: resolved | multi_route | deferred | no_destination.
        selected_host: Host of the selected destination, or "" when none.
        candidates: All candidate outcomes, kept and rejected.
    """

    card_index: int = -1
    title: str = ""
    resolution_state: str = ""
    selected_host: str = ""
    candidates: tuple[DiscoveryCandidateObservation, ...] = ()


@dataclass(frozen=True)
class DiscoveryObservation:
    """One search-results page as a research observation.

    Attributes:
        provider: Provider tag (e.g. "Google", "Bing") — the source surface.
        page_host: Host of the results page. The full URL is deliberately
            excluded: it would carry the user's search query.
        page_state: normal | captcha_block | login_required | error_404 | unknown.
        blocked: Whether the page was a block interstitial (distinct from a
            genuinely empty result set — D5).
        architecture: Derived card-group architecture label
            (anchorful | identifier_js | mixed | none).
        card_count: Cards detected in the dominant group.
        resolved_count: Cards with a selected destination.
        multi_route_count: Cards with multiple legitimate routes, no selection.
        deferred_count: Cards with material seen but nothing selected.
        no_destination_count: Cards with no usable destination material.
        sponsored_card_count: Cards whose only URL material was advertising.
        activation_attempts: Cards clicked during deferred resolution.
        activation_resolved: Cards that became resolved via activation.
        learned_identity: Identity attributes learned by sibling diff.
        cards: Per-card observation records.
    """

    provider: str = ""
    page_host: str = ""
    page_state: str = "normal"
    blocked: bool = False
    architecture: str = ""
    card_count: int = 0
    resolved_count: int = 0
    multi_route_count: int = 0
    deferred_count: int = 0
    no_destination_count: int = 0
    sponsored_card_count: int = 0
    activation_attempts: int = 0
    activation_resolved: int = 0
    learned_identity: tuple[str, ...] = ()
    cards: tuple[DiscoveryCardObservation, ...] = ()


# ---------------------------------------------------------------------------
# Session accounting (item 3).
# ---------------------------------------------------------------------------

#: One accounting dimension: (name, count) pairs, sorted by name.
Tally = tuple[tuple[str, int], ...]


def _tally(counts: dict[str, int]) -> Tally:
    return tuple(sorted((k, int(v)) for k, v in counts.items() if v))


@dataclass(frozen=True)
class ResearchAccounting:
    """What research collection did during one session.

    Item 5 counted observation-path failures in process and nothing ever
    read them; this record is how they leave the process. It separates three
    things a reader must not confuse:

    * ``recorded`` — rows newly written this session, per table.
    * ``lost`` — observations or rows that were NOT recorded because a step
      failed, per site, counted in records (a failed batch of five counts
      five). A non-empty ``lost`` means the database under-represents this
      session.
    * ``degraded`` — work that was recorded in a weaker form, per site: a
      signal written without its provenance signature, a detector that ran
      without its lifecycle history, an analysis pass that failed.

    ``corpus`` holds totals for the whole research database (all sessions)
    at the time of reading. ``complete`` is False when collection was still
    flushing at the time of reading, so the counts may still grow; a report
    must say so rather than present them as final.

    ``active`` is False when research was off for the session; every other
    field is then empty.
    """

    active: bool = False
    complete: bool = True
    recorded: Tally = ()
    lost: Tally = ()
    degraded: Tally = ()
    corpus: Tally = ()

    @classmethod
    def from_counts(
        cls,
        *,
        complete: bool,
        recorded: dict[str, int],
        lost: dict[str, int],
        degraded: dict[str, int],
        corpus: dict[str, int],
    ) -> ResearchAccounting:
        """Build an active record from plain counters. Session tallies drop
        zero counts; corpus totals keep them."""
        return cls(
            active=True,
            complete=complete,
            recorded=_tally(recorded),
            lost=_tally(lost),
            degraded=_tally(degraded),
            # Corpus totals keep their zeros: "0 signals on record" is a
            # fact, where a missing session tally simply means none.
            corpus=tuple(sorted((k, int(v)) for k, v in corpus.items())),
        )

    @property
    def records_recorded(self) -> int:
        return sum(n for _, n in self.recorded)

    @property
    def records_lost(self) -> int:
        return sum(n for _, n in self.lost)

    @property
    def records_degraded(self) -> int:
        return sum(n for _, n in self.degraded)

    def to_dict(self) -> dict[str, object]:
        """JSON-ready form, as the session report stores it."""
        return {
            "active": self.active,
            "complete": self.complete,
            "recorded": dict(self.recorded),
            "lost": dict(self.lost),
            "degraded": dict(self.degraded),
            "corpus": dict(self.corpus),
        }


@runtime_checkable
class ResearchSessionPort(Protocol):
    """The session-lifetime side of research collection (item 3).

    Workflows only observe (ResearchObserverPort); the orchestrator owns the
    session's end, so it alone needs to finish collection and read what it
    did. Satisfied structurally by ResearchSignalAggregator and by
    NullResearchObserver.
    """

    def stop(self) -> None:
        """Flush everything queued, then accept nothing more. Idempotent."""
        ...

    def accounting(self) -> ResearchAccounting:
        """What this session recorded, lost and degraded. Never raises."""
        ...


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

    def observe_discovery(self, observation: DiscoveryObservation) -> None:
        """Submit a search-surface observation (sponsored fraction, card
        architecture, resolution routes, block verdicts).

        Args:
            observation: The discovery-surface record for one results page.
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

    def observe_discovery(self, observation: DiscoveryObservation) -> None:
        pass

    @property
    def is_enabled(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def accounting(self) -> ResearchAccounting:
        """Research was off: nothing recorded, nothing lost."""
        return ResearchAccounting()
