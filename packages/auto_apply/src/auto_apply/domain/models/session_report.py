"""
Defines a data structure for holding the results of a single application session.
"""
from dataclasses import dataclass, field


@dataclass
class SessionReport:
    """A summary of the activities performed during a single run."""
    raw_results_found: int = 0
    new_jobs_identified: int = 0
    pending_jobs_to_apply_for: int = 0
    applications_completed: int = 0
    applications_failed: int = 0
    failed_job_urls: list[str] = field(default_factory=list)
