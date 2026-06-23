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
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class JobCardInfo:
    """A job listing card extracted from a SERP page.

    Attributes:
        title: Job title text.
        company: Company name text.
        location: Location string.
        url: Direct link to the job, or empty string.
        snippet: Brief description snippet.
        posted_date_text: Raw "posted X days ago" string, or empty.
        salary_text: Salary text if visible on SERP card, or empty.
        confidence: 0.0–1.0 confidence this is a genuine job card.
    """
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    snippet: str = ""
    posted_date_text: str = ""
    salary_text: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class SERPStructure:
    """Structured result of analyzing a Search Engine Results Page.

    Attributes:
        job_cards: All detected job listing cards.
        pagination_present: Whether there are more pages to navigate.
        total_results_text: Raw "About 12,400 results" string if present.
        captcha_detected: Whether a CAPTCHA challenge is visible.
    """
    job_cards: tuple[JobCardInfo, ...] = field(default=())
    pagination_present: bool = False
    total_results_text: str = ""
    captcha_detected: bool = False


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
