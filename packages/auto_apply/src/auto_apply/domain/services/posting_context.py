"""From a job posting to what the detectors see — one path, shared (item 7).

A live run turns a posting into a JobPostingObservation (vetting) and then
into a DetectionContext (the research aggregator). A replay re-runs the
same detectors over a kept page copy, with no browser and no database. If
the two built their inputs separately, a replay could silently stop
matching a live run the day one of them changed. So both build them here:

* posting_observation()        — vetting and replay;
* posting_detection_context()  — the aggregator and replay.

The aggregator passes what only it has (lifecycle history from the research
database, the salary corpus percentile); a replay passes nothing for those,
and its manifest lists them as not replayed.

Pure: no I/O, no clock — every date is a parameter.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from auto_apply.domain.ports.research_port import JobPostingObservation
from auto_apply.domain.services.posting_observation import (
    infer_jurisdiction,
    infer_metro_area,
    looks_like_generic_apply_url,
)
from auto_apply.domain.services.signal_detectors import DetectionContext

__all__ = ["posting_observation", "posting_detection_context"]


def posting_observation(
    *,
    job_title: str,
    job_description: str,
    company_name: str | None,
    location: str | None,
    platform: str | None,
    url: str,
    seen_on: date,
    page_copy_id: str | None = None,
) -> JobPostingObservation:
    """The research observation of one job posting.

    Honesty rules (vetting's, unchanged — see VettingWorkflow):
        * ``job_description`` is text read from the page, or "" — never a
          title standing in for one;
        * ``posting_hash`` stays None (no posting identity is minted:
          re-fetched pages do not re-hash identically);
        * salary fields stay None: nothing extracts them yet.
    """
    place = location or ""
    return JobPostingObservation(
        job_title=job_title,
        job_description=job_description,
        company_name=company_name,
        location=location,
        jurisdiction=infer_jurisdiction(place),
        salary_min=None,
        salary_max=None,
        platform=platform,
        first_seen_date=seen_on,
        posting_hash=None,
        application_url_is_generic=looks_like_generic_apply_url(url),
        metro_area=infer_metro_area(place),
        page_copy_id=page_copy_id,
    )


def posting_detection_context(
    observation: JobPostingObservation,
    *,
    current_date: date,
    first_seen_date: date | None = None,
    days_live: int | None = None,
    times_seen_cross_platform: int = 1,
    previous_posting_dates: Sequence[date] = (),
    salary_corpus_p25_for_role: float | None = None,
    salary_corpus_sample_size: int = 0,
) -> DetectionContext:
    """The detectors' input for one posting.

    Args:
        observation: The posting, as posting_observation() built it.
        current_date: "Today" for the detectors' age arithmetic. Live: the
            run's date. Replay: the page copy's capture date, never the
            replay's date.
        first_seen_date: From lifecycle history; defaults to the
            observation's own first_seen_date.
        days_live, times_seen_cross_platform, previous_posting_dates:
            Lifecycle history (live only).
        salary_corpus_p25_for_role, salary_corpus_sample_size: The salary
            corpus percentile (live only).
    """
    return DetectionContext(
        job_title=observation.job_title,
        job_description=observation.job_description,
        company_name=observation.company_name,
        location=observation.location,
        jurisdiction=observation.jurisdiction,
        salary_min=observation.salary_min,
        salary_max=observation.salary_max,
        platform=observation.platform,
        first_seen_date=first_seen_date or observation.first_seen_date,
        current_date=current_date,
        days_live=days_live,
        posting_hash=observation.posting_hash,
        times_seen_cross_platform=max(times_seen_cross_platform, 1),
        previous_posting_dates=list(previous_posting_dates),
        application_url_is_generic=observation.application_url_is_generic,
        metro_area=observation.metro_area,
        company_linkedin_age_days=observation.company_linkedin_age_days,
        company_domain_age_days=observation.company_domain_age_days,
        company_has_web_presence=observation.company_has_web_presence,
        salary_corpus_p25_for_role=salary_corpus_p25_for_role,
        salary_corpus_sample_size=salary_corpus_sample_size,
        page_copy_id=observation.page_copy_id,
    )
