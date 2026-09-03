"""
ResearchSignalAggregator — integrates signal detectors with the AA pipeline.

This adapter:
1. Subscribes to relevant EventBus events (JOB_DISCOVERED, FORM_OBSERVED, etc.)
2. Builds DetectionContext from event payloads
3. Runs all detectors via run_all_detectors()
4. Persists resulting ResearchSignal objects to SQLite
5. Publishes aggregate statistics on a configurable interval
6. Periodically computes corpus‑level macro‑signals (LM‑01, LM‑02, LM‑03)

Architecture rule: This class is an adapter — it may import from infrastructure.
It must NEVER be imported by domain or application layers.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.ports.research_port import (
    ApplicationOutcomeObservation,
    DiscoveryObservation,
    FormObservation,
    JobPostingObservation,
    ResearchObserverPort,
)
from auto_apply.domain.services.job_lifecycle_tracker import (
    JobLifecycleRecord,
    cross_platform_date_spread,
    days_live,
    update_lifecycle,
)
from auto_apply.domain.services.research_statistics import percentile
from auto_apply.domain.services.signal_detectors import (
    DetectionContext,
    ResearchSignal,
    run_all_detectors,
)

logger = logging.getLogger(__name__)

# ── SQLite schema (version 2 + provenance columns) ───────────────────────────
_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS research_signals (
    signal_id       TEXT PRIMARY KEY,
    signal_type     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence      REAL NOT NULL,
    evidence_text   TEXT,
    platform        TEXT,
    jurisdiction    TEXT,
    company_id      TEXT,
    job_category    TEXT,
    detected_date   TEXT NOT NULL,
    schema_version  INTEGER DEFAULT 2,
    consent_version TEXT,
    posting_hash    TEXT,
    content_hash    TEXT,
    provenance_signature TEXT
);

CREATE TABLE IF NOT EXISTS job_lifecycles (
    job_fingerprint          TEXT NOT NULL,
    platform                 TEXT NOT NULL,
    first_seen               TEXT NOT NULL,
    last_seen                TEXT NOT NULL,
    times_seen               INTEGER DEFAULT 1,
    times_reposted           INTEGER DEFAULT 0,
    applied_to               INTEGER DEFAULT 0,
    response_received        INTEGER DEFAULT 0,
    response_date            TEXT,
    company_id               TEXT,
    PRIMARY KEY (job_fingerprint, platform)
);

CREATE TABLE IF NOT EXISTS salary_observations (
    obs_id               TEXT PRIMARY KEY,
    salary_min           INTEGER,
    salary_max           INTEGER,
    salary_type          TEXT DEFAULT 'annual',
    currency             TEXT DEFAULT 'USD',
    role_title_normalized TEXT,
    experience_years_min INTEGER,
    experience_years_max INTEGER,
    education_required   TEXT,
    location_metro       TEXT,
    jurisdiction         TEXT,
    platform             TEXT,
    industry_sic         TEXT,
    posted_date          TEXT,
    schema_version       INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS form_observations (
    form_id                    TEXT PRIMARY KEY,
    job_fingerprint            TEXT,
    platform                   TEXT NOT NULL,
    company_id                 TEXT,
    total_fields               INTEGER,
    required_fields            INTEGER,
    optional_fields            INTEGER,
    essay_fields               INTEGER,
    file_upload_fields         INTEGER,
    knockout_questions         INTEGER,
    wcag_score                 TEXT,
    wcag_violations            TEXT,
    salary_history_requested   INTEGER DEFAULT 0,
    jurisdiction               TEXT,
    estimated_completion_minutes INTEGER,
    observed_date              TEXT NOT NULL,
    schema_version             INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS application_outcomes (
    outcome_id           TEXT PRIMARY KEY,
    platform             TEXT NOT NULL,
    company_id           TEXT,
    submitted_date       TEXT NOT NULL,
    acknowledgment_received INTEGER DEFAULT 0,
    acknowledgment_date  TEXT,
    schema_version       INTEGER DEFAULT 2
);

-- ── Provenance metadata table — stores the public key once per installation ──
CREATE TABLE IF NOT EXISTS research_provenance (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    public_key_hex    TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_type     ON research_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_severity ON research_signals(severity);
CREATE INDEX IF NOT EXISTS idx_signals_date     ON research_signals(detected_date);
CREATE INDEX IF NOT EXISTS idx_signals_company  ON research_signals(company_id);
CREATE INDEX IF NOT EXISTS idx_signals_posting  ON research_signals(posting_hash);
CREATE INDEX IF NOT EXISTS idx_lifecycles_fp    ON job_lifecycles(job_fingerprint);
CREATE INDEX IF NOT EXISTS idx_salary_role      ON salary_observations(role_title_normalized);
CREATE INDEX IF NOT EXISTS idx_outcomes_company ON application_outcomes(company_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_platform ON application_outcomes(platform);
"""


class ResearchSignalAggregator(ResearchObserverPort):
    """Daemon-thread adapter that persists research signals to SQLite.

    Implements domain.ports.research_port.ResearchObserverPort — this is
    the concrete implementation injected by composition_root.py into
    DiscoveryWorkflow, VettingWorkflow, and ApplicationsWorkflow when
    research consent is active. When consent is not active, composition_root
    injects NullResearchObserver instead, which workflows cannot distinguish
    from this class at the type level (structural typing via Protocol).

    Follows the queue-plus-daemon-thread pattern established by ResearchCollector.
    EventBus handlers and direct port calls enqueue work; the daemon thread
    does all I/O.

    Provenance: Every signal written to the database is signed with an
    Ed25519 key unique to this AA installation.  The public key is stored
    once in ``research_provenance`` so third-party verifiers can authenticate
    signals without the private key ever leaving the device.

    Macro‑signals (LM‑01, LM‑02, LM‑03) are computed inside the daemon
    flush loop every ``macro_signal_interval_seconds`` (default 3600 = once
    per hour).  They run against the accumulated corpus rather than a single
    DetectionContext, so they are placed here rather than in the per‑posting
    pipeline.

    Args:
        db_path: Path to the research SQLite database file.
        consent_version: The version of consent user has agreed to.
            If None, research is disabled even if called.
        flush_interval_seconds: How often the daemon thread flushes the queue.
        macro_signal_interval_seconds: How often corpus‑level macro‑signals
            are recomputed (default 3600 = hourly).
    """

    def __init__(
        self,
        db_path: Path,
        consent_version: str | None = None,
        flush_interval_seconds: float = 5.0,
        macro_signal_interval_seconds: float = 3600.0,
    ) -> None:
        self._db_path = db_path
        self._consent_version = consent_version
        self._flush_interval = flush_interval_seconds
        self._macro_signal_interval = macro_signal_interval_seconds
        self._queue: queue.Queue[ResearchSignal | None] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._enabled = consent_version is not None

        # ── Provenance — lazy‑init on first write ─────────────────────────
        self._signer: Any = None
        self._public_key_stored: bool = False

        # ── Macro‑signal tracking ─────────────────────────────────────────
        self._last_macro_ts: float = 0.0   # monotonic timestamp of last run

        # ── Discovery-surface observation counter (§4b) ──────────────────
        self._discovery_observation_count: int = 0

        if self._enabled:
            self._initialize_db()

    def _initialize_db(self) -> None:
        """Create tables if they don't exist."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._get_connection() as conn:
                conn.executescript(_SCHEMA_SQL)
            logger.info("ResearchSignalAggregator | DB initialized at %s", self._db_path)
        except Exception as exc:
            logger.error("ResearchSignalAggregator | DB init failed: %s", exc)
            self._enabled = False

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def start(self) -> None:
        """Start the background flush daemon."""
        if not self._enabled:
            return
        self._running = True
        self._last_macro_ts = time.monotonic()
        self._thread = threading.Thread(
            target=self._flush_loop,
            name="research-aggregator",
            daemon=True,
        )
        self._thread.start()
        logger.info("ResearchSignalAggregator | Started")

    def stop(self) -> None:
        """Signal the daemon to stop and flush remaining items."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._queue.put(None)  # Sentinel to unblock queue.get()
            self._thread.join(timeout=10.0)

    def submit_context(self, ctx: DetectionContext) -> None:
        """Run all detectors on a context and enqueue resulting signals.

        Safe to call from any thread (EventBus handler, provider thread, etc.).
        Detection is synchronous but fast (pure computation, no I/O).
        Persistence is async via the daemon thread.

        Args:
            ctx: Job posting context to analyze.
        """
        if not self._enabled:
            return
        try:
            signals = run_all_detectors(ctx)
            for signal in signals:
                self._queue.put_nowait(signal)
            if signals:
                logger.debug(
                    "ResearchSignalAggregator | %d signals detected for '%s'",
                    len(signals), ctx.job_title[:50],
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | Detection error: %s", exc)

    # ── ResearchObserverPort implementation ──────────────────────────────────
    # These three methods satisfy domain.ports.research_port.ResearchObserverPort.
    # Workflows depend only on that Protocol; composition_root.py injects this
    # class (or NullResearchObserver when consent is not active).

    @property
    def is_enabled(self) -> bool:
        """Whether research collection is currently active (consent given)."""
        return self._enabled

    def observe_job_posting(self, observation: JobPostingObservation) -> None:
        """Process a job posting observation: update lifecycle, build context, detect.

        This is the primary entry point from DiscoveryWorkflow/VettingWorkflow.
        It performs three steps, all read-only or queue-only (non-blocking):
          1. Look up / update the job's lifecycle record (GJ-02, GJ-03 inputs)
          2. Look up the salary corpus percentile for ST-03 (if salary present)
          3. Build a DetectionContext and run all detectors

        Args:
            observation: All available data about the posting.
        """
        if not self._enabled:
            return

        try:
            lifecycle_records: list[JobLifecycleRecord] = []
            updated_record: JobLifecycleRecord | None = None

            if observation.posting_hash:
                today = observation.first_seen_date or date.today()
                previous = self._load_lifecycle(
                    observation.posting_hash, observation.platform or "unknown"
                )
                updated_record = update_lifecycle(
                    previous,
                    job_fingerprint=observation.posting_hash,
                    platform=observation.platform or "unknown",
                    observation_date=today,
                )
                self._save_lifecycle(updated_record)
                lifecycle_records = self._load_all_lifecycles_for_fingerprint(
                    observation.posting_hash
                )

            n_platforms, all_first_seen = (
                cross_platform_date_spread(lifecycle_records)
                if lifecycle_records else (1, [])
            )

            p25, sample_size = (None, 0)
            if observation.salary_max or observation.salary_min:
                role_key = observation.job_title.lower().strip()
                p25, sample_size = self._compute_role_percentile(role_key, 25.0)

            ctx = DetectionContext(
                job_title=observation.job_title,
                job_description=observation.job_description,
                company_name=observation.company_name,
                location=observation.location,
                jurisdiction=observation.jurisdiction,
                salary_min=observation.salary_min,
                salary_max=observation.salary_max,
                platform=observation.platform,
                first_seen_date=updated_record.first_seen if updated_record else observation.first_seen_date,
                days_live=days_live(updated_record, date.today()) if updated_record else None,
                posting_hash=observation.posting_hash,
                times_seen_cross_platform=max(n_platforms, 1),
                previous_posting_dates=all_first_seen,
                application_url_is_generic=observation.application_url_is_generic,
                metro_area=observation.metro_area,
                company_linkedin_age_days=observation.company_linkedin_age_days,
                company_domain_age_days=observation.company_domain_age_days,
                company_has_web_presence=observation.company_has_web_presence,
                salary_corpus_p25_for_role=p25,
                salary_corpus_sample_size=sample_size,
            )
            self.submit_context(ctx)

            # Record salary observation for the corpus (feeds future ST-03 lookups)
            if observation.salary_min or observation.salary_max:
                self.record_salary_observation(
                    salary_min=observation.salary_min,
                    salary_max=observation.salary_max,
                    role_title=observation.job_title,
                    platform=observation.platform,
                    jurisdiction=observation.jurisdiction,
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | observe_job_posting error: %s", exc)

    def observe_form(self, observation: FormObservation) -> None:
        """Process an application form observation.

        Args:
            observation: All available data about the form.
        """
        if not self._enabled:
            return
        try:
            fs = observation.form_structure
            ctx = DetectionContext(
                job_title=observation.job_title,
                company_name=observation.company_name,
                jurisdiction=observation.jurisdiction,
                platform=observation.platform,
                posting_hash=observation.posting_hash,
                form_field_count=len(fs.fields) if fs.fields else observation.application_form_field_count,
                form_required_fields=sum(1 for f in fs.fields if f.is_required) if fs.fields else None,
                form_has_salary_history_field=fs.has_salary_history_field,
                form_wcag_violations=list(fs.wcag_violations),
                application_form_field_count=observation.application_form_field_count,
                knockout_thresholds=dict(observation.knockout_thresholds),
                estimated_completion_minutes=observation.estimated_completion_minutes,
            )
            self.submit_context(ctx)

            self.record_form_observation(
                platform=observation.platform,
                form_structure=fs,
                job_fingerprint=observation.posting_hash,
                jurisdiction=observation.jurisdiction,
                estimated_minutes=observation.estimated_completion_minutes,
            )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | observe_form error: %s", exc)

    def observe_application_outcome(
        self, observation: ApplicationOutcomeObservation
    ) -> None:
        """Record an application outcome for LM-02 black-hole tracking.

        Args:
            observation: Outcome data (platform, company, ack status).
        """
        if not self._enabled:
            return
        import uuid
        outcome_id = str(uuid.uuid4())
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO application_outcomes
                       (outcome_id, platform, company_id, submitted_date,
                        acknowledgment_received, acknowledgment_date, schema_version)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        outcome_id, observation.platform, observation.company_id,
                        observation.submitted_date.isoformat(),
                        int(observation.acknowledgment_received),
                        observation.acknowledgment_date.isoformat()
                        if observation.acknowledgment_date else None,
                        RESEARCH_SCHEMA_VERSION,
                    ),
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | observe_application_outcome error: %s", exc)

    def observe_discovery(self, observation: DiscoveryObservation) -> None:
        """Accept a discovery-surface observation (§4b).

        Persistence for discovery observations is deferred to the consumer
        batch that builds the detector side of the discovery taxonomy. For
        now each observation is logged and counted, so the record shape is
        validated against real harvests without shipping the exporter early.
        The observation carries no user data and no search URLs — it is
        logged verbatim at INFO for legibility.

        Args:
            observation: The discovery-surface record for one results page.
        """
        if not self._enabled:
            return
        try:
            self._discovery_observation_count += 1
            logger.info(
                "ResearchSignalAggregator | discovery observation #%d | "
                "provider=%s blocked=%s architecture=%s cards=%d resolved=%d "
                "multi_route=%d sponsored=%d",
                self._discovery_observation_count,
                observation.provider,
                observation.blocked,
                observation.architecture,
                observation.card_count,
                observation.resolved_count,
                observation.multi_route_count,
                observation.sponsored_card_count,
            )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | observe_discovery error: %s", exc)

    # ── Job lifecycle persistence (GJ-02, GJ-03) ─────────────────────────────

    def _load_lifecycle(
        self, job_fingerprint: str, platform: str
    ) -> JobLifecycleRecord | None:
        """Load the lifecycle record for (job_fingerprint, platform), if it exists."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    """SELECT * FROM job_lifecycles
                       WHERE job_fingerprint = ? AND platform = ?""",
                    (job_fingerprint, platform),
                ).fetchone()
            if row is None:
                return None
            return JobLifecycleRecord(
                job_fingerprint=row["job_fingerprint"],
                platform=row["platform"],
                first_seen=date.fromisoformat(row["first_seen"]),
                last_seen=date.fromisoformat(row["last_seen"]),
                times_seen=row["times_seen"],
                times_reposted=row["times_reposted"],
                applied_to=bool(row["applied_to"]),
                response_received=bool(row["response_received"]),
                response_date=date.fromisoformat(row["response_date"]) if row["response_date"] else None,
            )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | _load_lifecycle error: %s", exc)
            return None

    def _save_lifecycle(self, record: JobLifecycleRecord) -> None:
        """Upsert a lifecycle record."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO job_lifecycles
                       (job_fingerprint, platform, first_seen, last_seen,
                        times_seen, times_reposted, applied_to,
                        response_received, response_date, company_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(job_fingerprint, platform) DO UPDATE SET
                         last_seen=excluded.last_seen,
                         times_seen=excluded.times_seen,
                         times_reposted=excluded.times_reposted,
                         applied_to=excluded.applied_to,
                         response_received=excluded.response_received,
                         response_date=excluded.response_date""",
                    (
                        record.job_fingerprint, record.platform,
                        record.first_seen.isoformat(), record.last_seen.isoformat(),
                        record.times_seen, record.times_reposted,
                        int(record.applied_to), int(record.response_received),
                        record.response_date.isoformat() if record.response_date else None,
                        None,
                    ),
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | _save_lifecycle error: %s", exc)

    def _load_all_lifecycles_for_fingerprint(
        self, job_fingerprint: str
    ) -> list[JobLifecycleRecord]:
        """Load lifecycle records across ALL platforms for a given posting hash.

        Used for GJ-02 (cross-platform freshness laundering) — this is the
        only place a single posting_hash maps to multiple platform rows.
        """
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """SELECT * FROM job_lifecycles WHERE job_fingerprint = ?""",
                    (job_fingerprint,),
                ).fetchall()
            return [
                JobLifecycleRecord(
                    job_fingerprint=r["job_fingerprint"],
                    platform=r["platform"],
                    first_seen=date.fromisoformat(r["first_seen"]),
                    last_seen=date.fromisoformat(r["last_seen"]),
                    times_seen=r["times_seen"],
                    times_reposted=r["times_reposted"],
                    applied_to=bool(r["applied_to"]),
                    response_received=bool(r["response_received"]),
                    response_date=date.fromisoformat(r["response_date"]) if r["response_date"] else None,
                )
                for r in rows
            ]
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | _load_all_lifecycles error: %s", exc)
            return []

    # ── Salary corpus percentile (ST-03) ─────────────────────────────────────

    def _compute_role_percentile(
        self, role_title_normalized: str, p: float
    ) -> tuple[float | None, int]:
        """Compute the p-th percentile salary for a normalized role title.

        Args:
            role_title_normalized: Lowercased, stripped job title.
            p: Percentile to compute (e.g. 25.0 for ST-03's 25th percentile).

        Returns:
            Tuple of (percentile_value_or_None, sample_size). Returns
            (None, 0) if no salary data exists for this role.
        """
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """SELECT salary_max, salary_min FROM salary_observations
                       WHERE role_title_normalized = ?
                         AND (salary_max IS NOT NULL OR salary_min IS NOT NULL)""",
                    (role_title_normalized,),
                ).fetchall()
            values = [
                float(r["salary_max"] if r["salary_max"] is not None else r["salary_min"])
                for r in rows
            ]
            if not values:
                return None, 0
            return percentile(values, p), len(values)
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | _compute_role_percentile error: %s", exc)
            return None, 0

    def record_salary_observation(
        self,
        salary_min: int | None,
        salary_max: int | None,
        role_title: str,
        platform: str | None = None,
        jurisdiction: str | None = None,
        experience_min: int | None = None,
        experience_max: int | None = None,
    ) -> None:
        """Record a salary data point for market benchmarking.

        Args:
            salary_min: Minimum salary in USD/year.
            salary_max: Maximum salary in USD/year.
            role_title: Normalized job title.
            platform: Source platform.
            jurisdiction: US state/city code.
            experience_min: Min years experience required.
            experience_max: Max years experience required.
        """
        if not self._enabled or (salary_min is None and salary_max is None):
            return
        obs_id = hashlib.sha256(
            f"{role_title}{salary_min}{salary_max}{platform}{jurisdiction}".encode()
        ).hexdigest()[:16]
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO salary_observations
                       (obs_id, salary_min, salary_max, role_title_normalized,
                        platform, jurisdiction, experience_years_min,
                        experience_years_max, posted_date, schema_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (obs_id, salary_min, salary_max,
                     role_title.lower().strip(),
                     platform, jurisdiction,
                     experience_min, experience_max,
                     date.today().isoformat(),
                     RESEARCH_SCHEMA_VERSION),
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | Salary obs error: %s", exc)

    def record_form_observation(
        self,
        platform: str,
        form_structure,
        job_fingerprint: str | None = None,
        company_id: str | None = None,
        jurisdiction: str | None = None,
        estimated_minutes: int | None = None,
    ) -> None:
        """Record an ATS form complexity observation.

        Args:
            platform: ATS or job board identifier.
            form_structure: FormStructure from PageUnderstandingPort.
            job_fingerprint: Structural hash of the job posting.
            company_id: Anonymized company identifier.
            jurisdiction: US state/city code.
            estimated_minutes: Estimated completion time in minutes.
        """
        if not self._enabled:
            return
        import uuid
        form_id = str(uuid.uuid4())
        wcag_violations_json = json.dumps(list(form_structure.wcag_violations))
        wcag_score = "FAIL" if form_structure.wcag_violations else "AA"
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO form_observations
                       (form_id, job_fingerprint, platform, company_id,
                        total_fields, required_fields, salary_history_requested,
                        wcag_score, wcag_violations, jurisdiction,
                        estimated_completion_minutes, observed_date, schema_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (form_id, job_fingerprint, platform, company_id,
                     len(form_structure.fields),
                     sum(1 for f in form_structure.fields if f.is_required),
                     int(form_structure.has_salary_history_field),
                     wcag_score, wcag_violations_json, jurisdiction,
                     estimated_minutes, date.today().isoformat(),
                     RESEARCH_SCHEMA_VERSION),
                )
        except Exception as exc:
            logger.debug("ResearchSignalAggregator | Form obs error: %s", exc)

    def get_statistics_summary(self) -> dict:
        """Return a summary of accumulated research data.

        Returns:
            Dict with counts by signal type, severity, and jurisdiction.
        """
        if not self._enabled:
            return {}
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """SELECT signal_type, severity, COUNT(*) as cnt,
                              AVG(confidence) as avg_confidence
                       FROM research_signals
                       GROUP BY signal_type, severity
                       ORDER BY cnt DESC"""
                )
                rows = cursor.fetchall()
                return {
                    "by_signal_type": [dict(r) for r in rows],
                    "total_signals": sum(r["cnt"] for r in rows),
                }
        except Exception:
            return {}

    # =========================================================================
    # MACRO‑SIGNALS — corpus‑level analysis (LM‑01, LM‑02, LM‑03)
    # =========================================================================

    def compute_macro_signals(self) -> None:
        """Compute corpus-level macro-signals (LM-01, LM-02, LM-03).

        Called periodically by the daemon flush loop (every
        ``macro_signal_interval_seconds``).  Each analysis reads from the
        accumulated corpus tables and enqueues the resulting signals for
        persistence via the same queue-plus-daemon-thread pipeline used by
        per‑posting detectors, so macro‑signals are written to the same
        ``research_signals`` table with the same provenance guarantees.
        """
        if not self._enabled:
            return

        try:
            from auto_apply.domain.services.macro_analysis import (  # noqa: PLC0415
                compute_sector_opening_ratios,
                compute_black_hole_index,
                compute_geographic_pay_compression,
            )

            # ── LM-01: Sector opening-to-application ratio ────────────────
            sector_counts = self._query_sector_counts()
            lm01_signals = compute_sector_opening_ratios(sector_counts)
            for signal in lm01_signals:
                self._queue.put_nowait(signal)
            if lm01_signals:
                logger.info(
                    "ResearchSignalAggregator | LM-01: %d sector signals",
                    len(lm01_signals),
                )

            # ── LM-02: Application black hole mapping ─────────────────────
            records = self._query_response_rate_records()
            lm02_signals = compute_black_hole_index(records)
            for signal in lm02_signals:
                self._queue.put_nowait(signal)
            if lm02_signals:
                logger.info(
                    "ResearchSignalAggregator | LM-02: %d black‑hole signals",
                    len(lm02_signals),
                )

            # ── LM-03: Geographic pay compression ─────────────────────────
            metro_data = self._query_metro_salary_demographics()
            lm03_signals = compute_geographic_pay_compression(metro_data)
            for signal in lm03_signals:
                self._queue.put_nowait(signal)
            if lm03_signals:
                logger.info(
                    "ResearchSignalAggregator | LM-03: %d geo‑pay signals",
                    len(lm03_signals),
                )

        except Exception as exc:
            logger.error(
                "ResearchSignalAggregator: macro_analysis failed: %s", exc
            )

    # ── Private query helpers for macro‑signals ───────────────────────────

    def _query_sector_counts(self) -> list:
        """Return per‑sector posting counts for LM‑01.

        Approximates sectors from ``job_category`` values in
        ``research_signals`` and ``job_lifecycles``.  BLS JOLTS comparison
        data is not available from the local corpus alone — the returned
        ``SectorPostingCount`` objects have ``bls_jolts_openings=None``
        unless external enrichment has been performed.

        Returns:
            List of ``SectorPostingCount`` dataclass instances.
        """
        from auto_apply.domain.services.macro_analysis import (  # noqa: PLC0415
            SectorPostingCount,
        )

        results: list = []
        try:
            with self._get_connection() as conn:
                # Count distinct job fingerprints by job_category in signals.
                rows = conn.execute(
                    """SELECT COALESCE(job_category, 'unknown') AS sic_code,
                              COUNT(DISTINCT posting_hash) AS total_postings
                       FROM research_signals
                       WHERE posting_hash IS NOT NULL
                       GROUP BY job_category
                       ORDER BY total_postings DESC"""
                ).fetchall()

            for row in rows:
                results.append(
                    SectorPostingCount(
                        sic_code=row["sic_code"] or "unknown",
                        sector_name=row["sic_code"] or "Unknown Sector",
                        total_postings=row["total_postings"],
                        bls_jolts_openings=None,  # external enrichment required
                    )
                )
        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator | _query_sector_counts failed: %s", exc
            )

        return results

    def _query_response_rate_records(self) -> list:
        """Return per‑platform and per‑company response‑rate records for LM‑02.

        Reads from ``application_outcomes``, grouping by platform and
        anonymized company_id.

        Returns:
            List of ``ResponseRateRecord`` dataclass instances.
        """
        from auto_apply.domain.services.macro_analysis import (  # noqa: PLC0415
            ResponseRateRecord,
        )

        results: list = []
        try:
            with self._get_connection() as conn:
                # Per‑platform
                platform_rows = conn.execute(
                    """SELECT platform AS entity_id,
                              'platform' AS entity_type,
                              COUNT(*) AS applications_sent,
                              SUM(acknowledgment_received) AS responses_received
                       FROM application_outcomes
                       GROUP BY platform"""
                ).fetchall()

                for row in platform_rows:
                    results.append(
                        ResponseRateRecord(
                            entity_id=row["entity_id"] or "unknown",
                            entity_type=row["entity_type"],
                            applications_sent=row["applications_sent"],
                            responses_received=row["responses_received"] or 0,
                        )
                    )

                # Per‑company (anonymized)
                company_rows = conn.execute(
                    """SELECT company_id AS entity_id,
                              'company' AS entity_type,
                              COUNT(*) AS applications_sent,
                              SUM(acknowledgment_received) AS responses_received
                       FROM application_outcomes
                       WHERE company_id IS NOT NULL
                       GROUP BY company_id"""
                ).fetchall()

                for row in company_rows:
                    results.append(
                        ResponseRateRecord(
                            entity_id=row["entity_id"],
                            entity_type=row["entity_type"],
                            applications_sent=row["applications_sent"],
                            responses_received=row["responses_received"] or 0,
                        )
                    )
        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator | _query_response_rate_records failed: %s",
                exc,
            )

        return results

    def _query_metro_salary_demographics(self) -> list:
        """Return metro‑area salary observations for LM‑03.

        Reads median salary from ``salary_observations`` grouped by metro
        area.  The ``demographic_index`` field is set to 0.0 (placeholder)
        because AA's local corpus does not contain Census demographic data —
        that requires external enrichment (e.g. ACS 5‑year estimates) which
        must be joined by the analyst at publication time.

        Returns:
            List of ``MetroSalaryDemographic`` dataclass instances.
        """
        from auto_apply.domain.services.macro_analysis import (  # noqa: PLC0415
            MetroSalaryDemographic,
        )

        results: list = []
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """SELECT location_metro AS metro_area,
                               AVG(COALESCE(salary_max, salary_min)) AS avg_salary
                       FROM salary_observations
                       WHERE location_metro IS NOT NULL
                         AND location_metro != ''
                         AND (salary_max IS NOT NULL OR salary_min IS NOT NULL)
                       GROUP BY location_metro
                       HAVING COUNT(*) >= 5"""
                ).fetchall()

            for row in rows:
                results.append(
                    MetroSalaryDemographic(
                        metro_area=row["metro_area"],
                        col_normalized_salary_median=row["avg_salary"] or 0.0,
                        demographic_index=0.0,  # placeholder — requires external enrichment
                    )
                )
        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator | _query_metro_salary_demographics failed: %s",
                exc,
            )

        return results

    # ── Daemon thread ─────────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        """Background thread: drain queue, write signals to SQLite, and
        periodically compute macro‑signals."""
        batch: list[ResearchSignal] = []
        while self._running:
            try:
                item = self._queue.get(timeout=self._flush_interval)
                if item is None:
                    break
                batch.append(item)
                # Drain additional items without waiting
                while True:
                    try:
                        nxt = self._queue.get_nowait()
                        if nxt is None:
                            break
                        batch.append(nxt)
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            if batch:
                self._write_batch(batch)
                batch = []

            # ── Periodic macro‑signal computation ────────────────────────
            now = time.monotonic()
            if now - self._last_macro_ts >= self._macro_signal_interval:
                self._last_macro_ts = now
                self.compute_macro_signals()

        # Final flush
        remaining = []
        while True:
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    remaining.append(item)
            except queue.Empty:
                break
        if remaining:
            self._write_batch(remaining)

    def _ensure_signer(self) -> Any:
        """Lazily initialize the ProvenanceSigner and store the public key.

        Returns:
            The ProvenanceSigner instance, or None if initialization fails.
        """
        if self._signer is not None:
            return self._signer

        try:
            from auto_apply.adapters.secondary.security.data_protection import (  # noqa: PLC0415
                ProvenanceSigner,
            )
            from auto_apply.domain.config import RESEARCH_DIR  # noqa: PLC0415

            key_path = RESEARCH_DIR / "provenance_key.pem"
            signer = ProvenanceSigner(key_path=key_path)

            # Store the public key once per installation
            if not self._public_key_stored:
                self._store_public_key(signer.public_key_hex)
                self._public_key_stored = True

            self._signer = signer
            return signer

        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator: ProvenanceSigner init failed: %s", exc
            )
            return None

    def _store_public_key(self, public_key_hex: str) -> None:
        """Persist the provenance public key to the database metadata table."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO research_provenance
                       (id, public_key_hex, created_at)
                       VALUES (1, ?, ?)""",
                    (public_key_hex, date.today().isoformat()),
                )
            logger.info(
                "ResearchSignalAggregator: provenance public key stored (%s...)",
                public_key_hex[:16],
            )
        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator: could not store public key: %s", exc
            )

    def _write_batch(self, signals: list[ResearchSignal]) -> None:
        """Persist a batch of signals to SQLite in a single transaction.

        Uses INSERT OR IGNORE keyed on signal_id (PRIMARY KEY). For signals
        with a posting_hash, run_all_detectors() has already made signal_id
        deterministic — derived from (signal_type, posting_hash,
        detected_date) — so repeat detections of the same fact via
        different observation pathways (job posting vs. form) collapse to
        a single row here. This is the ONLY deduplication mechanism;
        nothing upstream filters duplicates, which keeps detectors pure
        and the dedup logic in exactly one place.

        Provenance: Each signal's content is hashed (SHA-256) and signed
        with an Ed25519 key unique to this AA installation.  The signature
        is stored alongside the signal so that third-party verifiers can
        authenticate the data's origin using the public key in
        ``research_provenance``.
        """
        # ── Lazy-init provenance signer ──────────────────────────────────
        signer = self._ensure_signer()

        # ── Build rows with provenance ────────────────────────────────────
        rows: list[tuple] = []
        for s in signals:
            content_hash: str | None = None
            provenance_signature: str | None = None

            if signer is not None:
                try:
                    # Compute a deterministic content hash over the fields
                    # that constitute the signal's evidentiary payload.
                    content = json.dumps({
                        "signal_type": s.signal_type,
                        "severity": s.severity,
                        "confidence": s.confidence,
                        "evidence_text": s.evidence_text or "",
                        "platform": s.platform or "",
                        "jurisdiction": s.jurisdiction or "",
                        "detected_date": s.detected_date.isoformat(),
                        "posting_hash": s.posting_hash or "",
                    }, sort_keys=True).encode("utf-8")

                    content_hash = hashlib.sha256(content).hexdigest()
                    provenance_signature = signer.sign_hex(content_hash)
                except Exception as exc:
                    logger.debug(
                        "ResearchSignalAggregator: provenance signing failed "
                        "for signal %s: %s",
                        s.signal_type, exc,
                    )

            rows.append((
                s.signal_id, s.signal_type, s.severity,
                s.confidence, s.evidence_text, s.platform,
                s.jurisdiction, s.company_id, s.job_category,
                s.detected_date.isoformat(),
                s.schema_version, self._consent_version,
                s.posting_hash, content_hash, provenance_signature,
            ))

        try:
            with self._get_connection() as conn:
                conn.executemany(
                    """INSERT OR IGNORE INTO research_signals
                       (signal_id, signal_type, severity, confidence,
                        evidence_text, platform, jurisdiction, company_id,
                        job_category, detected_date, schema_version,
                        consent_version, posting_hash,
                        content_hash, provenance_signature)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )
            logger.debug(
                "ResearchSignalAggregator | Wrote %d signals to DB", len(signals)
            )
        except Exception as exc:
            logger.error("ResearchSignalAggregator | Write batch failed: %s", exc)
