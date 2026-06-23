"""
Job Lifecycle Tracker — pure domain logic for GJ-02 (freshness laundering)
and GJ-03 (refill without hire) detection.

ARCHITECTURE: This module is pure — no I/O, no SQLite, no datetime.now().
The adapter layer (signal_aggregator.py) is responsible for:
  1. Loading the previous JobLifecycleRecord for a posting_hash from SQLite
  2. Calling update_lifecycle() with the new observation
  3. Persisting the returned record back to SQLite
  4. Populating DetectionContext.previous_posting_dates and
     times_seen_cross_platform / times_reposted from the record before
     calling run_all_detectors()

This separation means the lifecycle state machine logic (what counts as a
"repost", how times_seen accumulates) is fully unit-testable with synthetic
dates, with zero database dependency.

Structural hashing: posting_hash is computed by structural_hashing.py
(existing AA module) on (title, company, normalized_description). This
module does not compute the hash itself — it operates on whatever hash
string it's given, treating it as an opaque deduplication key.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta


@dataclass(frozen=True)
class JobLifecycleRecord:
    """Immutable lifecycle state for one (posting_hash, platform) pair.

    Attributes:
        job_fingerprint: Structural hash from structural_hashing.py.
        platform: Job board / ATS where this posting was observed.
        first_seen: First date AA observed this posting on this platform.
        last_seen: Most recent date AA observed this posting on this platform.
        times_seen: Total number of distinct observation dates.
        times_reposted: Number of times the posting disappeared (gap >
            REPOST_GAP_THRESHOLD_DAYS) and then reappeared.
        applied_to: Whether the user applied to this posting.
        response_received: Whether any response was received.
        response_date: Date of response, if any.
        all_seen_dates: Every date this posting was observed (for GJ-02
            cross-platform spread analysis — bounded to last MAX_DATES_TRACKED).
    """
    job_fingerprint: str
    platform: str
    first_seen: date
    last_seen: date
    times_seen: int = 1
    times_reposted: int = 0
    applied_to: bool = False
    response_received: bool = False
    response_date: date | None = None
    all_seen_dates: tuple[date, ...] = ()


# A gap of this many days between observations is treated as the posting
# having disappeared and reappeared (a "repost"), not continuous visibility.
REPOST_GAP_THRESHOLD_DAYS: int = 7

# Bound memory: only retain the most recent N observation dates per record.
MAX_DATES_TRACKED: int = 20


def update_lifecycle(
    previous: JobLifecycleRecord | None,
    job_fingerprint: str,
    platform: str,
    observation_date: date,
) -> JobLifecycleRecord:
    """Compute the updated lifecycle record after a new observation.

    Pure function: given the previous record (or None for first observation)
    and a new observation date, returns the new record. Does not mutate
    `previous`.

    Args:
        previous: The existing record for this (fingerprint, platform), or
            None if this is the first time AA has seen this posting on
            this platform.
        job_fingerprint: Structural hash of the posting.
        platform: Platform identifier.
        observation_date: The date of this observation.

    Returns:
        The updated (or newly created) JobLifecycleRecord.

    Example:
        >>> rec = update_lifecycle(None, "abc123", "linkedin", date(2026, 1, 1))
        >>> rec.times_seen
        1
        >>> rec2 = update_lifecycle(rec, "abc123", "linkedin", date(2026, 3, 1))
        >>> rec2.times_reposted  # gap > 7 days = repost
        1
    """
    if previous is None:
        return JobLifecycleRecord(
            job_fingerprint=job_fingerprint,
            platform=platform,
            first_seen=observation_date,
            last_seen=observation_date,
            times_seen=1,
            times_reposted=0,
            all_seen_dates=(observation_date,),
        )

    # Same-day re-observation — no state change beyond last_seen.
    if observation_date == previous.last_seen:
        return previous

    gap_days = (observation_date - previous.last_seen).days
    is_repost = gap_days > REPOST_GAP_THRESHOLD_DAYS

    new_dates = (*previous.all_seen_dates, observation_date)[-MAX_DATES_TRACKED:]

    return replace(
        previous,
        last_seen=observation_date,
        times_seen=previous.times_seen + 1,
        times_reposted=previous.times_reposted + (1 if is_repost else 0),
        all_seen_dates=new_dates,
    )


def days_live(record: JobLifecycleRecord, current_date: date) -> int:
    """Compute days_live for GJ-01 from a lifecycle record.

    Args:
        record: The lifecycle record.
        current_date: The date to measure "live" against.

    Returns:
        Days between first_seen and current_date (always >= 0).
    """
    return max(0, (current_date - record.first_seen).days)


def cross_platform_date_spread(
    records: list[JobLifecycleRecord],
) -> tuple[int, list[date]]:
    """Compute the GJ-02 input: cross-platform observation date spread.

    Args:
        records: All JobLifecycleRecord entries sharing the same
            job_fingerprint across different platforms.

    Returns:
        Tuple of (number of distinct platforms, sorted list of all
        first_seen dates across those platforms). An empty list of
        records returns (0, []).
    """
    if not records:
        return 0, []
    platforms = {r.platform for r in records}
    first_seen_dates = sorted(r.first_seen for r in records)
    return len(platforms), first_seen_dates


def mark_applied(record: JobLifecycleRecord) -> JobLifecycleRecord:
    """Return a copy of the record with applied_to=True.

    Args:
        record: The lifecycle record to update.

    Returns:
        A new record with applied_to set to True (immutable update).
    """
    return replace(record, applied_to=True)


def mark_response_received(
    record: JobLifecycleRecord, response_date: date
) -> JobLifecycleRecord:
    """Return a copy of the record with response_received=True and the date set.

    Args:
        record: The lifecycle record to update.
        response_date: The date the response was received.

    Returns:
        A new record with response fields set (immutable update).
    """
    return replace(record, response_received=True, response_date=response_date)
