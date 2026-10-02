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
import hmac
import json
import logging
from typing import Any
import queue
import sqlite3
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from auto_apply.domain.constants import RESEARCH_SCHEMA_VERSION
from auto_apply.domain.ports.research_port import (
    ApplicationOutcomeObservation,
    DiscoveryCandidateObservation,
    DiscoveryObservation,
    FormObservation,
    JobPostingObservation,
    ResearchAccounting,
    ResearchObserverPort,
)
from auto_apply.domain.services.job_lifecycle_tracker import (
    JobLifecycleRecord,
    cross_platform_date_spread,
    days_live,
    update_lifecycle,
)
from auto_apply.domain.services.research_identity import (
    ABSENT_COMPANY_TOKENS,
    resolve_research_salt,
)
from auto_apply.domain.services.research_statistics import percentile
from auto_apply.domain.services.signal_detectors import (
    OUTCOME_CLEAN,
    DetectionContext,
    DetectionResult,
    DetectorOutcome,
    ResearchSignal,
    run_all_detectors,
)
from auto_apply.domain.services.posting_context import posting_detection_context
from auto_apply.domain.services.url_evidence import redact_rendered_urls

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DetectorExamination:
    """Persistence-bound record of one run_all_detectors pass (item 5, O2/O3).

    Built by submit_context from the domain's DetectionResult, carried on the
    flush queue, written by _write_examination_batch. Only NON-clean outcomes
    are stored: the roster keeps "clean" derivable as roster-minus-recorded,
    so a 29-detector clean examination costs one row instead of twenty-nine
    (item 5, O1).
    """

    posting_hash: str | None
    platform: str | None
    jurisdiction: str | None
    detectors_roster: tuple[str, ...]
    detectors_fired: int
    signals_fired: int
    detectors_raised: int
    outcomes: tuple[DetectorOutcome, ...]
    page_copy_id: str | None = None

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
    provenance_signature TEXT,
    page_copy_id    TEXT
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

CREATE TABLE IF NOT EXISTS discovery_pages (
    page_id              TEXT PRIMARY KEY,
    provider             TEXT,
    page_host            TEXT,
    page_state           TEXT,
    blocked              INTEGER DEFAULT 0,
    architecture         TEXT,
    card_count           INTEGER,
    resolved_count       INTEGER,
    multi_route_count    INTEGER,
    deferred_count       INTEGER,
    no_destination_count INTEGER,
    sponsored_card_count INTEGER,
    activation_attempts  INTEGER,
    activation_resolved  INTEGER,
    learned_identity     TEXT,
    observed_date        TEXT NOT NULL,
    schema_version       INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS discovery_cards (
    card_id          TEXT PRIMARY KEY,
    page_id          TEXT NOT NULL REFERENCES discovery_pages(page_id),
    card_index       INTEGER,
    title            TEXT,
    resolution_state TEXT,
    selected_host    TEXT,
    schema_version   INTEGER DEFAULT 2
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    candidate_id     TEXT PRIMARY KEY,
    card_id          TEXT NOT NULL REFERENCES discovery_cards(card_id),
    resolved_host    TEXT,
    anchor_text      TEXT,
    source           TEXT,
    outcome          TEXT,
    rejection_reason TEXT,
    ad_evidence      TEXT,
    apply_intent     INTEGER DEFAULT 0,
    title_overlap    REAL,
    method           TEXT,
    schema_version   INTEGER DEFAULT 2
);

-- Detector outcome accounting (item 5): one examination row per detection
-- pass (the denominator every rate needs), outcome rows for non-clean
-- outcomes only. detectors_roster is a JSON array of the signal_types that
-- ran, in registry order, so "clean" stays derivable as roster minus
-- recorded outcomes even after the registry grows.
CREATE TABLE IF NOT EXISTS detector_examinations (
    examination_id     TEXT PRIMARY KEY,
    posting_hash       TEXT,
    platform           TEXT,
    jurisdiction       TEXT,
    detectors_run      INTEGER NOT NULL,
    detectors_roster   TEXT NOT NULL,
    detectors_fired    INTEGER NOT NULL,
    signals_fired      INTEGER NOT NULL,
    detectors_raised   INTEGER NOT NULL,
    examined_date      TEXT NOT NULL,
    schema_version     INTEGER DEFAULT 2,
    page_copy_id       TEXT
);

CREATE TABLE IF NOT EXISTS detector_outcomes (
    outcome_id         TEXT PRIMARY KEY,
    examination_id     TEXT NOT NULL REFERENCES detector_examinations(examination_id),
    signal_type        TEXT NOT NULL,
    outcome            TEXT NOT NULL,
    signals_count      INTEGER NOT NULL DEFAULT 0,
    error_class        TEXT,
    examined_date      TEXT NOT NULL,
    schema_version     INTEGER DEFAULT 2
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
CREATE INDEX IF NOT EXISTS idx_discovery_cards_page ON discovery_cards(page_id);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_card ON discovery_candidates(card_id);
CREATE INDEX IF NOT EXISTS idx_examinations_date ON detector_examinations(examined_date);
CREATE INDEX IF NOT EXISTS idx_examinations_posting ON detector_examinations(posting_hash);
CREATE INDEX IF NOT EXISTS idx_outcomes_exam ON detector_outcomes(examination_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_type ON detector_outcomes(signal_type);
"""


#: user_version value stamping the item-4a company-identity migration. Rows
#: written before it carry company_id values minted under the two retired
#: constructions and are nulled exactly once, at first open.
_COMPANY_IDENTITY_MIGRATION_VERSION: int = 3

#: user_version value stamping the phantom-identity migration. Rows minted
#: between item 4a and the canonical-form fix carry, for every posting whose
#: company extraction failed, ONE shared id — HMAC(salt, "unknown") — so
#: unrelated employers arrived pre-merged into a fabricated entity. Those
#: ids are recomputable (the names are known constants, the salt is in hand),
#: so exactly those — and nothing else — are nulled once, at first open.
_PHANTOM_IDENTITY_MIGRATION_VERSION: int = 4

#: Columns added after a table first shipped (table, column, type). A
#: database created before them gains them by ALTER TABLE at open, never by
#: recreation; rows written earlier read NULL — "no page copy", which is
#: true of them (item 6).
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("research_signals", "page_copy_id", "TEXT"),
    ("detector_examinations", "page_copy_id", "TEXT"),
)


def _candidate_hosts(cand: DiscoveryCandidateObservation) -> set[str]:
    """Every host a candidate's own URLs name — the context the text guard
    needs to recognise a bare ``host/path`` as a rendered URL."""
    hosts = {cand.resolved_host}
    for url in (cand.original_url, cand.resolved_url):
        try:
            hosts.add((urllib.parse.urlsplit(url).hostname or "").lower())
        except ValueError:
            continue
    hosts.discard("")
    return hosts


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
        provenance_key_path: Where the private Ed25519 signing key lives.
            composition_root injects domain.config.PROVENANCE_KEY_PATH, which
            is deliberately OUTSIDE the research directory so no "share your
            research data" instruction can sweep the key along. None resolves
            to that same constant lazily; tests inject a tmp path instead.
    """

    def __init__(
        self,
        db_path: Path,
        consent_version: str | None = None,
        flush_interval_seconds: float = 5.0,
        macro_signal_interval_seconds: float = 3600.0,
        provenance_key_path: Path | None = None,
    ) -> None:
        self._db_path = db_path
        self._provenance_key_path = provenance_key_path
        self._consent_version = consent_version
        self._flush_interval = flush_interval_seconds
        self._macro_signal_interval = macro_signal_interval_seconds
        self._queue: queue.Queue[ResearchSignal | DiscoveryObservation | _DetectorExamination | None] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self._enabled = consent_version is not None
        # True once the database exists and its schema is in place. Reads of
        # what was already written gate on THIS, not on _enabled: stop()
        # clears _enabled so nothing new is accepted, but a stopped
        # aggregator must still report what it wrote (session statistics are
        # read after shutdown).
        self._db_ready = False

        # ── Provenance — lazy‑init on first write ─────────────────────────
        self._signer: Any = None
        self._public_key_stored: bool = False

        # Resolved at construction when research is enabled (see __init__
        # below); None otherwise, and the v4 migration never runs then.
        self._research_salt: str | None = None

        # ── Macro‑signal tracking ─────────────────────────────────────────
        self._last_macro_ts: float = 0.0   # monotonic timestamp of last run

        # ── Discovery-surface observation counter (§4b) ──────────────────
        self._discovery_observation_count: int = 0

        # Session accounting (item 5 R2; item 3). Three tallies, keyed by
        # site or table, read through accounting() into the session report
        # and both end-of-session views:
        #   _recorded — rows newly written this session, per table;
        #   _failures — records LOST (not written) per failing site, counted
        #               in records, so a failed batch of five counts five;
        #   _degraded — work written in a weaker form (unsigned signal,
        #               detector without lifecycle history, failed analysis).
        # Producers run on the discovery and workflow threads and the flush
        # daemon writes, so every update holds _counter_lock: a bare
        # d[k] = d.get(k, 0) + n can drop increments across threads.
        self._recorded: dict[str, int] = {}
        self._failures: dict[str, int] = {}
        self._degraded: dict[str, int] = {}
        self._counter_lock = threading.Lock()

        if self._enabled:
            # The salt is resolved HERE — at adapter construction, not at the
            # first observation (item 4a, ruling R1). Every downstream path
            # into the detectors wraps detection in try/except
            # (run_all_detectors swallows per-detector; the workflows swallow
            # per observation), so a salt that first failed inside
            # compute_company_id would degrade to a run that produces zero
            # research rows while looking healthy. ResearchSaltError must
            # propagate out of this constructor: composition_root.py has not
            # been re-verified for this change, and any wrapper there that
            # catches it and degrades to NullResearchObserver re-creates the
            # silent shape this raise exists to prevent.
            # The value is kept on the instance: the phantom-identity
            # migration (_null_phantom_company_ids) needs it to recognise
            # ids minted by the retired construction for the known
            # placeholder names.
            self._research_salt = resolve_research_salt()
            self._initialize_db()

    def _initialize_db(self) -> None:
        """Create tables if they don't exist, then run the one-time migration."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._get_connection() as conn:
                conn.executescript(_SCHEMA_SQL)
                self._add_missing_columns(conn)
                self._null_legacy_company_ids(conn)
                self._null_phantom_company_ids(conn)
            self._db_ready = True
            logger.info("ResearchSignalAggregator | DB initialized at %s", self._db_path)
        except Exception as exc:
            logger.error("ResearchSignalAggregator | DB init failed: %s", exc)
            self._enabled = False
            # Nothing this session observes can be recorded, and how much
            # that is cannot be counted; the report must at least say so.
            self._record_degraded("database_init")

    @staticmethod
    def _add_missing_columns(conn: sqlite3.Connection) -> None:
        """Add every _ADDED_COLUMNS column a database created earlier lacks."""
        for table, column, ddl in _ADDED_COLUMNS:
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _null_legacy_company_ids(self, conn: sqlite3.Connection) -> None:
        """NULL every pre-migration research ``company_id``, exactly once.

        Rows written before item 4a carry a company_id minted under one of
        the two retired constructions — HMAC-SHA256 with a possibly-default
        salt (detector path) or SHA-256(name + salt) (application path).
        Neither value can be re-derived (the names were never stored) and the
        two schemes cannot join to each other or to new rows. A value that
        cannot join, sitting in a column whose whole purpose is joining, is
        plausible-looking data that would be counted as data — so, per the
        FetchedDescription precedent, it is made visibly absent. Everything
        else on the row (signal type, severity, dates, evidence) survives;
        corpus counts remain valid. Old provenance signatures also survive:
        the signed content assembled in _write_batch does not cover
        company_id.

        Idempotent via ``PRAGMA user_version``: runs only when the database
        predates the marker, is a no-op on an empty or freshly created
        database, and never touches rows written afterwards.
        job_lifecycles.company_id and form_observations.company_id need no
        migration: nothing has ever written them (_save_lifecycle hardcodes
        NULL; observe_form never passes a company_id).
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= _COMPANY_IDENTITY_MIGRATION_VERSION:
            return
        conn.execute(
            "UPDATE research_signals SET company_id = NULL "
            "WHERE company_id IS NOT NULL"
        )
        conn.execute(
            "UPDATE application_outcomes SET company_id = NULL "
            "WHERE company_id IS NOT NULL"
        )
        conn.execute(
            f"PRAGMA user_version = {_COMPANY_IDENTITY_MIGRATION_VERSION}"
        )
        logger.info(
            "ResearchSignalAggregator | nulled legacy company_id values "
            "(item 4a migration, user_version -> %d)",
            _COMPANY_IDENTITY_MIGRATION_VERSION,
        )

    def _null_phantom_company_ids(self, conn: sqlite3.Connection) -> None:
        """NULL every company_id minted from a placeholder name, exactly once.

        Rows written between item 4a and the canonical-form fix carry, for
        every posting whose company extraction failed, the SAME id:
        HMAC(salt, "unknown") — discovery producers emit the literal
        "Unknown" when they cannot name a company, so unrelated employers
        arrived in the corpus pre-merged into one fabricated entity with a
        fabricated response rate. Unlike the item-4a rows, these ids are
        recomputable: the names are known constants and the salt is in hand,
        so the migration recognises exactly the provable phantom and leaves
        every other row untouched. This recomputation MINTS nothing — it
        recognises corpses of the retired construction.

        What survives, deliberately:
          * ids minted from real names whose old form equals the new
            canonical form (f(name) == name.lower()) — the overwhelming
            majority; their joins stay valid across the boundary;
          * ids minted from name VARIANTS the new canonical form would now
            merge (e.g. a trailing-newline spelling). Those rows are
            truthful about a spelling-variant cohort but will never be
            joined by new writes. Dead weight, not fabricated data, and
            indistinguishable from real ids — so they stay;
          * ids minted from whitespace-only names, if any exist: enumerable
            only in principle, produced by no known producer, and
            indistinguishable from real ids. Disclosed, not nulled.

        What a researcher may trust afterwards: within rows written after
        this migration, company_id is stable across case, whitespace,
        invisibles and Unicode spelling. A company_id that appears both
        before and after is one continuous identity. A pre-migration
        company_id that never reappears may be a merged-away variant — join
        across the boundary at your own risk. No post-migration row is part
        of the "unknown" phantom, because compute_company_id now mints None
        for absence.

        Idempotent via PRAGMA user_version; composes after the item-4a
        migration (a pre-4a database is fully nulled by that one first);
        a no-op on a fresh database. When item 10 re-keys the salt, every
        id changes again and that migration supersedes this one wholesale.
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= _PHANTOM_IDENTITY_MIGRATION_VERSION:
            return
        if self._research_salt is None:
            # Unreachable: _initialize_db only runs when research is enabled,
            # which resolves the salt first. Guarded so the type stays honest.
            return
        phantom_ids = [
            hmac.new(
                self._research_salt.encode("utf-8"),
                token.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()[:16]
            for token in sorted(ABSENT_COMPANY_TOKENS)
        ]
        placeholders = ", ".join("?" for _ in phantom_ids)
        conn.execute(
            f"UPDATE research_signals SET company_id = NULL "
            f"WHERE company_id IN ({placeholders})",
            phantom_ids,
        )
        conn.execute(
            f"UPDATE application_outcomes SET company_id = NULL "
            f"WHERE company_id IN ({placeholders})",
            phantom_ids,
        )
        conn.execute(
            f"PRAGMA user_version = {_PHANTOM_IDENTITY_MIGRATION_VERSION}"
        )
        logger.info(
            "ResearchSignalAggregator | nulled phantom company_id values "
            "(%d placeholder identities, user_version -> %d)",
            len(phantom_ids),
            _PHANTOM_IDENTITY_MIGRATION_VERSION,
        )

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
        """Signal the daemon to stop and flush remaining items.

        Also marks the aggregator DISABLED: after stop(), the observe_* entry
        points become no-ops instead of enqueueing into a queue no thread
        will ever drain (a memory leak dressed as acceptance). A stopped
        aggregator reports is_enabled=False and has no restart path — build
        a new one. This is what makes "withdraw consent" and "session
        shutdown" real: no later write can recreate the database or the
        provenance key the purge removed. Reads are unaffected:
        get_statistics_summary() still reports what was written (it gates on
        _db_ready, not _enabled).
        """
        self._running = False
        self._enabled = False
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
            result: DetectionResult = run_all_detectors(ctx)
            for signal in result.signals:
                self._queue.put_nowait(signal)
            # Item 5: the examination itself is a record. One row per
            # detection pass answers the denominator question (M6) — how
            # many postings were examined, by which detectors, with what
            # outcome — which no rate computed from research_signals alone
            # could support before.
            self._queue.put_nowait(
                _DetectorExamination(
                    posting_hash=ctx.posting_hash,
                    platform=ctx.platform,
                    jurisdiction=ctx.jurisdiction,
                    detectors_roster=result.detectors_run,
                    detectors_fired=result.detectors_fired,
                    signals_fired=len(result.signals),
                    detectors_raised=result.detectors_raised,
                    outcomes=tuple(
                        o for o in result.outcomes if o.outcome != OUTCOME_CLEAN
                    ),
                    page_copy_id=ctx.page_copy_id,
                )
            )
            if result.signals:
                logger.debug(
                    "ResearchSignalAggregator | %d signals detected for '%s'",
                    len(result.signals), ctx.job_title[:50],
                )
        except Exception as exc:
            # R2/C2: counted and surfaced via get_statistics_summary; logged
            # by class name only — str(exc) can quote the posting.
            self._record_failure("submit_context")
            logger.exception(
                "ResearchSignalAggregator | Detection error (%s)",
                type(exc).__name__,
            )

    # ── ResearchObserverPort implementation ──────────────────────────────────
    # These three methods satisfy domain.ports.research_port.ResearchObserverPort.
    # Workflows depend only on that Protocol; composition_root.py injects this
    # class (or NullResearchObserver when consent is not active).

    @property
    def is_enabled(self) -> bool:
        """Whether research collection is currently active (consent given)."""
        return self._enabled

    def _failures_snapshot(self) -> dict[str, int]:
        with self._counter_lock:
            return dict(self._failures)

    @staticmethod
    def _bump(counts: dict[str, int], key: str, n: int) -> None:
        if n > 0:
            counts[key] = counts.get(key, 0) + n

    def _record_failure(self, site: str, n: int = 1) -> None:
        """Count records LOST at a failing site (item 5 R2; item 3)."""
        with self._counter_lock:
            self._bump(self._failures, site, n)

    def _record_degraded(self, site: str, n: int = 1) -> None:
        """Count work recorded in a weaker form (item 3)."""
        with self._counter_lock:
            self._bump(self._degraded, site, n)

    def _record_written(self, table: str, n: int) -> None:
        """Count rows newly written this session (item 3)."""
        with self._counter_lock:
            self._bump(self._recorded, table, n)

    def accounting(self) -> ResearchAccounting:
        """What this session recorded, lost and degraded (ResearchSessionPort).

        Read after stop() it is final; read while the daemon is still
        flushing it says so (``complete=False``). ``corpus`` comes from
        get_statistics_summary(), the totals for the whole database. A
        research-off aggregator (no consent) reports inactive. Never raises:
        a report must not fail because accounting could not be read.
        """
        if self._consent_version is None:
            return ResearchAccounting()
        try:
            thread = self._thread
            flushing = thread is not None and thread.is_alive()
            complete = not flushing and self._queue.empty()
            with self._counter_lock:
                recorded = dict(self._recorded)
                lost = dict(self._failures)
                degraded = dict(self._degraded)
            summary = self.get_statistics_summary()
            corpus = {
                key: int(summary.get(key, 0) or 0)
                for key in (
                    "total_signals",
                    "examinations",
                    "detectors_fired",
                    "detectors_raised",
                )
            }
            return ResearchAccounting.from_counts(
                complete=complete,
                recorded=recorded,
                lost=lost,
                degraded=degraded,
                corpus=corpus,
            )
        except Exception as exc:  # noqa: BLE001 — accounting must never raise
            logger.warning(
                "ResearchSignalAggregator | accounting unavailable (%s)",
                type(exc).__name__,
            )
            return ResearchAccounting(active=True, complete=False)

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

            # One builder for live and replay (posting_context, item 7): the
            # aggregator adds only what it alone has — lifecycle history and
            # the salary corpus percentile.
            ctx = posting_detection_context(
                observation,
                current_date=date.today(),
                first_seen_date=updated_record.first_seen if updated_record else None,
                days_live=days_live(updated_record, date.today()) if updated_record else None,
                times_seen_cross_platform=n_platforms,
                previous_posting_dates=all_first_seen,
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
            # Item 5, R2: counted and surfaced; class name only (C2).
            self._record_failure("observe_job_posting")
            logger.exception(
                "ResearchSignalAggregator | observe_job_posting error (%s)",
                type(exc).__name__,
            )

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
            # Item 5, R2: observe_form feeds the detector chain through
            # submit_context, so its swallow is the same class as the two
            # M5 sites; counted and surfaced; class name only (C2).
            self._record_failure("observe_form")
            logger.exception(
                "ResearchSignalAggregator | observe_form error (%s)",
                type(exc).__name__,
            )

    def observe_application_outcome(
        self, observation: ApplicationOutcomeObservation
    ) -> None:
        """Record an application outcome for LM-02 black-hole tracking.

        Args:
            observation: Outcome data (platform, company, ack status).
        """
        if not self._enabled:
            return
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
            self._record_written("application_outcomes", 1)
        except Exception as exc:
            self._record_failure("observe_application_outcome")
            logger.debug("ResearchSignalAggregator | observe_application_outcome error: %s", exc)

    def observe_discovery(self, observation: DiscoveryObservation) -> None:
        """Accept a discovery-surface observation (§4b) and enqueue it for
        persistence.

        Persistence is no longer deferred to a consumer batch: the record is
        placed on the same queue-plus-daemon pipeline as signals (no I/O on
        the calling discovery thread — the handler rule in
        domain/constants.py) and written by _write_discovery_batch into
        discovery_pages / discovery_cards / discovery_candidates. The
        consent gate above is unchanged: with consent absent this method
        costs exactly nothing and no rows exist.

        Two rulings bound what the daemon may write (item 4c): candidate
        original_url / resolved_url are never persisted (the set of
        candidate URLs on one page is the query's result set — the thing
        page_host was designed not to record), and row identity is a random
        surrogate, never content-derived. See _write_discovery_batch.

        The INFO line below logs seven scalars about the record, never the
        record itself; an earlier revision of this docstring claimed the
        record was "logged verbatim at INFO", which the code never did.

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
            self._queue.put_nowait(observation)
        except Exception as exc:
            self._record_failure("observe_discovery")
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
            self._record_degraded("lifecycle_load")
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
            self._record_failure("lifecycle_write")
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
            self._record_degraded("lifecycle_load")
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
            self._record_degraded("salary_percentile")
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
            self._record_written("salary_observations", 1)
        except Exception as exc:
            self._record_failure("salary_write")
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
            self._record_written("form_observations", 1)
        except Exception as exc:
            self._record_failure("form_write")
            logger.debug("ResearchSignalAggregator | Form obs error: %s", exc)

    def get_statistics_summary(self) -> dict:
        """Return a summary of accumulated research data.

        Returns:
            Dict with counts by signal type and severity, the examination
            denominator (item 5), and in-process accounting-failure counters.
            Still answers after stop(): a stopped aggregator accepts nothing
            new but reports what it wrote. Empty only when no database was
            ever initialised.
        """
        if not self._db_ready:
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
                exam_row = conn.execute(
                    """SELECT COUNT(*) AS examinations,
                              COALESCE(SUM(detectors_raised), 0) AS raised,
                              COALESCE(SUM(detectors_fired), 0) AS fired
                       FROM detector_examinations"""
                ).fetchone()
                return {
                    "by_signal_type": [dict(r) for r in rows],
                    "total_signals": sum(r["cnt"] for r in rows),
                    # Item 5: the denominator, readable back. examinations =
                    # detection passes recorded; raised/fired = per-detector
                    # outcomes across those passes; accounting_failures =
                    # records lost this session, per site (R2; item 3 —
                    # accounting() carries the full three-way tally).
                    "examinations": exam_row["examinations"],
                    "detectors_raised": exam_row["raised"],
                    "detectors_fired": exam_row["fired"],
                    "accounting_failures": self._failures_snapshot(),
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
            self._record_degraded("macro_signals")
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
            self._record_degraded("macro_query")
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
            self._record_degraded("macro_query")
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
            self._record_degraded("macro_query")
            logger.warning(
                "ResearchSignalAggregator | _query_metro_salary_demographics failed: %s",
                exc,
            )

        return results

    # ── Daemon thread ─────────────────────────────────────────────────────────

    def _flush_loop(self) -> None:
        """Background thread: drain queue; write signals, discovery
        observations and detector examinations to SQLite; and periodically
        compute macro-signals."""
        batch: list[ResearchSignal] = []
        discovery_batch: list[DiscoveryObservation] = []
        examination_batch: list[_DetectorExamination] = []
        while self._running:
            try:
                item = self._queue.get(timeout=self._flush_interval)
                if item is None:
                    break
                if isinstance(item, DiscoveryObservation):
                    discovery_batch.append(item)
                elif isinstance(item, _DetectorExamination):
                    examination_batch.append(item)
                else:
                    batch.append(item)
                # Drain additional items without waiting
                while True:
                    try:
                        nxt = self._queue.get_nowait()
                        if nxt is None:
                            break
                        if isinstance(nxt, DiscoveryObservation):
                            discovery_batch.append(nxt)
                        elif isinstance(nxt, _DetectorExamination):
                            examination_batch.append(nxt)
                        else:
                            batch.append(nxt)
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            if batch:
                self._write_batch(batch)
                batch = []
            if discovery_batch:
                self._write_discovery_batch(discovery_batch)
                discovery_batch = []
            if examination_batch:
                self._write_examination_batch(examination_batch)
                examination_batch = []

            # ── Periodic macro‑signal computation ────────────────────────
            now = time.monotonic()
            if now - self._last_macro_ts >= self._macro_signal_interval:
                self._last_macro_ts = now
                self.compute_macro_signals()

        # Final flush.
        #
        # The local-batch writes below are DEFENCE, not a repair: on every
        # path out of the loop above, `batch`, `discovery_batch` and
        # `examination_batch` are already empty here. Each iteration clears
        # them after writing,
        # so they are empty at the top of the next one, and both exits are
        # reached before anything is appended in that iteration — the
        # sentinel `break` sits immediately after the blocking `get`, and
        # the `while self._running` test is at the top. Instrumenting this
        # point across three stop timings (immediately after enqueue,
        # mid-interval, and after a flush) reported local batch sizes of 0
        # every time.
        #
        # They are kept because the day this loop becomes time-gated and
        # accumulates across iterations, they are what stops a flush
        # interval's records dying at shutdown.
        #
        # The queue drain below is the load-bearing part: producers gate on
        # `self._enabled`, not `self._running`, so a record enqueued after
        # stop() posted the sentinel lands there and nowhere else.
        remaining: list[ResearchSignal] = []
        remaining_discovery: list[DiscoveryObservation] = []
        remaining_examination: list[_DetectorExamination] = []
        while True:
            try:
                item = self._queue.get_nowait()
                if item is not None:
                    if isinstance(item, DiscoveryObservation):
                        remaining_discovery.append(item)
                    elif isinstance(item, _DetectorExamination):
                        remaining_examination.append(item)
                    else:
                        remaining.append(item)
            except queue.Empty:
                break
        if batch:
            self._write_batch(batch)
        if remaining:
            self._write_batch(remaining)
        if discovery_batch:
            self._write_discovery_batch(discovery_batch)
        if remaining_discovery:
            self._write_discovery_batch(remaining_discovery)
        if examination_batch:
            self._write_examination_batch(examination_batch)
        if remaining_examination:
            self._write_examination_batch(remaining_examination)

    def _key_path(self) -> Path:
        """The provenance key's path: injected, else the config constant.

        The lazy import mirrors the pattern this module previously used for
        RESEARCH_DIR and keeps module-import graphs unchanged for tests.
        """
        if self._provenance_key_path is not None:
            return self._provenance_key_path
        from auto_apply.domain.config import PROVENANCE_KEY_PATH  # noqa: PLC0415

        return PROVENANCE_KEY_PATH

    def _ensure_signer(self) -> Any:
        """Lazily initialize the ProvenanceSigner and store the public key.

        If the key file has vanished under a live cached signer — a consent
        purge rotates the installation's research identity by deleting it —
        the signer is regenerated and the public key re-stored. Without this
        check, _public_key_stored staying True would leave later rows with
        no key on record and exports would lose verification.json.

        Returns:
            The ProvenanceSigner instance, or None if initialization fails.
        """
        if self._signer is not None:
            if self._key_path().exists():
                return self._signer
            self._signer = None
            self._public_key_stored = False

        try:
            from auto_apply.adapters.secondary.security.data_protection import (  # noqa: PLC0415
                ProvenanceSigner,
            )

            signer = ProvenanceSigner(key_path=self._key_path())

            # Store the public key once per identity: after a purge rotated
            # the key, the new public key must be stored too.
            if not self._public_key_stored:
                self._public_key_stored = self._store_public_key(
                    signer.public_key_hex
                )

            self._signer = signer
            return signer

        except Exception as exc:
            logger.warning(
                "ResearchSignalAggregator: ProvenanceSigner init failed: %s", exc
            )
            return None

    def _store_public_key(self, public_key_hex: str) -> bool:
        """Persist the provenance public key to the database metadata table.

        Returns True on success so callers latch _public_key_stored only
        when the row really exists — a False return means the next write
        batch tries again instead of believing a lie.
        """
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
            return True
        except Exception as exc:
            self._record_degraded("public_key_store")
            logger.warning(
                "ResearchSignalAggregator: could not store public key: %s", exc
            )
            return False

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
        # Rows that will be written WITHOUT a signature (no signer, or this
        # signal's signing failed): counted as degraded, because a dataset
        # that says "every row signed" must be able to say when one is not.
        unsigned = 0
        for s in signals:
            content_hash: str | None = None
            provenance_signature: str | None = None

            if signer is not None:
                try:
                    # Compute a deterministic content hash over the fields
                    # that constitute the signal's evidentiary payload.
                    # page_copy_id (item 6) is deliberately NOT signed: it
                    # is a local link to a copy that may expire or be
                    # deleted, and adding it would change the hash of every
                    # signal ever written. Binding rows to page copies
                    # cryptographically belongs to the attestation item.
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

            if provenance_signature is None:
                unsigned += 1
            rows.append((
                s.signal_id, s.signal_type, s.severity,
                s.confidence, s.evidence_text, s.platform,
                s.jurisdiction, s.company_id, s.job_category,
                s.detected_date.isoformat(),
                s.schema_version, self._consent_version,
                s.posting_hash, content_hash, provenance_signature,
                s.page_copy_id,
            ))

        try:
            with self._get_connection() as conn:
                cursor = conn.executemany(
                    """INSERT OR IGNORE INTO research_signals
                       (signal_id, signal_type, severity, confidence,
                        evidence_text, platform, jurisdiction, company_id,
                        job_category, detected_date, schema_version,
                        consent_version, posting_hash,
                        content_hash, provenance_signature, page_copy_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )
            # rowcount sums executemany's inserts; INSERT OR IGNORE skips a
            # signal already on record (the dedup documented above), and a
            # skipped duplicate is not a new row.
            self._record_written("research_signals", max(cursor.rowcount, 0))
            self._record_degraded("signal_unsigned", unsigned)
            logger.debug(
                "ResearchSignalAggregator | Wrote %d signals to DB", len(signals)
            )
        except Exception as exc:
            self._record_failure("signal_write", len(signals))
            logger.error("ResearchSignalAggregator | Write batch failed: %s", exc)

    def _write_discovery_batch(self, observations: list[DiscoveryObservation]) -> None:
        """Persist discovery-surface observations (§4b): one page row, one
        row per card, one row per candidate, in a single transaction.

        Privacy ruling (item 4c, R1): the candidate-level ``original_url``
        and ``resolved_url`` are NEVER written. The page record was
        deliberately de-identified to host granularity so a user's search
        query cannot be reconstructed; the set of candidate URLs on one
        page IS that query's result set, so persisting full URLs one level
        down would route around the page-level decision. Hosts survive
        (``resolved_host`` — the syndication-topology datum GJ-02/GJ-03
        need); full URLs exist only in process memory for the lifetime of
        the observation.

        Text guard (item 2, the follow-on to R1): link text and card titles
        can RENDER a URL — a visible URL used as the link text, or the
        breadcrumb a results page puts inside its link ("www.indeed.com ›
        q-<search words>-jobs"). Both are written through
        url_evidence.redact_rendered_urls, which cuts any rendered URL to
        its host, so the query cannot reach the record through the text
        columns either. This is the one place discovery text is persisted,
        so every producer passes through it.

        Identity ruling (item 4c, R3): ``page_id`` / ``card_id`` /
        ``candidate_id`` are random surrogate keys minted here, at write
        time. Nothing content-derived is used — page content is measured
        unstable across fetches (the posting_hash precedent) — and the keys
        claim no cross-observation sameness: re-harvesting the same SERP
        yields a new, unlinked page row, and there is deliberately no
        run/session linker. The keys exist so child rows can join to their
        parent, and only that. This diverges from signals' deterministic
        signal_id on purpose: re-observation is not a dedup case here.

        Signing (item 10, C1): these rows are NOT provenance-signed the way
        research_signals rows are. If they should be, the hook is here —
        content-hash each row tuple at this point and store the signature
        in a new column; deliberately not built in this item.
        """
        page_rows: list[tuple] = []
        card_rows: list[tuple] = []
        candidate_rows: list[tuple] = []
        observed_date = date.today().isoformat()
        for obs in observations:
            page_id = uuid.uuid4().hex
            page_rows.append((
                page_id, obs.provider, obs.page_host, obs.page_state,
                int(obs.blocked), obs.architecture, obs.card_count,
                obs.resolved_count, obs.multi_route_count, obs.deferred_count,
                obs.no_destination_count, obs.sponsored_card_count,
                obs.activation_attempts, obs.activation_resolved,
                json.dumps(list(obs.learned_identity)),
                observed_date, RESEARCH_SCHEMA_VERSION,
            ))
            for card in obs.cards:
                card_id = uuid.uuid4().hex
                card_hosts = {card.selected_host}
                for cand in card.candidates:
                    card_hosts.update(_candidate_hosts(cand))
                card_rows.append((
                    card_id, page_id, card.card_index,
                    redact_rendered_urls(card.title, card_hosts),
                    card.resolution_state, card.selected_host,
                    RESEARCH_SCHEMA_VERSION,
                ))
                for cand in card.candidates:
                    candidate_rows.append((
                        uuid.uuid4().hex, card_id, cand.resolved_host,
                        redact_rendered_urls(cand.anchor_text, _candidate_hosts(cand)),
                        cand.source, cand.outcome,
                        cand.rejection_reason,
                        json.dumps(list(cand.ad_evidence)),
                        int(cand.apply_intent), cand.title_overlap,
                        cand.method, RESEARCH_SCHEMA_VERSION,
                    ))
        try:
            with self._get_connection() as conn:
                conn.executemany(
                    """INSERT INTO discovery_pages
                       (page_id, provider, page_host, page_state, blocked,
                        architecture, card_count, resolved_count,
                        multi_route_count, deferred_count,
                        no_destination_count, sponsored_card_count,
                        activation_attempts, activation_resolved,
                        learned_identity, observed_date, schema_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    page_rows,
                )
                conn.executemany(
                    """INSERT INTO discovery_cards
                       (card_id, page_id, card_index, title,
                        resolution_state, selected_host, schema_version)
                       VALUES (?,?,?,?,?,?,?)""",
                    card_rows,
                )
                conn.executemany(
                    """INSERT INTO discovery_candidates
                       (candidate_id, card_id, resolved_host, anchor_text,
                        source, outcome, rejection_reason, ad_evidence,
                        apply_intent, title_overlap, method, schema_version)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    candidate_rows,
                )
            self._record_written("discovery_pages", len(page_rows))
            logger.debug(
                "ResearchSignalAggregator | Wrote %d discovery observation(s) to DB",
                len(observations),
            )
        except Exception as exc:
            self._record_failure("discovery_write", len(observations))
            logger.error(
                "ResearchSignalAggregator | Discovery write batch failed: %s", exc
            )

    def _write_examination_batch(self, examinations: list[_DetectorExamination]) -> None:
        """Persist detector examinations (item 5): one examination row plus
        one row per non-clean outcome, in a single transaction.

        Denominator semantics: an examination is ONE registry pass over ONE
        context. The same posting observed through two pathways (discovery,
        then application form) is two examinations and both rows are kept —
        rates stay unbiased because numerator and denominator scale together.
        The answerable denominator is therefore the EXAMINATION COUNT, and the
        canonical rate query joins detector_outcomes to detector_examinations
        on examination_id.

        "Distinct postings examined" is NOT answerable yet, and this docstring
        previously said it was. posting_hash is carried on every examination
        row and is uniformly NULL today — nothing in AA mints a posting
        identity, which is what EXPECTED_POSTING_IDENTITY_SITES == {} asserts
        in tests/architecture/test_identity_pins.py. Measured on this code:
        five examinations persisted, five with posting_hash IS NULL, and
        COUNT(DISTINCT posting_hash) = 0, because COUNT(DISTINCT ...) skips
        NULLs. The column is here so the per-posting denominator lands
        somewhere the day item 2 mints an identity; until then it answers
        zero, and a query that always answers zero is not an available
        measurement.

        Signals themselves still dedup via deterministic signal_id, so the gap
        between detectors_fired here and rows in research_signals measures
        observation-path redundancy.

        Identity follows the 4c R3 ruling: examination_id / outcome_id are
        random surrogates minted at write time. Nothing content-derived — an
        examination claims no cross-observation sameness. C1 (item 5):
        these rows are deliberately NOT provenance-signed; if item 10 wants
        them signed, the hook is here, mirroring _write_batch's content-hash
        point.

        Roster: stored as a JSON array of the signal_types that ran, in
        registry order, so "clean" remains derivable (roster minus recorded
        outcomes) even after the registry grows and an old examination's 29
        no longer means today's 29.
        """
        exam_rows: list[tuple] = []
        outcome_rows: list[tuple] = []
        examined_date = date.today().isoformat()
        for exam in examinations:
            examination_id = uuid.uuid4().hex
            exam_rows.append((
                examination_id, exam.posting_hash, exam.platform,
                exam.jurisdiction, len(exam.detectors_roster),
                json.dumps(list(exam.detectors_roster)),
                exam.detectors_fired, exam.signals_fired,
                exam.detectors_raised, examined_date, RESEARCH_SCHEMA_VERSION,
                exam.page_copy_id,
            ))
            for outcome in exam.outcomes:
                outcome_rows.append((
                    uuid.uuid4().hex, examination_id, outcome.signal_type,
                    outcome.outcome, outcome.signals_count, outcome.error_class,
                    examined_date, RESEARCH_SCHEMA_VERSION,
                ))
        try:
            with self._get_connection() as conn:
                conn.executemany(
                    """INSERT INTO detector_examinations
                       (examination_id, posting_hash, platform, jurisdiction,
                        detectors_run, detectors_roster, detectors_fired,
                        signals_fired, detectors_raised, examined_date,
                        schema_version, page_copy_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    exam_rows,
                )
                if outcome_rows:
                    conn.executemany(
                        """INSERT INTO detector_outcomes
                           (outcome_id, examination_id, signal_type, outcome,
                            signals_count, error_class, examined_date,
                            schema_version)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        outcome_rows,
                    )
            self._record_written("detector_examinations", len(examinations))
            logger.debug(
                "ResearchSignalAggregator | Wrote %d detector examination(s) to DB",
                len(examinations),
            )
        except Exception as exc:
            self._record_failure("examination_write", len(examinations))
            logger.error(
                "ResearchSignalAggregator | Examination write batch failed: %s", exc
            )
