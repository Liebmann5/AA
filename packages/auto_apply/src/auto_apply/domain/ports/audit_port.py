"""
AuditRepositoryPort — contract for correspondence audit persistence.

This port defines the interface for storing and retrieving audit submission
records. The concrete implementation (SqliteAuditRepository) lives in the
adapters layer and is wired by the composition root.

Architecture: domain/ports/ defines the contract; adapters/ implement it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AuditSubmissionRecord:
    """Tracks one job's paired-submission status for one audit pair.

    This is a pure domain data structure — no I/O, no database details.
    All fields are optional unless noted; None indicates the field is not
    yet known (e.g., submission not yet occurred, callback not yet tracked).

    Attributes:
        pair_id: Which AuditPairDefinition this belongs to.
        job_fingerprint: Structural hash of the job posting (dedup key).
        job_url: The job's application URL (for reference).
        company_id: Anonymized company identifier (if available).
        platform: Source platform (e.g., "greenhouse", "linkedin").
        profile_a_submitted_at: UTC timestamp when profile A's application was submitted.
        profile_b_submitted_at: UTC timestamp when profile B's application was submitted.
        profile_a_callback: Whether profile A received a callback (None = pending/unknown).
        profile_b_callback: Whether profile B received a callback (None = pending/unknown).
        profile_a_interview_offered: Ethical safeguard — triggers immediate withdrawal.
        profile_b_interview_offered: Ethical safeguard — triggers immediate withdrawal.
        withdrawn: Whether this submission pair has been withdrawn.
    """
    pair_id: str
    job_fingerprint: str
    job_url: str
    company_id: str | None = None
    platform: str | None = None
    profile_a_submitted_at: datetime | None = None
    profile_b_submitted_at: datetime | None = None
    profile_a_callback: bool | None = None
    profile_b_callback: bool | None = None
    profile_a_interview_offered: bool = False
    profile_b_interview_offered: bool = False
    withdrawn: bool = False

    @property
    def both_submitted(self) -> bool:
        """True if both profiles' applications have been submitted."""
        return (
            self.profile_a_submitted_at is not None
            and self.profile_b_submitted_at is not None
        )

    @property
    def needs_withdrawal(self) -> bool:
        """True if either profile was offered an interview and not yet withdrawn."""
        return (
            not self.withdrawn
            and (self.profile_a_interview_offered or self.profile_b_interview_offered)
        )


@runtime_checkable
class AuditRepositoryPort(Protocol):
    """Persistence contract for audit submission records.

    Implementations (e.g., SqliteAuditRepository) must provide these methods.
    All methods are expected to be thread-safe and to log errors without
    crashing the caller.
    """

    def save_submission(self, record: AuditSubmissionRecord) -> None:
        """Persist a submission record (insert or update).

        If a record with the same (pair_id, job_fingerprint) exists, it is
        updated; otherwise, a new row is inserted.
        """
        ...

    def load_submissions(self, pair_id: str) -> list[AuditSubmissionRecord]:
        """Load all submission records for a given audit pair.

        Returns an empty list if none exist or on error.
        """
        ...

    def find_submission(
        self, pair_id: str, job_fingerprint: str
    ) -> AuditSubmissionRecord | None:
        """Find a specific submission record, if it exists.

        Returns None if not found or on error.
        """
        ...