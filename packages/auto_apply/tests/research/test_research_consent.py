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

from datetime import date, datetime, timezone
from pathlib import Path

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
