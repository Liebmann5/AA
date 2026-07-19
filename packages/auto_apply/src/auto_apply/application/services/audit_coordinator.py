"""
AuditCoordinator — automated correspondence audit framework.

Implements the methodology from the Research Module Specification
("Correspondence Audit Framework" section): paired profile applications
that differ in exactly one demographic-coded signal, submitted to the same
jobs, with callback rate differences measured via Fisher's exact test and
Wilson confidence intervals.

ETHICAL SAFEGUARDS (mandatory, non-negotiable — see docs/ETHICS.md):
  1. Only operates when the user has explicitly enabled audit mode AND
     research consent is active (checked via ResearchConsentManager).
  2. Any submission that progresses to interview stage is IMMEDIATELY
     withdrawn (withdraw_if_interview_offered) — fake applications must
     never occupy a real interview slot.
  3. All audit pairs and protocols must be pre-registered (this module
     provides export_protocol_for_preregistration() for OSF submission)
     BEFORE the coordinator begins scheduling submissions.
  4. Jurisdictions that prohibit audit studies are excluded via
     EXCLUDED_JURISDICTIONS — checked before scheduling.

ARCHITECTURE: Application-layer service. Depends only on:
  - AuditRepositoryPort (domain port, persistence)
  - WorkQueuePort (domain port, to enqueue paired APPLY tasks)
  - ResearchConsentManager (application service, consent gate)
Never imports adapters or infrastructure directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Protocol, runtime_checkable

from auto_apply.application.services.research_consent import ResearchConsentManager
from auto_apply.domain.services.research_statistics import (
    fisher_exact_2x2,
    wilson_score_interval,
)

logger = logging.getLogger(__name__)


# Jurisdictions where correspondence/audit studies using fictitious applications
# are legally prohibited or carry significant legal risk. Jobs in these
# jurisdictions are never selected for paired audit submission.
# This list must be reviewed periodically — it is intentionally conservative.
EXCLUDED_JURISDICTIONS: frozenset[str] = frozenset({
    # Placeholder — populate based on legal review per jurisdiction.
    # No jurisdictions are hardcoded as "safe"; this is an exclusion list
    # that grows as legal review identifies prohibitions.
})


@dataclass(frozen=True)
class AuditPairDefinition:
    """A matched pair of user profiles differing in exactly one signal.

    Attributes:
        pair_id: Unique identifier for this pair (used in pre-registration).
        dimension: What differs between profiles, e.g. "racial_name_signal",
            "gender_name_signal", "graduation_year_signal",
            "disability_disclosure_signal".
        profile_a_id: Identifier for the first profile in the pair.
        profile_b_id: Identifier for the second profile in the pair.
        profile_a_label: Human-readable label for profile A (for reports),
            e.g. "White-coded name (James Anderson)".
        profile_b_label: Human-readable label for profile B,
            e.g. "Black-coded name (Jamal Washington)".
        description: Full description of what is held constant and what differs.
            This text is exported verbatim to the OSF pre-registration.
    """
    pair_id: str
    dimension: str
    profile_a_id: str
    profile_b_id: str
    profile_a_label: str
    profile_b_label: str
    description: str


@dataclass(frozen=True)
class AuditSubmissionRecord:
    """Tracks one job's paired-submission status for one audit pair.

    Attributes:
        pair_id: Which AuditPairDefinition this belongs to.
        job_fingerprint: Structural hash of the job posting.
        job_url: The job's application URL.
        company_id: Anonymized company identifier.
        platform: Source platform.
        profile_a_submitted_at: When profile A's application was submitted, or None.
        profile_b_submitted_at: When profile B's application was submitted, or None.
        profile_a_callback: Whether profile A received a callback (None=pending).
        profile_b_callback: Whether profile B received a callback (None=pending).
        profile_a_interview_offered: Safeguard flag — triggers immediate withdrawal.
        profile_b_interview_offered: Safeguard flag — triggers immediate withdrawal.
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


@dataclass(frozen=True)
class AuditResult:
    """Statistical result for one audit pair across all submitted jobs.

    Attributes:
        pair_id: Which AuditPairDefinition this result is for.
        n_pairs: Number of job pairs included in this analysis.
        profile_a_callbacks: Total callbacks for profile A.
        profile_b_callbacks: Total callbacks for profile B.
        profile_a_rate: Callback rate for profile A.
        profile_b_rate: Callback rate for profile B.
        profile_a_ci: Wilson 95% CI for profile A's rate.
        profile_b_ci: Wilson 95% CI for profile B's rate.
        rate_difference: profile_a_rate - profile_b_rate.
        p_value: Two-tailed Fisher's exact test p-value.
        is_significant: True if p_value < 0.05.
    """
    pair_id: str
    n_pairs: int
    profile_a_callbacks: int
    profile_b_callbacks: int
    profile_a_rate: float
    profile_b_rate: float
    profile_a_ci: tuple[float, float]
    profile_b_ci: tuple[float, float]
    rate_difference: float
    p_value: float
    is_significant: bool


@runtime_checkable
class AuditRepositoryPort(Protocol):
    """Persistence contract for audit submission records."""

    def save_submission(self, record: AuditSubmissionRecord) -> None:
        """Persist a submission record (insert or update)."""
        ...

    def load_submissions(self, pair_id: str) -> list[AuditSubmissionRecord]:
        """Load all submission records for a given audit pair."""
        ...

    def find_submission(
        self, pair_id: str, job_fingerprint: str
    ) -> AuditSubmissionRecord | None:
        """Find a specific submission record, if it exists."""
        ...


@runtime_checkable
class AuditWorkDispatchPort(Protocol):
    """Contract for enqueueing paired application tasks.

    Implemented by an adapter wrapping the existing WorkQueuePort —
    this Protocol exists so AuditCoordinator doesn't need to know about
    WorkUnit's full schema, just that it can request an APPLY task for
    a specific (job, profile_id) pair.
    """

    def enqueue_application(self, job_url: str, profile_id: str) -> None:
        """Request an application be submitted using the given profile.

        Args:
            job_url: The job's application URL.
            profile_id: Which user profile to use for this application.
        """
        ...

    def withdraw_application(self, job_url: str, profile_id: str) -> None:
        """Request withdrawal of a previously submitted application.

        Args:
            job_url: The job's application URL.
            profile_id: Which profile's application to withdraw.
        """
        ...


class AuditCoordinator:
    """Schedules and analyzes correspondence audit submissions.

    Args:
        repository: Persistence adapter for submission records.
        dispatcher: Adapter for enqueueing/withdrawing applications.
        consent_manager: Gate — audit mode requires active research consent.
        pairs: Pre-registered audit pair definitions.
        sampling_rate: Fraction of eligible jobs to select for paired
            submission (0.0-1.0). Lower values reduce noise to legitimate
            employers; higher values increase statistical power faster.
    """

    def __init__(
        self,
        repository: AuditRepositoryPort,
        dispatcher: AuditWorkDispatchPort,
        consent_manager: ResearchConsentManager,
        pairs: list[AuditPairDefinition],
        sampling_rate: float = 0.1,
    ) -> None:
        if not (0.0 <= sampling_rate <= 1.0):
            raise ValueError(f"sampling_rate must be in [0,1], got {sampling_rate}")
        self._repository = repository
        self._dispatcher = dispatcher
        self._consent_manager = consent_manager
        self._pairs = {p.pair_id: p for p in pairs}
        self._sampling_rate = sampling_rate
        self._pair_cycle = list(pairs)
        self._cycle_index = 0

    @property
    def is_active(self) -> bool:
        """Audit mode requires active research consent AND configured pairs."""
        return self._consent_manager.is_active() and bool(self._pairs)

    def select_pair_for_job(
        self,
        job_url: str,
        job_fingerprint: str,
        jurisdiction: str | None,
        rng_value: float,
    ) -> AuditPairDefinition | None:
        """Decide whether and which audit pair to apply to this job.

        Args:
            job_url: The job's application URL (used as dedup key).
            job_fingerprint: Structural hash of the posting.
            jurisdiction: US state/city code, or None if unknown.
            rng_value: A value in [0,1) from the session's seeded RNG —
                callers must supply this (AuditCoordinator does not own
                randomness, per the determinism architecture).

        Returns:
            The AuditPairDefinition to use, or None if this job should
            not receive a paired audit submission (sampling miss,
            excluded jurisdiction, audit mode inactive, or already audited).
        """
        if not self.is_active:
            return None
        if jurisdiction is not None and jurisdiction in EXCLUDED_JURISDICTIONS:
            return None
        if rng_value >= self._sampling_rate:
            return None

        # Round-robin across configured pairs for balanced sample sizes
        if not self._pair_cycle:
            return None
        pair = self._pair_cycle[self._cycle_index % len(self._pair_cycle)]
        self._cycle_index += 1

        existing = self._repository.find_submission(pair.pair_id, job_fingerprint)
        if existing is not None:
            return None  # Already audited this job for this pair

        return pair

    def schedule_pair_submission(
        self,
        pair: AuditPairDefinition,
        job_url: str,
        job_fingerprint: str,
        company_id: str | None,
        platform: str | None,
    ) -> AuditSubmissionRecord:
        """Enqueue applications for both profiles in a pair and record initial state.

        Args:
            pair: The audit pair to use.
            job_url: The job's application URL.
            job_fingerprint: Structural hash of the posting.
            company_id: Anonymized company identifier.
            platform: Source platform.

        Returns:
            The newly created AuditSubmissionRecord (both submitted_at fields
            are None until the application workflow confirms submission via
            record_submission()).
        """
        record = AuditSubmissionRecord(
            pair_id=pair.pair_id,
            job_fingerprint=job_fingerprint,
            job_url=job_url,
            company_id=company_id,
            platform=platform,
        )
        self._repository.save_submission(record)

        self._dispatcher.enqueue_application(job_url, pair.profile_a_id)
        self._dispatcher.enqueue_application(job_url, pair.profile_b_id)

        logger.info(
            "AuditCoordinator | Scheduled pair %s for job %s (platform=%s)",
            pair.pair_id, job_fingerprint[:12], platform,
        )
        return record

    def record_submission(
        self,
        pair_id: str,
        job_fingerprint: str,
        profile_label: str,  # "a" or "b"
        submitted_at: datetime | None = None,
    ) -> None:
        """Record that one profile's application was submitted.

        Args:
            pair_id: The audit pair identifier.
            job_fingerprint: Structural hash of the posting.
            profile_label: Either "a" or "b" — which profile submitted.
            submitted_at: Submission timestamp (defaults to now, UTC).

        Raises:
            ValueError: If profile_label is not "a" or "b", or no matching
                submission record exists.
        """
        if profile_label not in ("a", "b"):
            raise ValueError(f"profile_label must be 'a' or 'b', got {profile_label!r}")

        record = self._repository.find_submission(pair_id, job_fingerprint)
        if record is None:
            raise ValueError(
                f"No submission record for pair={pair_id}, fingerprint={job_fingerprint}"
            )

        ts = submitted_at or datetime.now(timezone.utc)
        if profile_label == "a":
            record = replace(record, profile_a_submitted_at=ts)
        else:
            record = replace(record, profile_b_submitted_at=ts)
        self._repository.save_submission(record)

    def record_callback(
        self,
        pair_id: str,
        job_fingerprint: str,
        profile_label: str,
        is_interview_offer: bool = False,
    ) -> AuditSubmissionRecord:
        """Record that a profile received a callback.

        If is_interview_offer=True, this triggers the ETHICAL SAFEGUARD:
        the caller MUST follow up with withdraw_if_needed() to immediately
        withdraw both applications for this job, since fake applications
        must never occupy real interview slots.

        Args:
            pair_id: The audit pair identifier.
            job_fingerprint: Structural hash of the posting.
            profile_label: Either "a" or "b".
            is_interview_offer: Whether this callback is an interview offer
                (vs. a generic acknowledgment/auto-reply).

        Returns:
            The updated AuditSubmissionRecord.

        Raises:
            ValueError: If profile_label invalid or no matching record.
        """
        if profile_label not in ("a", "b"):
            raise ValueError(f"profile_label must be 'a' or 'b', got {profile_label!r}")

        record = self._repository.find_submission(pair_id, job_fingerprint)
        if record is None:
            raise ValueError(
                f"No submission record for pair={pair_id}, fingerprint={job_fingerprint}"
            )

        if profile_label == "a":
            record = replace(
                record,
                profile_a_callback=True,
                profile_a_interview_offered=is_interview_offer or record.profile_a_interview_offered,
            )
        else:
            record = replace(
                record,
                profile_b_callback=True,
                profile_b_interview_offered=is_interview_offer or record.profile_b_interview_offered,
            )

        self._repository.save_submission(record)

        if is_interview_offer:
            logger.warning(
                "AuditCoordinator | Interview offer received for pair=%s job=%s "
                "profile=%s — IMMEDIATE WITHDRAWAL REQUIRED",
                pair_id, job_fingerprint[:12], profile_label,
            )
        return record

    def withdraw_if_needed(self, record: AuditSubmissionRecord) -> AuditSubmissionRecord:
        """Withdraw both applications if either received an interview offer.

        ETHICAL SAFEGUARD — must be called after every record_callback().
        Real interview slots must never be occupied by fictitious applications.

        Args:
            record: The submission record to check and possibly withdraw.

        Returns:
            The updated record (withdrawn=True if action was taken).
        """
        if not record.needs_withdrawal:
            return record

        pair = self._pairs.get(record.pair_id)
        if pair is not None:
            self._dispatcher.withdraw_application(record.job_url, pair.profile_a_id)
            self._dispatcher.withdraw_application(record.job_url, pair.profile_b_id)
            logger.warning(
                "AuditCoordinator | Withdrew both applications for job=%s (pair=%s) "
                "due to interview offer",
                record.job_fingerprint[:12], record.pair_id,
            )

        updated = replace(record, withdrawn=True)
        self._repository.save_submission(updated)
        return updated

    def compute_results(self, pair_id: str) -> AuditResult | None:
        """Compute callback-rate statistics for an audit pair.

        Only includes submission records where BOTH profiles' applications
        were confirmed submitted (both_submitted=True) — incomplete pairs
        are excluded to avoid bias from partial-submission failures.

        Args:
            pair_id: The audit pair identifier.

        Returns:
            AuditResult with Fisher's exact p-value and Wilson CIs, or None
            if no complete pairs exist yet.

        Raises:
            ValueError: If pair_id is not a registered AuditPairDefinition.
        """
        if pair_id not in self._pairs:
            raise ValueError(f"Unknown audit pair_id: {pair_id}")

        records = [
            r for r in self._repository.load_submissions(pair_id)
            if r.both_submitted
        ]
        n = len(records)
        if n == 0:
            return None

        a_callbacks = sum(1 for r in records if r.profile_a_callback)
        b_callbacks = sum(1 for r in records if r.profile_b_callback)

        a_rate = a_callbacks / n
        b_rate = b_callbacks / n
        a_ci = wilson_score_interval(a_callbacks, n)
        b_ci = wilson_score_interval(b_callbacks, n)

        # 2x2 table: rows = profile A/B, cols = callback yes/no
        p_value = fisher_exact_2x2(
            a=a_callbacks, b=n - a_callbacks,
            c=b_callbacks, d=n - b_callbacks,
        )

        return AuditResult(
            pair_id=pair_id,
            n_pairs=n,
            profile_a_callbacks=a_callbacks,
            profile_b_callbacks=b_callbacks,
            profile_a_rate=a_rate,
            profile_b_rate=b_rate,
            profile_a_ci=a_ci,
            profile_b_ci=b_ci,
            rate_difference=a_rate - b_rate,
            p_value=p_value,
            is_significant=p_value < 0.05,
        )

    def export_protocol_for_preregistration(self) -> dict:
        """Export the audit protocol as a dict for OSF pre-registration.

        Per the spec's ethical requirements, this protocol MUST be published
        on the Open Science Framework BEFORE the coordinator begins
        scheduling submissions. Includes pair definitions, sampling rate,
        and the statistical analysis plan.

        Returns:
            A dict suitable for json.dump() to create the OSF pre-registration
            document.
        """
        return {
            "protocol_version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "sampling_rate": self._sampling_rate,
            "excluded_jurisdictions": sorted(EXCLUDED_JURISDICTIONS),
            "audit_pairs": [
                {
                    "pair_id": p.pair_id,
                    "dimension": p.dimension,
                    "profile_a_label": p.profile_a_label,
                    "profile_b_label": p.profile_b_label,
                    "description": p.description,
                }
                for p in self._pairs.values()
            ],
            "statistical_analysis_plan": {
                "primary_test": "Fisher's exact test (two-tailed), 2x2 table "
                                 "of (profile A/B) x (callback received/not)",
                "confidence_intervals": "Wilson score interval, 95%",
                "significance_threshold": 0.05,
                "minimum_sample_size_per_pair": 30,
                "exclusion_criteria": "Submission pairs where either profile's "
                                       "application failed to submit are excluded "
                                       "(both_submitted=False)",
            },
            "ethical_safeguards": {
                "interview_withdrawal": "Any application reaching interview-offer "
                                         "stage is immediately withdrawn for both "
                                         "profiles in the pair (see withdraw_if_needed).",
                "consent_required": "Audit mode requires active research consent "
                                     "(ResearchConsentManager.is_active()).",
                "jurisdiction_exclusions": sorted(EXCLUDED_JURISDICTIONS),
            },
        }