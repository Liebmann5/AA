"""
ResearchConsentManager — the consent gate for all research data collection.

ARCHITECTURE: Application-layer service. Depends only on RepositoryPort
(domain port) for persistence — never touches SQLite directly. The
composition root injects a concrete repository adapter.

Default state: research is OFF. No data is collected, no detectors run,
no SignalAggregator is even constructed, until the user explicitly grants
consent through grant_consent(). This is the worst-case-user-safe default
and the FAIR4RS / deon-compliant default (see docs/ETHICS.md).

Consent versioning: CURRENT_CONSENT_VERSION (domain/constants.py) is bumped
whenever data collection practices change. If a user previously consented
to v2.0 and the app now requires v2.1, is_consent_current() returns False
and the UI must re-prompt before research resumes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.ports.consent_repository_port import ConsentRepositoryPort

logger = logging.getLogger(__name__)


class InMemoryConsentRepository:
    """In-memory ConsentRepositoryPort for testing.

    NOT for production use — production must persist to disk so consent
    survives restarts. See SqliteConsentRepository in the adapters layer
    for the real implementation.
    """

    def __init__(self) -> None:
        self._record = ConsentRecord()
        self._purge_count = 0

    def load_consent(self) -> ConsentRecord:
        return self._record

    def save_consent(self, record: ConsentRecord) -> None:
        self._record = record

    def purge_research_data(self) -> int:
        count = self._purge_count
        self._purge_count = 0
        return count

    def _set_purge_count(self, n: int) -> None:
        """Test helper — not part of the port contract."""
        self._purge_count = n


class ResearchConsentManager:
    """Application service governing research data collection consent.

    Usage in composition_root.py:
        consent_manager = ResearchConsentManager(consent_repository)
        if consent_manager.is_active():
            observer = ResearchSignalAggregator(db_path, consent_manager.consent_version)
        else:
            observer = NullResearchObserver()

    Args:
        repository: Persistence adapter for consent records.
    """

    def __init__(self, repository: ConsentRepositoryPort) -> None:
        self._repository = repository

    def is_active(self) -> bool:
        """Return True if research collection should run right now.

        Requires BOTH: consent was granted, AND the consent version matches
        CURRENT_CONSENT_VERSION (re-consent required after policy changes).

        Returns:
            True if research collection is authorized and current.
        """
        record = self._repository.load_consent()
        if not record.granted:
            return False
        if record.withdrawn_at is not None:
            return False
        if record.consent_version != CURRENT_CONSENT_VERSION:
            logger.info(
                "ResearchConsent | Consent version mismatch (have=%s, current=%s) "
                "— re-consent required",
                record.consent_version, CURRENT_CONSENT_VERSION,
            )
            return False
        return True

    def needs_reconsent(self) -> bool:
        """Return True if the user previously consented but the policy has changed.

        Used by the UI to show a "research practices have been updated,
        please review" prompt rather than the full first-time dialog.

        Returns:
            True if a previous consent exists but is for an old version.
        """
        record = self._repository.load_consent()
        return (
            record.granted
            and record.withdrawn_at is None
            and record.consent_version != CURRENT_CONSENT_VERSION
        )

    @property
    def consent_version(self) -> str | None:
        """The consent version the user most recently agreed to, or None."""
        return self._repository.load_consent().consent_version

    def grant_consent(self) -> ConsentRecord:
        """Record that the user has agreed to CURRENT_CONSENT_VERSION.

        Returns:
            The newly created ConsentRecord.
        """
        record = ConsentRecord(
            granted=True,
            consent_version=CURRENT_CONSENT_VERSION,
            granted_at=datetime.now(timezone.utc),
            withdrawn_at=None,
        )
        self._repository.save_consent(record)
        logger.info("ResearchConsent | Consent granted (version=%s)", CURRENT_CONSENT_VERSION)
        return record

    def withdraw_consent(self, purge_data: bool = True) -> int:
        """Withdraw consent and optionally purge all collected research data.

        Args:
            purge_data: If True (default), delete all research signals
                attributable to this user within 24 hours per the data
                retention policy in docs/ETHICS.md. The purge itself is
                synchronous here for simplicity; production may queue it.

        Returns:
            Number of records purged (0 if purge_data=False).
        """
        previous = self._repository.load_consent()
        record = ConsentRecord(
            granted=False,
            consent_version=previous.consent_version,
            granted_at=previous.granted_at,
            withdrawn_at=datetime.now(timezone.utc),
        )
        self._repository.save_consent(record)
        logger.info("ResearchConsent | Consent withdrawn")

        if purge_data:
            count = self._repository.purge_research_data()
            logger.info("ResearchConsent | Purged %d research records", count)
            return count
        return 0