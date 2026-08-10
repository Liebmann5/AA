"""Persistence contract for research-consent records.

RELOCATED from ``application/services/research_consent`` (2026-08-07), for the
same reason as ``ConsentRecord``: the adapter that implements this Protocol
(``adapters/secondary/research/sqlite_consent_repository``) had to import it
from the application layer, which is the one import direction the architecture
forbids for adapters.

A port describing what an adapter must provide belongs beside the other ports,
not inside the service that happens to be its first consumer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_apply.domain.models.consent import ConsentRecord


@runtime_checkable
class ConsentRepositoryPort(Protocol):
    """Persistence contract for consent records.

    Implementations store this in the user's local profile data
    (e.g. profile.json or a small SQLite table) — never transmitted anywhere.
    """

    def load_consent(self) -> ConsentRecord:
        """Load the current consent record. Returns default (not granted) if none exists."""
        ...

    def save_consent(self, record: ConsentRecord) -> None:
        """Persist a consent record."""
        ...

    def purge_research_data(self) -> int:
        """Delete all research signal data associated with this user.

        Returns:
            Number of records deleted (for user-facing confirmation).
        """
        ...
