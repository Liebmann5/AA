"""
ResearchSignalAggregator — integrates signal detectors with the AA pipeline.

This adapter:
1. Subscribes to relevant EventBus events (JOB_DISCOVERED, FORM_OBSERVED, etc.)
2. Builds DetectionContext from event payloads
3. Runs all detectors via run_all_detectors()
4. Persists resulting ResearchSignal objects to SQLite
5. Publishes aggregate statistics on a configurable interval

Architecture rule: This class is an adapter — it may import from infrastructure.
It must NEVER be imported by domain or application layers.
"""
from __future__ import annotations

import hashlib
import json
import logging
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

# ── SQLite schema (version 2) ─────────────────────────────────────────────────
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
    posting_hash    TEXT
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

    Args:
        db_path: Path to the research SQLite database file.
        consent_version: The version of consent user has agreed to.
            If None, research is disabled even if called.
        flush_interval_seconds: How often the daemon thread flushes the queue.
    """

    def __init__(
        self,
        db_path: Path,
        consent_version: str | None = None,
        flush_interval_seconds: float = 5.0,
    ) -> None:
        self._db_path = db_path
        self._consent_version = consent_version
        self._flush_interval = flush_interval_seconds
        self._queue: queue.Queue[ResearchSignal | None] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._enabled = consent_version is not None

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

    # ── Daemon thread ─────────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        """Background thread: drain queue and write signals to SQLite."""
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
        """
        try:
            with self._get_connection() as conn:
                conn.executemany(
                    """INSERT OR IGNORE INTO research_signals
                       (signal_id, signal_type, severity, confidence,
                        evidence_text, platform, jurisdiction, company_id,
                        job_category, detected_date, schema_version,
                        consent_version, posting_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            s.signal_id, s.signal_type, s.severity,
                            s.confidence, s.evidence_text, s.platform,
                            s.jurisdiction, s.company_id, s.job_category,
                            s.detected_date.isoformat(),
                            s.schema_version, self._consent_version,
                            s.posting_hash,
                        )
                        for s in signals
                    ],
                )
            logger.debug(
                "ResearchSignalAggregator | Wrote %d signals to DB", len(signals)
            )
        except Exception as exc:
            logger.error("ResearchSignalAggregator | Write batch failed: %s", exc)
