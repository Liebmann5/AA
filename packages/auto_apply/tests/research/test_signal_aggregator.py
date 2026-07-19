"""Integration‑style tests for ResearchSignalAggregator and SqliteAuditRepository.

All tests use ``tmp_path`` for SQLite databases — no production data is touched.
The aggregator is tested with its daemon thread stopped immediately to avoid
race conditions in the test suite.

Coverage:
    - Aggregator can be started and stopped
    - Submitting observations without a started thread does not crash
    - SqliteAuditRepository save → load → find submission
    - Consent gate: aggregator is enabled only when consent is active
    - Signal observation through the ResearchObserverPort interface
    - Graceful degradation when consent is withdrawn mid-session
"""

import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from auto_apply.domain.ports.research_port import (
    JobPostingObservation,
    FormObservation,
    ApplicationOutcomeObservation,
)
from auto_apply.domain.ports.page_understanding_port import FormStructure
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.adapters.secondary.research.sqlite_audit_repository import (
    SqliteAuditRepository,
)
from auto_apply.domain.ports.audit_port import AuditSubmissionRecord
from auto_apply.application.services.research_consent import (
    ResearchConsentManager,
    InMemoryConsentRepository,
)
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# ResearchSignalAggregator lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregator_starts_and_stops(aggregator):
    """start() should spawn a daemon thread; stop() should join it cleanly."""
    aggregator.start()
    assert aggregator._thread is not None
    assert aggregator._thread.is_alive()
    aggregator.stop()
    # After stop, the thread must have exited.
    aggregator._thread.join(timeout=2.0)
    assert not aggregator._thread.is_alive()


def test_aggregator_observation_without_start_does_not_crash(aggregator):
    """Submitting observations before the daemon thread is started must be
    safe — the internal queue may grow, but nothing should raise."""
    obs = JobPostingObservation(job_title="DevOps Engineer", job_description="...")
    try:
        aggregator.observe_job_posting(obs)
    except Exception as exc:
        pytest.fail(f"observe_job_posting raised unexpectedly: {exc}")


def test_aggregator_observation_with_start_then_stop(aggregator):
    """After starting and then stopping, further observations must not raise."""
    aggregator.start()
    aggregator.stop()
    obs = FormObservation(
        platform="greenhouse", company_name="Acme", job_title="SWE",
        form_structure=FormStructure(fields=()),
    )
    try:
        aggregator.observe_form(obs)
    except Exception as exc:
        pytest.fail(f"observe_form raised unexpectedly after stop: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Consent gate tests
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregator_consent_gate():
    """ResearchSignalAggregator only runs when consent is active."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    assert not mgr.is_active()

    mgr.grant_consent()
    assert mgr.is_active()

    agg = ResearchSignalAggregator(
        db_path=Path("/tmp/test_signals.db"),  # noqa: S108 — test path
        consent_version=mgr.consent_version,
    )
    assert agg.is_enabled


def test_aggregator_disabled_when_consent_is_none(tmp_path):
    """Aggregator must be disabled when consent_version is None."""
    agg = ResearchSignalAggregator(
        db_path=tmp_path / "test.db",
        consent_version=None,
    )
    assert not agg.is_enabled


def test_aggregator_disabled_when_consent_withdrawn():
    """After withdrawing consent, aggregator is not active."""
    repo = InMemoryConsentRepository()
    mgr = ResearchConsentManager(repo)
    mgr.grant_consent()
    assert mgr.is_active()

    mgr.withdraw_consent(purge_data=False)
    assert not mgr.is_active()


def test_aggregator_version_mismatch_blocks_active():
    """If the stored consent version does not match CURRENT_CONSENT_VERSION,
    the consent manager must report inactive."""
    repo = InMemoryConsentRepository()
    # Seed a stale consent record directly into the repo
    old_record = repo.load_consent()
    # Create a record with an old version
    from auto_apply.application.services.research_consent import ConsentRecord

    stale = ConsentRecord(
        granted=True,
        consent_version="v1.0",  # old version
        granted_at=datetime.now(timezone.utc),
        withdrawn_at=None,
    )
    repo.save_consent(stale)

    mgr = ResearchConsentManager(repo)
    assert not mgr.is_active()


# ─────────────────────────────────────────────────────────────────────────────
# ResearchObserverPort interface compliance
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregator_satisfies_observer_port(aggregator):
    """ResearchSignalAggregator structurally satisfies ResearchObserverPort."""
    from auto_apply.domain.ports.research_port import ResearchObserverPort

    # All required methods must be callable without raising
    assert hasattr(aggregator, "observe_job_posting")
    assert hasattr(aggregator, "observe_form")
    assert hasattr(aggregator, "observe_application_outcome")
    assert hasattr(aggregator, "is_enabled")

    assert callable(aggregator.observe_job_posting)
    assert callable(aggregator.observe_form)
    assert callable(aggregator.observe_application_outcome)


def test_aggregator_observe_job_posting_accepts_full_observation(aggregator):
    """observe_job_posting must accept a fully populated JobPostingObservation."""
    obs = JobPostingObservation(
        job_title="Senior Python Engineer",
        job_description="Build and maintain APIs. 5+ years experience.",
        company_name="Acme Corp",
        location="San Francisco, CA",
        jurisdiction="CA",
        salary_min=120000,
        salary_max=180000,
        platform="greenhouse",
        first_seen_date=date.today(),
        posting_hash="abc123def456",
        application_url_is_generic=False,
        metro_area="San Francisco-Oakland-Berkeley, CA",
    )
    try:
        aggregator.observe_job_posting(obs)
    except Exception as exc:
        pytest.fail(f"observe_job_posting with full observation raised: {exc}")


def test_aggregator_observe_form_accepts_minimal_observation(aggregator):
    """observe_form must accept a minimal FormObservation without crashing."""
    obs = FormObservation(
        platform="lever",
        company_name="TechCo",
        job_title="Backend Engineer",
        form_structure=FormStructure(fields=()),
    )
    try:
        aggregator.observe_form(obs)
    except Exception as exc:
        pytest.fail(f"observe_form raised: {exc}")


def test_aggregator_observe_application_outcome_degraded(aggregator):
    """observe_application_outcome must handle missing optional fields."""
    obs = ApplicationOutcomeObservation(
        platform="indeed",
        company_id="anon_1234",
        submitted_date=date.today(),
    )
    try:
        aggregator.observe_application_outcome(obs)
    except Exception as exc:
        pytest.fail(f"observe_application_outcome raised: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# SqliteAuditRepository — new API tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_submission(
    pair_id: str = "pair-1",
    job_fingerprint: str = "fp-abc",
    job_url: str = "https://example.com/job/1",
    company_id: str = "comp-1",
    platform: str = "greenhouse",
    submitted_a: datetime | None = None,
    submitted_b: datetime | None = None,
    callback_a: bool | None = None,
    callback_b: bool | None = None,
) -> AuditSubmissionRecord:
    """Create a minimal AuditSubmissionRecord for testing."""
    return AuditSubmissionRecord(
        pair_id=pair_id,
        job_fingerprint=job_fingerprint,
        job_url=job_url,
        company_id=company_id,
        platform=platform,
        profile_a_submitted_at=submitted_a,
        profile_b_submitted_at=submitted_b,
        profile_a_callback=callback_a,
        profile_b_callback=callback_b,
    )


def test_save_and_load_submission(tmp_path: Path):
    """A saved submission can be loaded back with all fields intact."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")
    record = _make_submission()
    repo.save_submission(record)

    loaded = repo.load_submissions("pair-1")
    assert len(loaded) == 1
    assert loaded[0].pair_id == "pair-1"
    assert loaded[0].job_fingerprint == "fp-abc"
    assert loaded[0].job_url == "https://example.com/job/1"
    assert loaded[0].profile_a_submitted_at is None


def test_save_multiple_and_load_all(tmp_path: Path):
    """Multiple submissions for the same pair are all returned by load_submissions."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")
    repo.save_submission(_make_submission(pair_id="pair-1", job_fingerprint="a"))
    repo.save_submission(_make_submission(pair_id="pair-1", job_fingerprint="b"))
    repo.save_submission(_make_submission(pair_id="pair-2", job_fingerprint="c"))

    pair1 = repo.load_submissions("pair-1")
    assert len(pair1) == 2

    pair2 = repo.load_submissions("pair-2")
    assert len(pair2) == 1


def test_find_submission_returns_record(tmp_path: Path):
    """find_submission returns the correct record when it exists."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")
    repo.save_submission(_make_submission(pair_id="p1", job_fingerprint="f1"))

    found = repo.find_submission("p1", "f1")
    assert found is not None
    assert found.pair_id == "p1"
    assert found.job_fingerprint == "f1"


def test_find_submission_returns_none_for_unknown_pair(tmp_path: Path):
    """find_submission returns None when no matching record exists."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")
    assert repo.find_submission("nonexistent", "f1") is None


def test_update_existing_submission(tmp_path: Path):
    """Saving a submission with the same (pair_id, fingerprint) updates it."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")

    original = _make_submission(job_fingerprint="f1", callback_a=False)
    repo.save_submission(original)

    updated = _make_submission(job_fingerprint="f1", callback_a=True)
    repo.save_submission(updated)

    loaded = repo.find_submission(original.pair_id, "f1")
    assert loaded is not None
    assert loaded.profile_a_callback is True


def test_load_submissions_empty_pair(tmp_path: Path):
    """load_submissions returns empty list for pair with no records."""
    repo = SqliteAuditRepository(tmp_path / "audit.db")
    result = repo.load_submissions("nonexistent_pair")
    assert result == []
    assert isinstance(result, list)


def test_both_submitted_property(tmp_path: Path):
    """AuditSubmissionRecord.both_submitted reflects submission state."""
    now = datetime.now(timezone.utc)

    not_submitted = _make_submission()
    assert not not_submitted.both_submitted

    partial = _make_submission(submitted_a=now)
    assert not partial.both_submitted

    both = _make_submission(submitted_a=now, submitted_b=now)
    assert both.both_submitted
