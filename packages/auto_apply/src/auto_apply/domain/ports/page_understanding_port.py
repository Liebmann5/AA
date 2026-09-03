"""
PageUnderstandingPort — the correct home for Math subsystem capabilities.

This port replaces the architectural violation of MathDiscoveryProvider.
The Math subsystem is NOT a discovery source. It is a page analysis tool
that any engine can use. This port defines the contract; adapters implement it.

Correct usage:
    class GoogleProvider:
        def __init__(self, browser, prefs,
                     page_understanding: PageUnderstandingPort | None = None):
            self._page_understanding = page_understanding

        def run(self):
            structure = self._page_understanding.analyze_serp(context)
            jobs = self._extract_from_structure(structure)

Adapters that implement this port:
    MathPageUnderstandingAdapter   — uses Math DOM + Hungarian + VIPS
    BS4PageUnderstandingAdapter    — uses BeautifulSoup (fallback, no browser needed)
    NullPageUnderstandingAdapter   — no-op, returns empty structures (worst-case)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Protocol, runtime_checkable


class CardResolutionState(str, Enum):
    """Why a card has, or does not have, a selected destination URL."""

    RESOLVED = "resolved"
    MULTI_ROUTE = "multi_route"
    DEFERRED = "deferred"
    NO_DESTINATION = "no_destination"


@dataclass(frozen=True)
class JobUrlCandidate:
    """One validated destination hypothesis for a job card.

    This is evidence, not commitment. ``JobCardInfo.url`` is the commitment,
    and it is populated only from a selected candidate.
    """

    url: str = ""
    original_url: str = ""
    anchor_text: str = ""
    source: str = ""            # "static" | "revealed" | "navigation"
    score: float = 0.0
    title_overlap: float = 0.0
    method: str = ""            # unwrap description or "top-level navigation"
    apply_intent: bool = False
    pending_redirect: bool = False
    canonical_url: str = ""


@dataclass(frozen=True)
class JobUrlRejection:
    """A URL that was considered and rejected, with the reason.

    Rejection for *application* purposes never deletes the *observation* —
    the reason is the research datum (paid placement, dead-end text,
    internal endpoint, and so on).
    """

    original_url: str = ""
    resolved_url: str = ""
    reason: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobCardInfo:
    """A job listing card extracted from a SERP page.

    Gate semantics (unchanged): a card becomes a Job only when it has both
    title and ``url``. ``url`` is populated only from a selected candidate,
    so ``multi_route`` and ``deferred`` cards keep ``url=""`` and still fail
    the gate safely — while their candidates are retained as evidence.

    Attributes:
        title: Job title text.
        company: Company name text.
        location: Location string.
        url: Selected destination URL, or empty string.
        snippet: Brief description snippet.
        posted_date_text: Raw "posted X days ago" string, or empty.
        salary_text: Salary text if visible on SERP card, or empty.
        confidence: 0.0–1.0 confidence this is a genuine job card.
        card_index: Index of the card within its detected group.
        candidates: Validated destination candidates (may be several).
        rejections: Rejected URLs with reasons.
        resolution_state: resolved | multi_route | deferred | no_destination.
        identity_attribute: Learned per-card identity attribute name, if any.
        identity_value: That attribute's value on this card, if any.
    """

    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    snippet: str = ""
    posted_date_text: str = ""
    salary_text: str = ""
    confidence: float = 1.0
    card_index: int = -1
    candidates: tuple[JobUrlCandidate, ...] = ()
    rejections: tuple[JobUrlRejection, ...] = ()
    resolution_state: str = CardResolutionState.NO_DESTINATION.value
    identity_attribute: str = ""
    identity_value: str = ""

    @property
    def has_ad_rejection(self) -> bool:
        """True when any rejection was classified as advertising."""
        return any("advertising" in r.reason.lower() for r in self.rejections)


@dataclass(frozen=True)
class SerpResolutionReport:
    """Group-level structural report for one SERP card group."""

    learned_identity: tuple[str, ...] = ()
    chosen_level: str = "detected"
    detected_parent_count: int = 0
    note: str = ""


@dataclass(frozen=True)
class SERPStructure:
    """Structured result of analyzing a Search Engine Results Page.

    Attributes:
        job_cards: All detected job listing cards.
        pagination_present: Whether there are more pages to navigate.
        total_results_text: Raw "About 12,400 results" string if present.
        captcha_detected: Whether a CAPTCHA challenge is visible.
        resolution_report: Group-level resolution metadata.
    """

    PASS_FRACTION: ClassVar[float] = 0.6

    job_cards: tuple[JobCardInfo, ...] = field(default=())
    pagination_present: bool = False
    total_results_text: str = ""
    captcha_detected: bool = False
    resolution_report: SerpResolutionReport = field(default_factory=SerpResolutionReport)

    @property
    def total_cards(self) -> int:
        return len(self.job_cards)

    @property
    def resolved_count(self) -> int:
        return sum(
            1 for c in self.job_cards
            if c.resolution_state == CardResolutionState.RESOLVED.value
        )

    @property
    def multi_route_count(self) -> int:
        return sum(
            1 for c in self.job_cards
            if c.resolution_state == CardResolutionState.MULTI_ROUTE.value
        )

    @property
    def deferred_count(self) -> int:
        return sum(
            1 for c in self.job_cards
            if c.resolution_state == CardResolutionState.DEFERRED.value
        )

    @property
    def no_destination_count(self) -> int:
        return sum(
            1 for c in self.job_cards
            if c.resolution_state == CardResolutionState.NO_DESTINATION.value
        )

    @property
    def sponsored_card_count(self) -> int:
        """Cards whose only URL material was advertising (paid placement)."""
        return sum(
            1 for c in self.job_cards
            if not c.candidates and c.has_ad_rejection
        )

    @property
    def ad_leak(self) -> bool:
        """Defensive check: a surviving candidate still carrying ad evidence.

        Advertising candidates are rejected before candidacy, so this should
        be structurally impossible; the property exists so a future bypass
        fails loudly instead of silently passing the acceptance gate.
        """
        return any(
            "advertising" in (c.method or "").lower()
            for card in self.job_cards
            for c in card.candidates
        )

    @property
    def page_pass_yield(self) -> bool:
        """The strict acceptance gate: enough cards produced a committed URL."""
        if not self.job_cards or self.ad_leak:
            return False
        return (self.resolved_count / len(self.job_cards)) >= self.PASS_FRACTION

    @property
    def page_pass_route(self) -> bool:
        """The looser gate: the page exposed safe destination evidence."""
        if not self.job_cards or self.ad_leak:
            return False
        return (
            (self.resolved_count + self.multi_route_count) / len(self.job_cards)
        ) >= self.PASS_FRACTION


@dataclass(frozen=True)
class FormFieldInfo:
    """A single form field extracted from an application page.

    Attributes:
        field_id: Unique identifier (from HTML id attribute or generated).
        label_text: Associated label text.
        field_type: HTML input type or element type.
        name: The `name` attribute value.
        placeholder: Placeholder text if present.
        is_required: Whether the field is required.
        is_honeypot: Whether this appears to be a honeypot trap.
        options: For select/radio fields, the available options.
    """

    field_id: str = ""
    label_text: str = ""
    field_type: str = "text"
    name: str = ""
    placeholder: str = ""
    is_required: bool = False
    is_honeypot: bool = False
    options: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class FormStructure:
    """Structured result of analyzing an application form page.

    Attributes:
        fields: All detected form fields.
        page_count: Estimated number of form pages.
        has_file_upload: Whether resume/CV upload is present.
        has_cover_letter_field: Whether a cover letter field exists.
        wcag_violations: Accessibility violation codes found.
        has_salary_history_field: Whether prior salary is requested.
        confidence: Overall confidence in the analysis quality.
    """

    fields: tuple[FormFieldInfo, ...] = field(default=())
    page_count: int = 1
    has_file_upload: bool = False
    has_cover_letter_field: bool = False
    wcag_violations: tuple[str, ...] = field(default=())
    has_salary_history_field: bool = False
    confidence: float = 1.0


@dataclass(frozen=True)
class PageContext:
    """Input to PageUnderstandingPort — what's currently in the browser.

    Attributes:
        url: Current page URL.
        html_source: Raw HTML source (may be empty if browser is live).
        page_title: Browser tab title.
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.
    """

    url: str = ""
    html_source: str = ""
    page_title: str = ""
    viewport_width: int = 1920
    viewport_height: int = 1080


@runtime_checkable
class PageUnderstandingPort(Protocol):
    """Contract for all page analysis capabilities.

    Implementations:
        MathPageUnderstandingAdapter — primary, uses JS DOM + math algorithms
        BS4PageUnderstandingAdapter  — fallback, uses BeautifulSoup HTML parsing
        NullPageUnderstandingAdapter — no-op, returns empty structures

    Note: Methods return empty structures on failure, never raise.
    Callers must check the `confidence` field and the number of results.
    """

    def analyze_serp(self, context: PageContext) -> SERPStructure:
        """Extract job cards from a Search Engine Results Page.

        Args:
            context: Current page state (URL, HTML, dimensions).

        Returns:
            Structured job listing data. Returns empty SERPStructure on failure.
        """
        ...

    def analyze_form(self, context: PageContext) -> FormStructure:
        """Extract form fields from a job application page.

        Args:
            context: Current page state.

        Returns:
            Structured form field data. Returns empty FormStructure on failure.
        """
        ...

    def analyze_job_listing(self, context: PageContext) -> "JobListingStructure":
        """Extract structured job description from a job listing page.

        Args:
            context: Current page state.

        Returns:
            Structured job description data.
        """
        ...


@dataclass(frozen=True)
class JobListingStructure:
    """Structured result of analyzing a job description page.

    Attributes:
        full_text: Complete visible text of the job description.
        title: Job title as displayed on the page.
        company: Company name as displayed on the page.
        location: Location string.
        salary_text: Salary text as displayed, or empty.
        requirements_text: Extracted requirements section text.
        apply_button_present: Whether an Apply button was found.
        apply_url: URL the Apply button links to, if detectable.
    """

    full_text: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    salary_text: str = ""
    requirements_text: str = ""
    apply_button_present: bool = False
    apply_url: str = ""


class NullPageUnderstandingAdapter:
    """No-op implementation of PageUnderstandingPort.

    Used as the fallback when no perception adapter is available.
    Returns empty structures with confidence=0.0.
    Safe to use anywhere — never raises.
    """

    def analyze_serp(self, context: PageContext) -> SERPStructure:
        return SERPStructure()

    def analyze_form(self, context: PageContext) -> FormStructure:
        return FormStructure(confidence=0.0)

    def analyze_job_listing(self, context: PageContext) -> JobListingStructure:
        return JobListingStructure()
