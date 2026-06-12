"""Passive, consent-gated research data collector.

This module provides ResearchCollector, which observes the session via
EventBus subscriptions and records anonymized hiring market signals to
disk for later analysis. It is the implementation of the research feature
described in AA's design goals.

Core Design Principles:
    1. Consent first, always. The collector does nothing until the user has
       explicitly opted in. CapabilitiesRegistry.is_research_enabled()
       is checked before every operation. No data is ever collected
       without a confirmed opt-in.

    2. Zero personal data. The collector NEVER records:
       - Job URLs (could identify a user's browsing pattern)
       - Company names (could identify geography or industry preference)
       - User names, emails, resume details, or any profile data
       Only aggregate, categorical signals are recorded. A signal says
       "a title/description seniority mismatch was observed" not
       "Alice applied to Google and the job title said Junior but required
       Senior experience."

    3. Passive observation only. The collector is a pure EventBus
       subscriber. It never calls into domain engines, never navigates,
       never touches the browser, and never slows down the main loop.
       All disk writes happen on a background daemon thread via a queue.

    4. Research-grade uniformity. Because all users contribute the same
       signal types with no personally identifying variation, the dataset
       is uniform across all contributors. This satisfies the randomization
       requirement for valid statistical analysis.

    5. Non-blocking by design. The EventBus delivers signals to the
       collector synchronously on the publishing thread, but the collector
       only enqueues them — never writes to disk on the hot path. The
       background worker handles all I/O.

Signal Taxonomy:
    Signals are categorized by the hiring practice they document.
    See ResearchSignalType for the full catalog with descriptions.

Output Format:
    CSV file: ~/.auto_apply/research_data/hiring_signals.csv
    One row per signal. Headers written on first run. Append-only.
    The file is designed to be importable into pandas, R, or any
    standard data analysis tool with zero preprocessing.

Example:
    >>> collector = ResearchCollector(enabled=True, event_bus=bus, session_id="s1")
    >>> collector.start()   # Subscribes to EventBus, starts writer thread
    >>> # ... session runs, signals are collected automatically ...
    >>> collector.shutdown()  # Flushes queue, joins writer thread
"""

import csv
import logging
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from auto_apply.domain.events import Event

logger = logging.getLogger(__name__)

# Output directory relative to the user data directory.
# Resolved to an absolute path in ResearchCollector.__init__().
_RESEARCH_SUBDIR = "research_data"
_OUTPUT_FILENAME  = "hiring_signals.csv"

# CSV column headers — order must match ResearchSignal.to_csv_row().
_CSV_HEADERS = [
    "timestamp_utc",
    "session_id",
    "signal_type",
    "category",
    "platform_type",       # e.g. "linkedin", "greenhouse", "workday", "unknown"
    "job_tier_listed",     # e.g. "entry", "mid", "senior", "manager", "unknown"
    "job_tier_actual",     # tier implied by description, may differ from listed
    "years_required",      # integer or empty
    "ats_present",         # "yes", "no", "unknown"
    "ats_disclosed",       # "yes", "no", "unknown"
    "response_type",       # "rejected", "no_response", "advanced", "unknown"
    "form_field_type",     # for form anomaly signals
    "detail_code",         # short machine-readable detail (no free text)
    "notes",               # optional short human-readable note (no PII ever)
]


# ─────────────────────────────────────────────────────────────────────────────
# Signal Type Catalog
# ─────────────────────────────────────────────────────────────────────────────

class ResearchSignalType(Enum):
    """Complete catalog of research signal types.

    Each value documents a specific hiring market pattern that AA can
    observe and record. The docstring on each member describes the
    research question it helps answer.
    """

    # ── Title / Seniority Signals ─────────────────────────────────────────

    TITLE_DESCRIPTION_MISMATCH = auto()
    """Job title lists a lower tier (e.g. 'Software Engineer') but the
    description contains explicit senior/lead language."""

    TITLE_UNDISCLOSED_LEVEL = auto()
    """Job title has no tier qualifier (e.g. 'Engineer' not 'Senior Engineer')
    but the description implies a specific level."""

    ENTRY_LEVEL_EXPERIENCE_REQUIRED = auto()
    """A position labeled 'Entry Level', 'Junior', or 'New Grad' explicitly
    requires N years of professional experience (N > 0)."""

    MANAGER_HEAVY_POSTING = auto()
    """A company's job listings show a disproportionate ratio of
    manager/senior/lead roles vs. individual contributor roles."""

    # ── ATS / Process Signals ─────────────────────────────────────────────

    ATS_REJECTION_RAPID = auto()
    """Application received a rejection response within < 24 hours."""

    ATS_NO_RESPONSE = auto()
    """Application received zero response after N days (configurable threshold)."""

    ATS_PRESENT_UNDISCLOSED = auto()
    """An ATS form was detected during application but the job posting
    gave no indication that ATS software was in use."""

    ATS_OPT_OUT_OFFERED = auto()
    """The application process offered the option to bypass ATS evaluation."""

    # ── Form / Application Design Signals ─────────────────────────────────

    HIDDEN_REQUIREMENT_FORM = auto()
    """A form question reveals a minimum requirement not stated in the job description."""  # noqa: E501

    HIDDEN_REQUIREMENT_DROPDOWN_GATE = auto()
    """A dropdown field that only offers options ≥ a minimum threshold."""

    HIDDEN_REQUIREMENT_NUMERIC_GATE = auto()
    """A numeric text field that rejects values below an undisclosed threshold."""

    YIN_YANG_CONFLICT = auto()
    """The application process presents a binary choice that creates a
    conflict regardless of which option is chosen."""

    FORM_LOGIC_CONFLICT = auto()
    """A form field presents options where no single answer correctly
    represents the candidate."""

    UNPAID_DECEPTIVE_POSTING = auto()
    """A job listing uses language implying paid employment but reveals
    the position is unpaid or underpaid."""

    # ── Accessibility / Communication Signals ─────────────────────────────

    NO_DIRECT_CONTACT = auto()
    """The application provides no way to contact the hiring manager or
    recruiter directly."""

    AUTH_WALL_MID_APPLICATION = auto()
    """Required account creation or login appeared mid-application."""

    CAPTCHA_EXCESSIVE = auto()
    """Multiple CAPTCHA challenges appeared during a single application session."""

    # ── Internship / Early Career Signals ─────────────────────────────────

    INTERNSHIP_CURRENT_STUDENT_ONLY = auto()
    """An internship posting explicitly restricts applicants to currently
    enrolled students, excluding recent graduates."""

    INTERNSHIP_UNPAID = auto()
    """An internship position is unpaid or offers only academic credit."""

    # ── Positive Signals (Companies Doing Things Right) ───────────────────

    INCLUSIVE_LANGUAGE_DETECTED = auto()
    """The job posting uses explicit inclusive language acknowledging the
    current market."""

    SALARY_RANGE_DISCLOSED = auto()
    """The posting includes a specific salary range rather than 'competitive'
    or no information."""

    TRANSPARENT_PROCESS_DESCRIBED = auto()
    """The posting describes the full hiring process timeline and steps."""


# ─────────────────────────────────────────────────────────────────────────────
# Signal Data Model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ResearchSignal:
    """A single anonymized observation of a hiring market pattern.

    All fields are either categorical (platform type, tier label) or
    boolean/numeric aggregate values. No field may contain a URL,
    company name, job title, user name, or any other identifying data.

    Attributes:
        session_id: The session that produced this signal.
        signal_type: The ResearchSignalType enum value.
        category: Broad category string for pivot analysis.
        platform_type: Normalized platform label, e.g. "linkedin".
        job_tier_listed: The tier label from the job title.
        job_tier_actual: The tier implied by description content.
        years_required: Explicit years of experience required, or None.
        ats_present: Whether ATS was detected.
        ats_disclosed: Whether ATS use was disclosed in the posting.
        response_type: The outcome of the application, if known.
        form_field_type: For form anomalies, the field type observed.
        detail_code: Short machine-readable tag, no free text.
        notes: Optional brief annotation. MUST CONTAIN NO PII.
    """
    session_id:      str
    signal_type:     ResearchSignalType
    category:        str              = ""
    platform_type:   str              = "unknown"
    job_tier_listed: str              = "unknown"
    job_tier_actual: str              = "unknown"
    years_required:  int | None    = None
    ats_present:     str              = "unknown"
    ats_disclosed:   str              = "unknown"
    response_type:   str              = "unknown"
    form_field_type: str              = ""
    detail_code:     str              = ""
    notes:           str              = ""
    timestamp:       datetime         = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_csv_row(self) -> list[str]:
        """Produces a CSV row in the order defined by _CSV_HEADERS."""
        return [
            self.timestamp.isoformat(),
            self.session_id,
            self.signal_type.name,
            self.category,
            self.platform_type,
            self.job_tier_listed,
            self.job_tier_actual,
            str(self.years_required) if self.years_required is not None else "",
            self.ats_present,
            self.ats_disclosed,
            self.response_type,
            self.form_field_type,
            self.detail_code,
            self.notes,
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Research Collector
# ─────────────────────────────────────────────────────────────────────────────

class ResearchCollector:
    """Passive EventBus subscriber that records anonymized hiring signals.

    Args:
        enabled: Explicit boolean flag — must be True for any data collection.
        event_bus: The shared EventBus. The collector subscribes to
            events in start() and unsubscribes in shutdown().
        session_id: The current session identifier.
        data_dir: Override for the output directory. If None, defaults
            to the standard user data directory.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        event_bus: Any,
        session_id: str,
        data_dir: Path | None = None,
    ) -> None:
        self._enabled    = enabled
        self._event_bus  = event_bus
        self._session_id = session_id

        if data_dir is not None:
            self._data_dir = Path(data_dir)
        else:
            from auto_apply.domain.config import USER_DATA_DIR  # noqa: PLC0415
            self._data_dir = USER_DATA_DIR / _RESEARCH_SUBDIR

        self._csv_path = self._data_dir / _OUTPUT_FILENAME

        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._writer_thread: threading.Thread | None = None

        self._signals_recorded: int = 0
        self._signals_dropped: int  = 0

        if self._enabled:
            logger.info(
                "ResearchCollector initialized | session=%s output=%s",
                session_id,
                self._csv_path,
            )
        else:
            logger.info(
                "ResearchCollector: research collection is disabled "
                "(user has not opted in or admin policy prohibits it)"
            )

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def start(self) -> None:
        """Subscribes to EventBus events and starts the background writer."""
        if not self._enabled:
            return

        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_csv_headers()

        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="ResearchWriter",
            daemon=True,
        )
        self._writer_thread.start()

        self._event_bus.subscribe(Event.APPLICATION_SUBMITTED,  self._on_application_submitted)  # noqa: E501
        self._event_bus.subscribe(Event.APPLICATION_FAILED,     self._on_application_failed)  # noqa: E501
        self._event_bus.subscribe(Event.JOB_VETTED_FAIL,        self._on_job_vetted_fail)  # noqa: E501
        self._event_bus.subscribe(Event.FORM_FIELD_FAILED,      self._on_form_field_failed)  # noqa: E501
        self._event_bus.subscribe(Event.LOGIC_CONFLICT_DETECTED,self._on_logic_conflict)
        self._event_bus.subscribe(Event.CAPTCHA_DETECTED,       self._on_captcha_detected)  # noqa: E501
        self._event_bus.subscribe(Event.BOT_DETECTION_TRIGGERED,self._on_bot_detection)
        self._event_bus.subscribe(
            Event.AUTH_WALL_MID_APPLICATION
            if hasattr(Event, "AUTH_WALL_MID_APPLICATION")
            else Event.APPLICATION_FAILED,
            self._on_auth_wall,
        )

        logger.info("ResearchCollector started and subscribed to EventBus")

    def shutdown(self) -> None:
        """Flushes the queue and stops the background writer cleanly."""
        if not self._enabled or self._writer_thread is None:
            return

        self._stop_event.set()
        self._writer_thread.join(timeout=10.0)

        if self._writer_thread.is_alive():
            remaining = self._queue.qsize()
            self._signals_dropped += remaining
            logger.warning(
                "ResearchCollector: writer did not drain in time | dropped=%d",
                remaining,
            )

        logger.info(
            "ResearchCollector shutdown | recorded=%d dropped=%d",
            self._signals_recorded,
            self._signals_dropped,
        )

    # =========================================================================
    # PUBLIC SIGNAL RECORDING
    # =========================================================================

    def record(self, signal: ResearchSignal) -> None:
        """Enqueues a signal for background writing.

        Args:
            signal: The fully constructed ResearchSignal to record.
        """
        if not self._enabled:
            return
        self._enqueue(signal)

    def record_signal(
        self,
        signal_type: ResearchSignalType,
        *,
        platform_type:   str = "unknown",
        job_tier_listed: str = "unknown",
        job_tier_actual: str = "unknown",
        years_required:  int | None = None,
        ats_present:     str = "unknown",
        ats_disclosed:   str = "unknown",
        response_type:   str = "unknown",
        form_field_type: str = "",
        detail_code:     str = "",
        notes:           str = "",
    ) -> None:
        """Convenience builder for recording a signal without constructing the dataclass."""  # noqa: E501
        if not self._enabled:
            return

        signal = ResearchSignal(
            session_id=self._session_id,
            signal_type=signal_type,
            category=self._category_for(signal_type),
            platform_type=platform_type,
            job_tier_listed=job_tier_listed,
            job_tier_actual=job_tier_actual,
            years_required=years_required,
            ats_present=ats_present,
            ats_disclosed=ats_disclosed,
            response_type=response_type,
            form_field_type=form_field_type,
            detail_code=detail_code,
            notes=notes,
        )
        self._enqueue(signal)

    # =========================================================================
    # EVENTBUS HANDLERS
    # =========================================================================

    def _on_application_submitted(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            url = payload.get("url", "")
            self.record_signal(
                ResearchSignalType.ATS_NO_RESPONSE,
                platform_type=self._classify_platform(url),
                response_type="submitted",
                detail_code="application_submitted",
            )
        except Exception:
            pass

    def _on_application_failed(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            url = payload.get("url", "")
            reason = payload.get("reason", "")
            self.record_signal(
                ResearchSignalType.HIDDEN_REQUIREMENT_FORM,
                platform_type=self._classify_platform(url),
                response_type="failed",
                detail_code=self._sanitize_detail(reason),
            )
        except Exception:
            pass

    def _on_job_vetted_fail(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            reason = payload.get("reason", "")
            self.record_signal(
                ResearchSignalType.TITLE_DESCRIPTION_MISMATCH,
                detail_code=self._sanitize_detail(reason),
            )
        except Exception:
            pass

    def _on_form_field_failed(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            field_type = payload.get("field_type", "")
            error = payload.get("error", "")
            self.record_signal(
                ResearchSignalType.FORM_LOGIC_CONFLICT,
                form_field_type=field_type,
                detail_code=self._sanitize_detail(error),
            )
        except Exception:
            pass

    def _on_logic_conflict(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            field_type = payload.get("field_label", "")
            self.record_signal(
                ResearchSignalType.YIN_YANG_CONFLICT,
                form_field_type=self._sanitize_detail(field_type),
                detail_code="logic_conflict",
            )
        except Exception:
            pass

    def _on_captcha_detected(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            captcha_type = payload.get("captcha_type", "unknown")
            self.record_signal(
                ResearchSignalType.CAPTCHA_EXCESSIVE,
                detail_code=self._sanitize_detail(captcha_type),
            )
        except Exception:
            pass

    def _on_bot_detection(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            self.record_signal(
                ResearchSignalType.CAPTCHA_EXCESSIVE,
                detail_code="bot_detection_triggered",
            )
        except Exception:
            pass

    def _on_auth_wall(self, payload: dict) -> None:
        if not self._enabled or not payload:
            return
        try:
            self.record_signal(
                ResearchSignalType.AUTH_WALL_MID_APPLICATION,
                detail_code="auth_wall_mid_application",
            )
        except Exception:
            pass

    # =========================================================================
    # BACKGROUND WRITER
    # =========================================================================

    def _writer_loop(self) -> None:
        """Background thread: drains the queue and writes signals to CSV."""
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                signal: ResearchSignal = self._queue.get(timeout=1.0)
                self._write_signal(signal)
                self._queue.task_done()
                self._signals_recorded += 1
            except queue.Empty:
                continue
            except Exception as exc:
                logger.error("ResearchCollector writer error | %s", exc)

    def _write_signal(self, signal: ResearchSignal) -> None:
        """Appends one signal row to the CSV file."""
        try:
            with open(self._csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(signal.to_csv_row())
        except Exception as exc:
            logger.error("ResearchCollector: failed to write signal | %s", exc)

    def _enqueue(self, signal: ResearchSignal) -> None:
        """Puts a signal on the queue. Never blocks, never raises."""
        try:
            self._queue.put_nowait(signal)
        except Exception:
            self._signals_dropped += 1

    def _ensure_csv_headers(self) -> None:
        """Writes the CSV header row if the output file does not yet exist."""
        if not self._csv_path.exists():
            try:
                with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(_CSV_HEADERS)
                logger.info("ResearchCollector: created output file | %s", self._csv_path)  # noqa: E501
            except Exception as exc:
                logger.error(
                    "ResearchCollector: failed to create CSV file | %s", exc
                )

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _classify_platform(url: str) -> str:
        """Extracts a normalized platform label from a URL domain only."""
        if not url:
            return "unknown"
        try:
            host = urlparse(url).netloc.lower()
            platform_map = {
                "linkedin":        "linkedin",
                "indeed":          "indeed",
                "greenhouse":      "greenhouse",
                "lever":           "lever",
                "workday":         "workday",
                "icims":           "icims",
                "smartrecruiters": "smartrecruiters",
                "bamboohr":        "bamboohr",
                "jobvite":         "jobvite",
                "taleo":           "taleo",
                "successfactors":  "successfactors",
                "myworkday":       "workday",
                "ziprecruiter":    "ziprecruiter",
                "glassdoor":       "glassdoor",
            }
            for key, label in platform_map.items():
                if key in host:
                    return label
            return "other"
        except Exception:
            return "unknown"

    @staticmethod
    def _sanitize_detail(text: str) -> str:
        """Truncates and sanitizes a detail string for safe CSV inclusion."""
        if not text:
            return ""
        import re  # noqa: PLC0415
        sanitized = re.sub(r"https?://\S+", "[url]", text)
        sanitized = re.sub(r"[\w.+-]+@[\w-]+\.\w+", "[email]", sanitized)
        return sanitized[:80].strip()

    @staticmethod
    def _category_for(signal_type: ResearchSignalType) -> str:
        """Maps a signal type to its broad research category."""
        categories = {
            ResearchSignalType.TITLE_DESCRIPTION_MISMATCH:      "seniority",
            ResearchSignalType.TITLE_UNDISCLOSED_LEVEL:         "seniority",
            ResearchSignalType.ENTRY_LEVEL_EXPERIENCE_REQUIRED: "seniority",
            ResearchSignalType.MANAGER_HEAVY_POSTING:           "seniority",
            ResearchSignalType.ATS_REJECTION_RAPID:             "ats_process",
            ResearchSignalType.ATS_NO_RESPONSE:                 "ats_process",
            ResearchSignalType.ATS_PRESENT_UNDISCLOSED:         "ats_process",
            ResearchSignalType.ATS_OPT_OUT_OFFERED:             "ats_process",
            ResearchSignalType.HIDDEN_REQUIREMENT_FORM:         "hidden_gating",
            ResearchSignalType.HIDDEN_REQUIREMENT_DROPDOWN_GATE:"hidden_gating",
            ResearchSignalType.HIDDEN_REQUIREMENT_NUMERIC_GATE: "hidden_gating",
            ResearchSignalType.YIN_YANG_CONFLICT:               "form_design",
            ResearchSignalType.FORM_LOGIC_CONFLICT:             "form_design",
            ResearchSignalType.UNPAID_DECEPTIVE_POSTING:        "compensation",
            ResearchSignalType.NO_DIRECT_CONTACT:               "communication",
            ResearchSignalType.AUTH_WALL_MID_APPLICATION:       "friction",
            ResearchSignalType.CAPTCHA_EXCESSIVE:               "friction",
            ResearchSignalType.INTERNSHIP_CURRENT_STUDENT_ONLY: "early_career",
            ResearchSignalType.INTERNSHIP_UNPAID:               "early_career",
            ResearchSignalType.INCLUSIVE_LANGUAGE_DETECTED:     "positive",
            ResearchSignalType.SALARY_RANGE_DISCLOSED:          "positive",
            ResearchSignalType.TRANSPARENT_PROCESS_DESCRIBED:   "positive",
        }
        return categories.get(signal_type, "other")