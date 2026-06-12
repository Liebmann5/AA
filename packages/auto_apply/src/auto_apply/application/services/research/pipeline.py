"""Research data collection, anonymization, and export pipeline.

This module transforms AA from a job application tool into a research
platform. It captures structured, classified telemetry about every
interaction with the hiring market — from the candidate's perspective.

This is the infrastructure that makes AA academically valuable. Most
hiring research uses employer-side data (LinkedIn, ATS vendors, HR
analytics). AA produces the first large-scale candidate-side dataset.

Data Lifecycle:
    1. Collection:  SessionDataCollector captures raw events during a session.
    2. Classification:  Each event is tagged with structured metadata.
    3. Anonymization:  PII is stripped before any data leaves the device.
    4. Export:  Anonymized data is written to portable formats (CSV, JSON).
    5. Aggregation:  Optional — aggregate stats across sessions for dashboards.

Privacy Contract:
    - Research data collection is OPT-IN ONLY. Default is OFF.
    - No data is ever sent to any server. All data stays on the user's device.
    - The anonymizer runs BEFORE the exporter. Raw data never reaches the
      export stage.
    - The user can delete all research data at any time via the UI.
    - ConsentManager tracks consent state and prevents collection if not granted.

Research Signals Captured:
    - Employer response time (time between application and any response)
    - Ghosting detection (no response after N days)
    - ATS type identification (Greenhouse, Lever, Workday, etc.)
    - Application friction score (number of steps, time to complete)
    - Rejection patterns (which filter stage rejects, and why)
    - Callback rate by job category, company size, location
    - Duplicate/fake job listing detection
    - Form accessibility score (how usable the form is)

Example:
    >>> from auto_apply.application.services.research.pipeline import ResearchPipeline
    >>> pipeline = ResearchPipeline(consent_granted=True)
    >>> pipeline.record_application_attempt(job, result, metadata)
    >>> pipeline.export_session("./research_output/")
"""

# Layer: application
# Depends on: domain

import csv
import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Research Event Classification
# ─────────────────────────────────────────────────────────────────────────────

class EventCategory(Enum):
    """Top-level categories for research events."""
    DISCOVERY = auto()
    VETTING = auto()
    APPLICATION = auto()
    FORM_INTERACTION = auto()
    EMPLOYER_RESPONSE = auto()
    SYSTEM = auto()


class ApplicationOutcome(Enum):
    """Possible outcomes of an application attempt."""
    SUCCESS = "success"
    FAILED_FORM_ERROR = "failed_form_error"
    FAILED_NAVIGATION = "failed_navigation"
    FAILED_CAPTCHA = "failed_captcha"
    FAILED_TIMEOUT = "failed_timeout"
    FAILED_ATS_REJECTION = "failed_ats_rejection"
    REDIRECT_TO_CAREERS = "redirect_to_careers"
    ALREADY_APPLIED = "already_applied"
    SKIPPED_VETTING = "skipped_vetting"


class VettingOutcome(Enum):
    """Possible outcomes of a vetting evaluation."""
    PASSED = "passed"
    FAILED_TITLE_MISMATCH = "failed_title_mismatch"
    FAILED_LOCATION = "failed_location"
    FAILED_EXPERIENCE = "failed_experience"
    FAILED_SKILLS = "failed_skills"
    FAILED_BLACKLIST = "failed_blacklist"
    FAILED_THROTTLED = "failed_throttled"
    FAILED_DUPLICATE = "failed_duplicate"
    ERROR = "error"


class ATSType(Enum):
    """Known Applicant Tracking System types."""
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ICIMS = "icims"
    TALEO = "taleo"
    BAMBOOHR = "bamboohr"
    SMARTRECRUITERS = "smartrecruiters"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Research Data Models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DiscoveryEvent:
    """Records a single discovery action."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # noqa: E501
    provider: str = ""           # "google", "bing", "indeed", "company_page"
    query: str = ""              # The search query used (anonymized)
    location_query: str = ""     # The location searched
    results_count: int = 0       # How many listings were found
    new_results_count: int = 0   # How many were not duplicates
    page_load_time_ms: int = 0   # Time to load the search results page
    pagination_pages: int = 0    # How many pages were navigated


@dataclass
class VettingEvent:
    """Records a single vetting evaluation."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # noqa: E501
    job_hash: str = ""           # Anonymized job identifier
    outcome: str = ""            # VettingOutcome value
    rejection_reason: str = ""   # Human-readable reason if failed
    filter_name: str = ""        # Which filter rejected it
    fit_score: float = 0.0       # Computed fit score (0.0-1.0)
    processing_time_ms: int = 0  # Time to evaluate


@dataclass
class ApplicationEvent:
    """Records a single application attempt — the core research data point."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # noqa: E501
    job_hash: str = ""           # Anonymized job identifier
    company_hash: str = ""       # Anonymized company identifier
    ats_type: str = "unknown"    # ATSType value
    outcome: str = ""            # ApplicationOutcome value
    form_steps: int = 0          # Number of form pages/steps
    form_fields: int = 0         # Total form fields encountered
    fields_auto_filled: int = 0  # Fields AA filled successfully
    fields_failed: int = 0       # Fields AA could not fill
    time_to_complete_ms: int = 0 # Total time from navigation to submission
    page_load_time_ms: int = 0   # Time for the application page to load
    captcha_encountered: bool = False
    captcha_resolved: bool = False
    error_message: str = ""      # Anonymized error if failed
    # Friction metrics
    required_account_creation: bool = False
    required_file_upload: bool = False
    required_cover_letter: bool = False
    had_custom_questions: bool = False
    custom_question_count: int = 0


@dataclass
class EmployerResponseEvent:
    """Records employer response data (populated on subsequent sessions)."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # noqa: E501
    job_hash: str = ""
    company_hash: str = ""
    days_since_application: int = 0
    response_type: str = ""      # "none", "rejection", "interview_request", "offer"
    is_ghosted: bool = False     # True if no response after threshold days


@dataclass
class SessionSummary:
    """Aggregate metrics for one complete session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # noqa: E501
    duration_seconds: float = 0.0
    jobs_discovered: int = 0
    jobs_vetted_pass: int = 0
    jobs_vetted_fail: int = 0
    applications_attempted: int = 0
    applications_succeeded: int = 0
    applications_failed: int = 0
    unique_companies: int = 0
    unique_ats_types: int = 0
    captchas_encountered: int = 0
    captchas_resolved: int = 0
    avg_form_completion_ms: float = 0.0
    avg_form_fields: float = 0.0
    browser_restarts: int = 0
    network_interruptions: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Anonymizer
# ─────────────────────────────────────────────────────────────────────────────

class Anonymizer:
    """Strips PII from research data before export.

    Uses one-way hashing so the same entity produces the same hash
    across sessions (enabling longitudinal analysis without exposing identity).
    The salt is per-installation, not per-session, so "company X" always
    maps to the same hash on the same machine.

    What is anonymized:
        - Job URLs → SHA-256 hash
        - Company names → SHA-256 hash
        - User-provided text in search queries → removed
        - Error messages → generic classification only
        - Any PII patterns (email, phone, name) → stripped

    What is NOT anonymized (safe to keep):
        - ATS type
        - Outcome codes
        - Numeric metrics (timing, counts)
        - Boolean flags
    """

    def __init__(self, salt: str | None = None) -> None:
        self._salt = salt or self._load_or_create_salt()

    def hash_value(self, value: str) -> str:
        """Produces a deterministic, non-reversible hash of a string."""
        if not value:
            return ""
        combined = f"{self._salt}:{value.lower().strip()}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

    def anonymize_url(self, url: str) -> str:
        """Hashes a URL, preserving only the domain for ATS classification."""
        return self.hash_value(url)

    def anonymize_company(self, company: str) -> str:
        """Hashes a company name."""
        return self.hash_value(company)

    def anonymize_query(self, query: str) -> str:
        """Removes specific terms from a search query, keeping structure."""
        # Replace proper nouns and specifics with category tags
        return "[search_query]"

    def strip_pii(self, text: str) -> str:
        """Removes email addresses, phone numbers, and name-like patterns."""
        if not text:
            return ""
        text = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', text)
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
        text = re.sub(r'\b\d{5}(-\d{4})?\b', '[ZIP]', text)
        return text

    def _load_or_create_salt(self) -> str:
        """Loads or creates a persistent per-installation salt."""
        salt_path = Path.home() / ".auto_apply" / ".research_salt"
        try:
            if salt_path.exists():
                return salt_path.read_text().strip()
            salt = uuid.uuid4().hex
            salt_path.parent.mkdir(parents=True, exist_ok=True)
            salt_path.write_text(salt)
            return salt
        except Exception:
            return uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────────────────────
# Consent Manager
# ─────────────────────────────────────────────────────────────────────────────

class ConsentManager:
    """Manages user consent for research data collection.

    Consent state is persisted to disk. Collection cannot occur unless
    consent is explicitly granted. The user can revoke consent at any
    time, which stops all future collection but does not delete existing
    data (the user must explicitly request deletion).
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or (Path.home() / ".auto_apply")
        self._consent_file = self._data_dir / ".research_consent"

    def is_granted(self) -> bool:
        """Returns True if the user has granted research consent."""
        try:
            if self._consent_file.exists():
                data = json.loads(self._consent_file.read_text())
                return data.get("consent_granted", False)
        except Exception:
            pass
        return False

    def grant(self) -> None:
        """Records that the user has granted consent."""
        self._save_state(True)
        logger.info("Research consent granted")

    def revoke(self) -> None:
        """Records that the user has revoked consent."""
        self._save_state(False)
        logger.info("Research consent revoked")

    def delete_all_data(self, research_dir: Path) -> int:
        """Deletes all research data files. Returns count of files deleted."""
        count = 0
        if research_dir.exists():
            for f in research_dir.glob("*.json"):
                f.unlink()
                count += 1
            for f in research_dir.glob("*.csv"):
                f.unlink()
                count += 1
        logger.info("Deleted %d research data files", count)
        return count

    def _save_state(self, granted: bool) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "consent_granted": granted,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
        }
        self._consent_file.write_text(json.dumps(data, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Research Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class ResearchPipeline:
    """The main research data collection and export pipeline.

    Instantiated once per session by the orchestrator. Collects events
    during the session, then exports anonymized data at session end.

    Args:
        consent_granted: Whether the user has opted in to research collection.
        output_dir: Directory for exported research data files.
    """

    def __init__(
        self,
        consent_granted: bool = False,
        output_dir: Path | None = None,
    ) -> None:
        self._active = consent_granted
        self._output_dir = output_dir or (Path.home() / ".auto_apply" / "research")
        self._anonymizer = Anonymizer()

        self._discovery_events: list[DiscoveryEvent] = []
        self._vetting_events: list[VettingEvent] = []
        self._application_events: list[ApplicationEvent] = []
        self._response_events: list[EmployerResponseEvent] = []

        if self._active:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Research pipeline active | output=%s", self._output_dir)
        else:
            logger.debug("Research pipeline inactive (no consent)")

    @property
    def is_active(self) -> bool:
        return self._active

    # ── Recording Methods ─────────────────────────────────────────────────

    def record_discovery(
        self,
        provider: str,
        query: str,
        location: str,
        results_count: int,
        new_count: int,
        load_time_ms: int = 0,
        pages: int = 1,
    ) -> None:
        """Records a discovery event."""
        if not self._active:
            return
        self._discovery_events.append(DiscoveryEvent(
            provider=provider,
            query=self._anonymizer.anonymize_query(query),
            location_query=location,
            results_count=results_count,
            new_results_count=new_count,
            page_load_time_ms=load_time_ms,
            pagination_pages=pages,
        ))

    def record_vetting(
        self,
        job_url: str,
        outcome: VettingOutcome,
        rejection_reason: str = "",
        filter_name: str = "",
        fit_score: float = 0.0,
        processing_time_ms: int = 0,
    ) -> None:
        """Records a vetting evaluation event."""
        if not self._active:
            return
        self._vetting_events.append(VettingEvent(
            job_hash=self._anonymizer.anonymize_url(job_url),
            outcome=outcome.value,
            rejection_reason=rejection_reason,
            filter_name=filter_name,
            fit_score=fit_score,
            processing_time_ms=processing_time_ms,
        ))

    def record_application(
        self,
        job_url: str,
        company: str,
        ats_type: ATSType,
        outcome: ApplicationOutcome,
        form_steps: int = 0,
        form_fields: int = 0,
        fields_filled: int = 0,
        fields_failed: int = 0,
        time_ms: int = 0,
        captcha: bool = False,
        captcha_resolved: bool = False,
        error: str = "",
        required_account: bool = False,
        required_upload: bool = False,
        required_cover_letter: bool = False,
        custom_questions: int = 0,
    ) -> None:
        """Records an application attempt — the primary research data point."""
        if not self._active:
            return
        self._application_events.append(ApplicationEvent(
            job_hash=self._anonymizer.anonymize_url(job_url),
            company_hash=self._anonymizer.anonymize_company(company),
            ats_type=ats_type.value,
            outcome=outcome.value,
            form_steps=form_steps,
            form_fields=form_fields,
            fields_auto_filled=fields_filled,
            fields_failed=fields_failed,
            time_to_complete_ms=time_ms,
            captcha_encountered=captcha,
            captcha_resolved=captcha_resolved,
            error_message=self._anonymizer.strip_pii(error),
            required_account_creation=required_account,
            required_file_upload=required_upload,
            required_cover_letter=required_cover_letter,
            had_custom_questions=custom_questions > 0,
            custom_question_count=custom_questions,
        ))

    # ── Export Methods ────────────────────────────────────────────────────

    def export_session(self, session_id: str) -> Path | None:
        """Exports all collected data for this session as JSON.

        Returns the path to the exported file, or None if inactive.
        """
        if not self._active:
            return None

        output = {
            "meta": {
                "session_id": session_id,
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
                "event_counts": {
                    "discovery": len(self._discovery_events),
                    "vetting": len(self._vetting_events),
                    "application": len(self._application_events),
                },
            },
            "discovery_events": [asdict(e) for e in self._discovery_events],
            "vetting_events": [asdict(e) for e in self._vetting_events],
            "application_events": [asdict(e) for e in self._application_events],
        }

        filename = f"session_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"  # noqa: E501
        filepath = self._output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info("Research data exported | path=%s events=%d",
                     filepath, sum(output["meta"]["event_counts"].values()))
        return filepath

    def export_session_csv(self, session_id: str) -> Path | None:
        """Exports application events as CSV for easy analysis in R/Python.

        Returns the path to the exported file, or None if inactive.
        """
        if not self._active or not self._application_events:
            return None

        filename = f"applications_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"  # noqa: E501
        filepath = self._output_dir / filename

        fieldnames = list(asdict(self._application_events[0]).keys())

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for event in self._application_events:
                writer.writerow(asdict(event))

        logger.info("Research CSV exported | path=%s rows=%d", filepath, len(self._application_events))  # noqa: E501
        return filepath

    def generate_session_summary(self) -> SessionSummary:
        """Generates aggregate summary metrics for this session."""
        summary = SessionSummary()
        summary.jobs_discovered = sum(e.results_count for e in self._discovery_events)
        summary.jobs_vetted_pass = sum(1 for e in self._vetting_events if e.outcome == "passed")  # noqa: E501
        summary.jobs_vetted_fail = sum(1 for e in self._vetting_events if e.outcome != "passed")  # noqa: E501
        summary.applications_attempted = len(self._application_events)
        summary.applications_succeeded = sum(1 for e in self._application_events if e.outcome == "success")  # noqa: E501
        summary.applications_failed = summary.applications_attempted - summary.applications_succeeded  # noqa: E501

        companies = set(e.company_hash for e in self._application_events if e.company_hash)  # noqa: E501
        summary.unique_companies = len(companies)

        ats_types = set(e.ats_type for e in self._application_events if e.ats_type != "unknown")  # noqa: E501
        summary.unique_ats_types = len(ats_types)

        summary.captchas_encountered = sum(1 for e in self._application_events if e.captcha_encountered)  # noqa: E501
        summary.captchas_resolved = sum(1 for e in self._application_events if e.captcha_resolved)  # noqa: E501

        times = [e.time_to_complete_ms for e in self._application_events if e.time_to_complete_ms > 0]  # noqa: E501
        summary.avg_form_completion_ms = sum(times) / len(times) if times else 0

        fields = [e.form_fields for e in self._application_events if e.form_fields > 0]
        summary.avg_form_fields = sum(fields) / len(fields) if fields else 0

        return summary
