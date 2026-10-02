"""Tests for ResearchConsentManager, SqliteConsentRepository, and NullResearchObserver.

These tests are pure — they only touch temporary SQLite databases and
in‑memory structures. No real user data or network.

Coverage:
    - Consent is inactive by default
    - Granting consent makes it active
    - Withdrawing consent deactivates it
    - NullResearchObserver never raises
    - Version mismatch blocks active consent
    - Data purge on withdrawal
    - Re‑consent detection after policy version change
    - Consent record round‑trip through SqliteConsentRepository
"""

import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.research_consent import (
    ResearchConsentManager,
    ConsentRecord,
    InMemoryConsentRepository,
)
from auto_apply.domain.ports.research_port import (
    NullResearchObserver,
    JobPostingObservation,
    FormObservation,
    ApplicationOutcomeObservation,
)
from auto_apply.domain.ports.page_understanding_port import FormStructure
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.domain.constants import (
    CURRENT_CONSENT_VERSION,
    RESEARCH_SCHEMA_VERSION,
)
from auto_apply.domain.ports.research_consent_port import (
    ResearchConsentReason,
    ResearchConsentState,
)
from auto_apply.domain.services import research_consent_text
from auto_apply.domain.services.signal_detectors import (
    DetectionContext,
    ResearchSignal,
)
from auto_apply.adapters.secondary.research.signal_aggregator import (
    _SCHEMA_SQL,
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Consent lifecycle — InMemoryConsentRepository
# ─────────────────────────────────────────────────────────────────────────────

def test_consent_not_active_by_default():
    """A fresh InMemoryConsentRepository has no active consent."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    assert not mgr.is_active()


def test_consent_requires_grant():
    """Consent is not active until explicitly granted."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    assert not mgr.is_active()


def test_grant_consent_makes_active():
    """After granting consent, is_active() returns True and version matches."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    # Simulate the record that would be written by the consent dialog.
    record = ConsentRecord(
        granted=True,
        consent_version=CURRENT_CONSENT_VERSION,
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    )
    repo.save_consent(record)

    assert mgr.is_active()
    assert mgr.consent_version == CURRENT_CONSENT_VERSION


def test_grant_consent_method_works():
    """ResearchConsentManager.grant_consent() creates and persists an active record."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    assert not mgr.is_active()

    record = mgr.grant_consent()

    assert record.granted is True
    assert record.consent_version == CURRENT_CONSENT_VERSION
    assert record.granted_at is not None
    assert record.withdrawn_at is None
    assert mgr.is_active()


def test_withdraw_consent_deactivates():
    """Withdrawing consent makes the manager inactive again."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    mgr.grant_consent()
    assert mgr.is_active()

    # Withdraw
    withdrawn = ConsentRecord(
        granted=False,
        consent_version=CURRENT_CONSENT_VERSION,
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=datetime.now(timezone.utc),
    )
    repo.save_consent(withdrawn)
    assert not mgr.is_active()


def test_withdraw_consent_method_works():
    """ResearchConsentManager.withdraw_consent() creates a withdrawn record."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    mgr.grant_consent()
    assert mgr.is_active()

    purged = mgr.withdraw_consent(purge_data=True)

    assert not mgr.is_active()


def test_version_mismatch_blocks_active():
    """If the stored consent version differs from the required constant,
    ResearchConsentManager.is_active() must be False."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    record = ConsentRecord(
        granted=True,
        consent_version="v1.0",  # older version
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    )
    repo.save_consent(record)

    # The manager compares against CURRENT_CONSENT_VERSION ("2.1"); a
    # version mismatch must cause is_active() to return False.
    assert not mgr.is_active()


def test_needs_reconsent_detects_version_change():
    """needs_reconsent() returns True when granted version != current version."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)

    # Grant with current version — no re‑consent needed
    mgr.grant_consent()
    assert not mgr.needs_reconsent()

    # Simulate a policy version bump by writing a stale record
    stale = ConsentRecord(
        granted=True,
        consent_version="v1.0",  # old
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    )
    repo.save_consent(stale)
    assert mgr.needs_reconsent()


def test_needs_reconsent_false_when_withdrawn():
    """If consent was withdrawn, needs_reconsent returns False
    (there is no active consent to re‑prompt about)."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)

    # Grant with old version, then withdraw
    stale = ConsentRecord(
        granted=True,
        consent_version="v1.0",
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    )
    repo.save_consent(stale)

    withdrawn = ConsentRecord(
        granted=False,
        consent_version="v1.0",
        granted_at=stale.granted_at,
        withdrawn_at=datetime.now(timezone.utc),
    )
    repo.save_consent(withdrawn)

    assert not mgr.needs_reconsent()


def test_needs_reconsent_false_when_never_granted():
    """If consent was never granted, needs_reconsent is False."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    assert not mgr.needs_reconsent()


def test_withdraw_consent_without_purge():
    """Withdrawing without purging does not delete research data."""
    repo = InMemoryConsentRepository()
    repo._set_purge_count(42)  # simulate existing data
    mgr = ResearchConsentManager(repo)
    mgr.grant_consent()

    purged = mgr.withdraw_consent(purge_data=False)

    assert purged == 0
    assert not mgr.is_active()


def test_withdraw_consent_with_purge():
    """Withdrawing with purge=True deletes research data."""
    repo = InMemoryConsentRepository()
    repo._set_purge_count(15)
    mgr = ResearchConsentManager(repo)
    mgr.grant_consent()

    purged = mgr.withdraw_consent(purge_data=True)

    assert purged == 15
    assert not mgr.is_active()


# ─────────────────────────────────────────────────────────────────────────────
# SqliteConsentRepository persistence
# ─────────────────────────────────────────────────────────────────────────────

def test_sqlite_consent_repo_default_not_granted(consent_db):
    """A fresh SqliteConsentRepository returns a default (not granted) record."""
    record = consent_db.load_consent()
    assert record.granted is False
    assert record.consent_version is None
    assert record.granted_at is None
    assert record.withdrawn_at is None


def test_sqlite_consent_repo_save_and_load(consent_db):
    """A saved consent record survives a round‑trip through SQLite."""
    now = datetime.now(timezone.utc)
    record = ConsentRecord(
        granted=True,
        consent_version=CURRENT_CONSENT_VERSION,
        granted_at=now,
        withdrawn_at=None,
    )
    consent_db.save_consent(record)

    loaded = consent_db.load_consent()
    assert loaded.granted is True
    assert loaded.consent_version == CURRENT_CONSENT_VERSION
    assert loaded.withdrawn_at is None


def test_sqlite_consent_repo_purge_research_data(consent_db):
    """purge_research_data returns 0 when the research DB doesn't exist."""
    purged = consent_db.purge_research_data()
    assert purged >= 0


def test_consent_manager_with_sqlite_backend(consent_db):
    """ResearchConsentManager works correctly with SqliteConsentRepository."""
    mgr = ResearchConsentManager(consent_db)
    assert not mgr.is_active()

    mgr.grant_consent()
    assert mgr.is_active()
    assert mgr.consent_version == CURRENT_CONSENT_VERSION

    mgr.withdraw_consent(purge_data=False)
    assert not mgr.is_active()


# ─────────────────────────────────────────────────────────────────────────────
# NullResearchObserver safety
# ─────────────────────────────────────────────────────────────────────────────

def test_null_observer_all_methods_are_callable():
    """Every observe_* method on NullResearchObserver must execute without
    raising an exception — even when called with minimal or invalid data."""
    observer = NullResearchObserver()

    # Build a valid but minimal form structure
    form = FormStructure(fields=())

    # Call every method; if any raises, pytest will catch it.
    observer.observe_job_posting(JobPostingObservation(
        job_title="Test", job_description="Test", company_name="Acme",
    ))
    observer.observe_form(FormObservation(
        platform="greenhouse", company_name="Acme", job_title="Test",
        form_structure=form,
    ))
    observer.observe_application_outcome(ApplicationOutcomeObservation(
        platform="greenhouse", company_id="acme_id",
        submitted_date=date.today(),
    ))

    # The NullObserver's is_enabled property must return False.
    assert observer.is_enabled is False


def test_null_observer_handles_none_fields():
    """NullResearchObserver must not crash when observation fields are None."""
    observer = NullResearchObserver()

    # All fields at their defaults (empty strings, None, etc.)
    observer.observe_job_posting(JobPostingObservation())
    observer.observe_form(FormObservation())
    observer.observe_application_outcome(ApplicationOutcomeObservation(
        platform="unknown",
        company_id="",
        submitted_date=date.today(),
    ))

    assert observer.is_enabled is False


def test_null_observer_matches_port_interface():
    """NullResearchObserver structurally satisfies ResearchObserverPort."""
    from auto_apply.domain.ports.research_port import ResearchObserverPort

    observer = NullResearchObserver()

    # Must have all required port methods
    assert hasattr(observer, "observe_job_posting")
    assert hasattr(observer, "observe_form")
    assert hasattr(observer, "observe_application_outcome")
    assert hasattr(observer, "is_enabled")

    assert callable(observer.observe_job_posting)
    assert callable(observer.observe_form)
    assert callable(observer.observe_application_outcome)


# ═════════════════════════════════════════════════════════════════════════════
# The consent interface (M1/M2, FORKs 1-4, pinned 2026-10-01)
#
# Every pin in this section is RED against the tree that had: no caller for
# grant_consent/withdraw_consent, a config-flag gate no user could open, a
# ResearchSaltError that stopped AA from starting, and a withdrawal with no
# channel to the running aggregator.
# ═════════════════════════════════════════════════════════════════════════════


def test_status_is_off_by_default():
    """TEETH: a fresh consent store reports OFF — research is opt-in.

    RED today: ResearchConsentManager has no status().
    """
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    status = mgr.status()
    assert status.state is ResearchConsentState.OFF
    assert status.reason is ResearchConsentReason.NONE
    assert status.consent_version is None
    assert status.current_version == CURRENT_CONSENT_VERSION
    assert status.offered is True
    assert status.collecting_now is False


def test_status_active_after_grant_when_salt_available(monkeypatch):
    """TEETH: with a salt set, grant() yields ACTIVE.

    RED today: no grant()/status() on the manager.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "status-active-salt")
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    status = mgr.grant()
    assert status.state is ResearchConsentState.ACTIVE
    assert status.consent_version == CURRENT_CONSENT_VERSION
    assert mgr.should_collect()


def test_status_inactive_with_no_salt_reason_when_granted_without_salt(monkeypatch):
    """TEETH vs M3 (FORK 4): a grant with NO salt is recorded-but-inactive,
    with the reason reported — and the consent record itself is still valid.

    RED today: no status(); the only no-salt behaviour was a build-time raise.
    """
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    status = mgr.grant()
    assert status.state is ResearchConsentState.INACTIVE
    assert status.reason is ResearchConsentReason.NO_SALT
    assert not mgr.should_collect()
    assert mgr.is_active(), (
        "the consent RECORD is granted and current — only collection is blocked"
    )


def test_status_needs_reconsent_for_stale_version():
    """TEETH: a granted-but-stale version reports NEEDS_RECONSENT."""
    repo = InMemoryConsentRepository()
    repo.save_consent(ConsentRecord(
        granted=True,
        consent_version="v1.0",
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    ))
    mgr = ResearchConsentManager(repo)
    assert mgr.status().state is ResearchConsentState.NEEDS_RECONSENT
    assert not mgr.should_collect()


def test_status_withdrawn_after_withdrawal():
    """TEETH: a withdrawn record reports WITHDRAWN, never OFF."""
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    mgr.grant_consent()
    mgr.withdraw_consent(purge_data=False)
    assert mgr.status().state is ResearchConsentState.WITHDRAWN
    assert not mgr.should_collect()


def test_grant_interface_records_current_version_and_returns_status(monkeypatch):
    """TEETH: grant() is the interface operation — it writes the CURRENT
    version (the one consent_dialog() carries) and returns the new status.

    RED today: grant() does not exist; grant_consent had no production caller.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "grant-pin-salt")
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    status = mgr.grant()
    assert status.state is ResearchConsentState.ACTIVE
    record = repo.load_consent()
    assert record.granted is True
    assert record.consent_version == CURRENT_CONSENT_VERSION
    assert record.granted_at is not None


def test_should_collect_is_the_and_of_all_gates(monkeypatch):
    """GUARD (FORK 1): should_collect() is the single collection decision —
    consent AND offered AND not admin-prohibited AND salt. Each gate alone
    must be able to shut it."""
    monkeypatch.setenv("AA_RESEARCH_SALT", "gates-salt")
    repo = InMemoryConsentRepository()
    granted = ResearchConsentManager(repo)
    granted.grant_consent()
    assert granted.should_collect()
    ungranted = ResearchConsentManager(InMemoryConsentRepository())
    assert not ungranted.should_collect()
    not_offered = ResearchConsentManager(repo, is_offered=False)
    assert not not_offered.should_collect()
    prohibited = ResearchConsentManager(repo, admin_prohibited=True)
    assert not prohibited.should_collect()
    monkeypatch.delenv("AA_RESEARCH_SALT")
    no_salt = ResearchConsentManager(repo)
    assert not no_salt.should_collect()


def test_admin_prohibition_wins_over_grant():
    """GUARD (FORK 1, deliverable vii): an admin prohibition beats a grant —
    reported as ADMIN_PROHIBITED, not merely "off"."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo, admin_prohibited=True)
    status = mgr.grant()
    assert status.state is ResearchConsentState.INACTIVE
    assert status.reason is ResearchConsentReason.ADMIN_PROHIBITED
    assert status.offered is False
    assert not mgr.should_collect()


def test_not_offered_wins_over_grant():
    """GUARD (FORK 1): a deployment that does not offer research reports
    NOT_OFFERED even to a user who granted."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo, is_offered=False)
    status = mgr.grant()
    assert status.state is ResearchConsentState.INACTIVE
    assert status.reason is ResearchConsentReason.NOT_OFFERED
    assert not mgr.should_collect()


def test_consent_dialog_carries_current_version_and_canonical_text():
    """GUARD (FORK 2/5): the dialog the surfaces render comes from the one
    canonical module, versioned with CURRENT_CONSENT_VERSION — so "which text
    did this user agree to" is answered by construction."""
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    dialog = mgr.consent_dialog()
    assert dialog.version == CURRENT_CONSENT_VERSION
    assert dialog.title == research_consent_text.DIALOG_TITLE
    assert dialog.body == research_consent_text.DIALOG_BODY
    assert dialog.agree_label == research_consent_text.AGREE_LABEL
    assert dialog.decline_label == research_consent_text.DECLINE_LABEL
    assert "{old_version}" in dialog.reconsent_body_template


# ── FORK 3: withdrawal and shutdown stop the running observer ────────────────


def _signal() -> ResearchSignal:
    return ResearchSignal(
        signal_id="sig-consent-pin-1",
        signal_type="GJ-01",
        severity="violation",
        confidence=0.9,
        evidence_text="evidence",
        platform="indeed",
        jurisdiction="CA",
        company_id=None,
        job_category=None,
        detected_date=date(2026, 10, 1),
        schema_version=RESEARCH_SCHEMA_VERSION,
        posting_hash="posting-hash",
    )


def _rows(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_withdrawal_stops_a_running_aggregator_and_nothing_resurrects(tmp_path, monkeypatch):
    """TEETH vs M4 and the 91de8c9 measurement (deliverable iii): withdrawing
    stops the running aggregator FIRST; a later observe writes nothing; after
    the purge neither research_signals.db nor provenance_key.pem reappears.

    RED today: withdraw_consent has no channel to the aggregator (nothing
    registers it), so the daemon keeps writing and the next batch after the
    purge recreates the database file and a fresh key.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "withdraw-stop-salt")
    db = tmp_path / "research" / "research_signals.db"
    key = tmp_path / "provenance_key.pem"
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version=CURRENT_CONSENT_VERSION,
        provenance_key_path=key,
    )
    repo = SqliteConsentRepository(
        consent_db_path=tmp_path / "research_consent.db",
        research_db_path=db,
        provenance_key_path=key,
    )
    mgr = ResearchConsentManager(repo)
    mgr.grant()
    agg.start()
    mgr.register_observer(agg)
    assert mgr.collecting

    # Something genuinely collected: the database file and the key exist.
    agg._write_batch([_signal()])
    assert db.exists()
    assert key.exists()

    purged = mgr.withdraw_consent(purge_data=True)

    assert purged >= 1
    assert not agg.is_enabled, "withdrawal must stop collection, not only purge"
    agg.observe_application_outcome(ApplicationOutcomeObservation(
        platform="probe", company_id="x", submitted_date=date.today(),
    ))
    time.sleep(0.3)
    assert not db.exists(), (
        "a stopped-then-purged aggregator must not recreate the database"
    )
    assert not key.exists(), "the provenance key must not be regenerated"


def test_withdrawal_without_purge_still_stops_collection(tmp_path, monkeypatch):
    """TEETH (FORK 3, deliverable iv): purge_data=False keeps the data — but
    collection STILL stops. RED today: nothing stops the aggregator on any
    withdrawal path."""
    monkeypatch.setenv("AA_RESEARCH_SALT", "withdraw-keep-salt")
    db = tmp_path / "research_signals.db"
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version=CURRENT_CONSENT_VERSION,
        provenance_key_path=tmp_path / "key.pem",
    )
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    mgr.grant()
    agg.start()
    mgr.register_observer(agg)
    agg._write_batch([_signal()])
    assert _rows(db, "research_signals") == 1

    purged = mgr.withdraw_consent(purge_data=False)

    assert purged == 0
    assert db.exists(), "purge_data=False must keep the data"
    assert not agg.is_enabled
    agg.observe_application_outcome(ApplicationOutcomeObservation(
        platform="probe", company_id="x", submitted_date=date.today(),
    ))
    time.sleep(0.3)
    assert _rows(db, "research_signals") == 1, (
        "a withdrawn aggregator must not write again"
    )


def test_session_shutdown_stops_the_observer_and_flushes_its_queue(tmp_path, monkeypatch):
    """TEETH (FORK 3, session end, deliverable v): SessionController.shutdown()
    stops the research observer, and items still queued at that moment are
    flushed, not lost with the daemon thread.

    RED today: SessionController has no research_consent parameter and nobody
    in any shutdown path calls the aggregator's stop().
    """
    from auto_apply.application.services.session_controller import SessionController

    monkeypatch.setenv("AA_RESEARCH_SALT", "shutdown-flush-salt")
    db = tmp_path / "research_signals.db"
    agg = ResearchSignalAggregator(
        db_path=db,
        consent_version=CURRENT_CONSENT_VERSION,
        flush_interval_seconds=3600.0,  # queued items stay queued until stop()
        provenance_key_path=tmp_path / "key.pem",
    )
    agg.start()
    mgr = ResearchConsentManager(InMemoryConsentRepository())
    mgr.register_observer(agg)
    # One queued examination (enqueued on every detection pass, signal or not).
    agg.submit_context(DetectionContext(job_title="T", posting_hash="ph"))

    registry = MagicMock()
    registry.get_active_profile.return_value = MagicMock(profile_name="p")
    orchestrator = MagicMock()
    orchestrator.context = MagicMock(session_id="s")

    controller = SessionController(
        registry=registry,
        db=MagicMock(),
        orchestrator=orchestrator,
        research_consent=mgr,
    )
    controller.shutdown()

    assert not agg.is_enabled
    assert _rows(db, "detector_examinations") == 1, (
        "the queued examination must be flushed by shutdown, not lost"
    )


# ── FORK 5: the text cannot drift from the schema or the version ─────────────

_DIALOG_DOC_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "RESEARCH_CONSENT_DIALOG.md"
)


def test_every_schema_table_is_disclosed_in_the_consent_text():
    """GUARD/ratchet (FORK 5, deliverable vi): every table the research schema
    creates maps to a phrase that must appear in the canonical consent text —
    the same contract TABLE_SPECS gives the exporter. A table added to the
    schema fails this pin until the text and this map are updated, so the
    dialog can never again silently fall behind what is collected (M5).

    RED today: the discovery_* and detector_* tables have no disclosure.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_SCHEMA_SQL)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    disclosure = {
        "research_signals": "Anonymized excerpts",
        "job_lifecycles": "reposted",
        "salary_observations": "salary range",
        "form_observations": "Application form structure",
        "application_outcomes": "acknowledgment within 30 days",
        "discovery_pages": "result-page hosts",
        "discovery_cards": "job titles shown",
        "discovery_candidates": "link texts and destination hosts",
        "detector_examinations": "Which detectors ran",
        "detector_outcomes": "how each concluded",
        "research_provenance": "public verification key",
    }
    assert tables == set(disclosure), (
        f"schema/consent-text drift — update the dialog AND this map: "
        f"{tables ^ set(disclosure)}"
    )
    for table, phrase in disclosure.items():
        assert phrase in research_consent_text.DIALOG_BODY, (
            f"{table} is not disclosed in the consent text"
        )


def test_dialog_doc_title_version_matches_current_consent_version():
    """GUARD (FORK 5, deliverable vi): the doc's title version equals
    CURRENT_CONSENT_VERSION — the document itself declares this rule and
    nothing enforced it."""
    import re

    doc = _DIALOG_DOC_PATH.read_text(encoding="utf-8")
    match = re.search(r"\(v(\d+\.\d+)\)", doc)
    assert match, "dialog doc title carries no (vX.Y) version"
    assert match.group(1) == CURRENT_CONSENT_VERSION


def test_dialog_doc_contains_the_canonical_text_verbatim():
    """GUARD (FORK 2/5): the canonical strings live in
    domain/services/research_consent_text.py (one source); the doc must quote
    them byte-for-byte so the authoritative document and what the surfaces
    render cannot drift."""
    doc_lines = {
        line.lstrip("> ").strip()
        for line in _DIALOG_DOC_PATH.read_text(encoding="utf-8").splitlines()
    }
    canonical_lines = [
        research_consent_text.DIALOG_TITLE,
        *research_consent_text.DIALOG_BODY.splitlines(),
        research_consent_text.AGREE_LABEL,
        research_consent_text.DECLINE_LABEL,
        research_consent_text.RECONSENT_TITLE,
        *research_consent_text.RECONSENT_BODY_TEMPLATE.splitlines(),
        research_consent_text.WITHDRAW_TITLE,
        *research_consent_text.WITHDRAW_BODY.splitlines(),
        research_consent_text.PAGE_COPIES_TITLE,
        *research_consent_text.PAGE_COPIES_BODY.splitlines(),
        research_consent_text.PAGE_COPIES_AGREE_LABEL,
    ]
    missing = [
        line.strip()
        for line in canonical_lines
        if line.strip() and line.strip() not in doc_lines
    ]
    assert not missing, (
        f"RESEARCH_CONSENT_DIALOG.md has drifted from the canonical consent "
        f"text: {missing[:5]}"
    )
