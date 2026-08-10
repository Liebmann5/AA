"""A user's research-consent decision, as a value.

RELOCATED from ``application/services/research_consent`` (2026-08-07).

``ConsentRecord`` is a frozen dataclass with no behaviour and no dependencies
beyond ``datetime``. It was declared inside an application service, which meant
``adapters/secondary/research/sqlite_consent_repository.py`` — the thing that
persists it — had to import upward across the layer boundary to name the type
it stores.

Consent is a domain concept in this codebase's own terms: whether a user has
authorised research collection governs behaviour in the domain, the application
layer and the adapters alike. A type that three layers agree on belongs in the
one they all already depend on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConsentRecord:
    """A user's research consent decision.

    Attributes:
        granted: Whether research collection is currently authorized.
        consent_version: The version of the consent dialog the user agreed to.
        granted_at: UTC timestamp when consent was granted (None if never granted).
        withdrawn_at: UTC timestamp when consent was withdrawn (None if active).
    """

    granted: bool = False
    consent_version: str | None = None
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None
