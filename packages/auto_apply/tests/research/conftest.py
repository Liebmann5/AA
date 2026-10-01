"""Shared fixtures for research module tests.

All fixtures that require SQLite use ``tmp_path`` — no production database
paths are ever written to or read from.
"""

import pytest

from auto_apply.domain.services.signal_detectors.base import DetectionContext
from auto_apply.adapters.secondary.research.signal_aggregator import ResearchSignalAggregator
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.adapters.secondary.research.sqlite_audit_repository import (
    SqliteAuditRepository,
    #AuditSession,
    #AuditApplicationRecord,
)


@pytest.fixture
def minimal_context() -> DetectionContext:
    """A DetectionContext with just enough data to avoid unintended signal firings.

    Detectors that require specific trigger fields must be given overrides in
    individual tests — this fixture is a safe, silent baseline.
    """
    return DetectionContext(
        job_title="Software Engineer",
        job_description="Build and maintain web applications.",
        company_name="Acme Corp",
        location="San Francisco, CA",
        salary_min=100000,
        salary_max=150000,
        first_seen_date=None,
        days_live=None,
        posting_hash="abc123",
    )


@pytest.fixture
def consent_db(tmp_path):
    """A fresh, file‑backed SqliteConsentRepository for consent‑gate tests."""
    return SqliteConsentRepository(
        consent_db_path=tmp_path / "consent.db",
        research_db_path=tmp_path / "research_signals.db",
    )


@pytest.fixture
def aggregator(tmp_path, monkeypatch):
    """A ResearchSignalAggregator backed by a fresh SQLite database.

    The aggregator is *not* started; call ``.start()`` in tests that need the
    background daemon thread.

    The salt is set here rather than in an autouse fixture, so that every
    construction site states the dependency: since item 4a an enabled
    aggregator resolves AA_RESEARCH_SALT at construction and raises
    ResearchSaltError without one. A test that wants the unset case unsets it
    itself — see tests/research/test_research_identity.py.

    The provenance key path is injected for the same reason: without it the
    first flushed batch would write a real Ed25519 private key into the
    developer's actual data directory.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "conftest-research-salt")
    return ResearchSignalAggregator(
        db_path=tmp_path / "research_signals.db",
        consent_version="v2.1",
        flush_interval_seconds=0.1,  # fast flush for tests
        provenance_key_path=tmp_path / "provenance_key.pem",
    )