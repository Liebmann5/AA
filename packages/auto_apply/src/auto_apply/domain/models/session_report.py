"""Rich session report model for AutoApply.

A SessionReport is built incrementally during a session and finalized at the
end. It captures everything the user needs to review:
  - What jobs were found and where
  - What was vetted and why jobs were rejected
  - What was applied to and what the evidence was
  - What failed and why
  - How long each task took (per-task duration tracking)

The report is:
  - Written as JSON to ~/.auto_apply/reports/session_{id}.json
  - Displayed as a summary in the CLI after session ends
  - Accessible via the GUI's activity feed
  - Available for research pipeline export
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from auto_apply.domain.models.application_evidence import ApplicationEvidence


@dataclass
class ApplicationRecord:
    """A single application attempt with its evidence and timing.

    Attributes:
        job_url: The job posting URL applied to.
        job_title: The job title.
        company: The company name.
        ats_platform: Matched ATS platform name, or None.
        outcome: Evidence outcome string (SUBMITTED, FAILED, etc.).
        confidence: Confidence score [0.0, 1.0].
        fields_filled: Number of form fields filled.
        pages_navigated: Number of form pages navigated.
        used_gpt4all: Whether GPT4All was used for custom answers.
        timestamp: UTC ISO timestamp when this record was created.
        started_at: UTC ISO timestamp when the application task began.
            Set by the orchestrator before dispatching the APPLY task.
            May be empty if timing was not recorded.
        duration_seconds: Wall-clock seconds the application attempt took.
            0.0 if timing was not recorded.
    """

    job_url: str
    job_title: str
    company: str
    ats_platform: str | None
    outcome: str
    confidence: float
    fields_filled: int
    pages_navigated: int
    used_gpt4all: bool
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: str = ""
    duration_seconds: float = 0.0
    #: Joins this outcome to the per-page research rows for the same
    #: attempt, so a partial application's friction data is not read as a
    #: completed one.
    attempt_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_url": self.job_url,
            "job_title": self.job_title,
            "company": self.company,
            "ats_platform": self.ats_platform,
            "outcome": self.outcome,
            "confidence": round(self.confidence, 3),
            "fields_filled": self.fields_filled,
            "pages_navigated": self.pages_navigated,
            "used_gpt4all": self.used_gpt4all,
            "timestamp": self.timestamp,
            "started_at": self.started_at,
            "duration_seconds": round(self.duration_seconds, 1),
        }


@dataclass
class SessionReport:
    """Comprehensive record of a single AutoApply session.

    Built incrementally during the session. Finalized and written to disk
    when the session ends.
    """

    session_id: str = ""
    profile_name: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None
    duration_seconds: float = 0.0
    mode: str = "discovery"  # discovery | direct | vet | company
    report_path: Path | None = None

    # Discovery stats
    raw_results_found: int = 0
    new_jobs_identified: int = 0
    deduplicated_count: int = 0
    discovery_sources: list[str] = field(default_factory=list)

    # Vetting stats
    pending_jobs_to_apply_for: int = 0
    jobs_rejected_by_filter: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    # Application records
    applications: list[ApplicationRecord] = field(default_factory=list)

    # ── Derived counts (computed from applications list) ──────────────────

    @property
    def applications_completed(self) -> int:
        return len(self.applications)

    @property
    def applications_submitted(self) -> int:
        return sum(
            1
            for a in self.applications
            if a.outcome in ("SUBMITTED", "PROBABLY_SUBMITTED")
        )

    @property
    def applications_failed(self) -> int:
        return sum(
            1
            for a in self.applications
            if a.outcome
            not in (
                "SUBMITTED",
                "PROBABLY_SUBMITTED",
                "USER_SKIPPED",
                "SUBMISSION_GATE_BLOCKED",
            )
        )

    @property
    def submissions_blocked_by_gate(self) -> int:
        """Applications the submission gate refused to send.

        Separate from :attr:`applications_failed` on purpose: a blocked
        submission is a *not attempted*, not a failure. A run showing a high
        count here is working correctly and waiting for a human — which is the
        opposite of what a silent count would imply.
        """
        return sum(
            1 for a in self.applications if a.outcome == "SUBMISSION_GATE_BLOCKED"
        )

    @property
    def gate_block_remedy(self) -> str:
        """What the operator should do about blocked submissions, if any.

        Empty when nothing was blocked, so callers can print it unconditionally
        and it simply disappears on a normal run.
        """
        blocked = self.submissions_blocked_by_gate
        if not blocked:
            return ""
        return (
            f"{blocked} submission(s) were blocked by the pre-submit review "
            f"gate and were NOT sent. This is the safe default, not a fault. "
            f"To submit automatically, either wire an approval gate (run with "
            f"the GUI/CLI review prompt enabled) or remove "
            f"'BEFORE_FORM_SUBMIT' from human_review_checkpoints in your "
            f"profile to opt into autonomous submission."
        )

    @property
    def submitted_job_urls(self) -> list[str]:
        return [
            a.job_url
            for a in self.applications
            if a.outcome in ("SUBMITTED", "PROBABLY_SUBMITTED")
        ]

    @property
    def submitted_companies(self) -> dict[str, str]:
        """Maps job_url → company for submitted applications."""
        return {
            a.job_url: a.company
            for a in self.applications
            if a.outcome in ("SUBMITTED", "PROBABLY_SUBMITTED")
        }

    @property
    def success_rate(self) -> float:
        if not self.applications:
            return 0.0
        return self.applications_submitted / self.applications_completed

    @property
    def total_task_duration_seconds(self) -> float:
        """Sum of all per-application durations.  0.0 if timing was not recorded."""
        return sum(a.duration_seconds for a in self.applications)

    @property
    def average_application_seconds(self) -> float | None:
        """Mean application duration, or None if no applications have timing data."""
        timed = [a for a in self.applications if a.duration_seconds > 0]
        if not timed:
            return None
        return self.total_task_duration_seconds / len(timed)

    # ── Mutation methods ─────────────────────────────────────────────────

    def record_application(
        self,
        job: Any,  # Job model
        evidence: "ApplicationEvidence",
        started_at: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        """Add an application record from a completed attempt.

        Args:
            job: The Job that was applied to.
            evidence: Structured ApplicationEvidence from the workflow.
            started_at: ISO timestamp when the application task began.
            duration_seconds: Wall-clock seconds the attempt took.
        """
        self.applications.append(
            ApplicationRecord(
                job_url=job.url,
                job_title=job.title,
                company=job.company,
                # Was evidence.ats_descriptor_matched — a field ApplicationEvidence
                # has never had. Every record_application call raised
                # AttributeError, so the session report stayed empty.
                ats_platform=evidence.ats_platform,
                outcome=evidence.outcome,
                attempt_id=evidence.attempt_id,
                confidence=evidence.confidence,
                fields_filled=evidence.required_fields_filled
                + evidence.optional_fields_filled,
                pages_navigated=getattr(evidence, "pages_navigated", 0),
                used_gpt4all=getattr(evidence, "used_gpt4all", False),
                started_at=started_at,
                duration_seconds=duration_seconds,
            )
        )

    def finalize(self, duration_seconds: float) -> None:
        """Mark the session as complete."""
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.duration_seconds = duration_seconds

    def save(self, reports_dir: Path) -> Path:
        """Write the report to disk as a JSON file.

        Returns the path to the written file.
        """
        reports_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"session_{self.session_id[:8]}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path = reports_dir / filename

        data = {
            "session_id": self.session_id,
            "profile_name": self.profile_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "mode": self.mode,
            "discovery": {
                "raw_results_found": self.raw_results_found,
                "new_jobs_identified": self.new_jobs_identified,
                "sources": self.discovery_sources,
            },
            "vetting": {
                "jobs_approved": self.pending_jobs_to_apply_for,
                "jobs_rejected": self.jobs_rejected_by_filter,
                "rejection_reasons": self.rejection_reasons,
            },
            "applications": {
                "total": self.applications_completed,
                "submitted": self.applications_submitted,
                "failed": self.applications_failed,
                "success_rate": round(self.success_rate, 3),
                "total_task_duration_seconds": round(
                    self.total_task_duration_seconds, 1
                ),
                "average_application_seconds": (
                    round(self.average_application_seconds, 1)
                    if self.average_application_seconds is not None
                    else None
                ),
                "records": [a.to_dict() for a in self.applications],
            },
        }

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.report_path = path
        return path

    def get_stats(self) -> dict[str, Any]:
        """Returns the stats dict expected by _print_results in the CLI.

        Includes backward-compatible keys for the GUI/CLI dashboard polling.
        """
        return {
            # New keys (used by CLI _print_results)
            "jobs_found": self.raw_results_found,
            "jobs_vetted": self.new_jobs_identified,
            "jobs_passed_vetting": self.pending_jobs_to_apply_for,
            "applications_attempted": self.applications_completed,
            "applications_submitted": self.applications_submitted,
            "applications_failed": self.applications_failed,
            "submissions_blocked_by_gate": self.submissions_blocked_by_gate,
            "gate_block_remedy": self.gate_block_remedy,
            "session_duration_seconds": self.duration_seconds,
            "submitted_job_urls": self.submitted_job_urls,
            "submitted_companies": self.submitted_companies,
            "success_rate": self.success_rate,
            # Per-task timing (new — Wave M)
            "total_task_duration_seconds": round(
                self.total_task_duration_seconds, 1
            ),
            "average_application_seconds": (
                round(self.average_application_seconds, 1)
                if self.average_application_seconds is not None
                else None
            ),
            # Backward-compatible keys (used by GUI/CLI dashboard polling)
            "jobs_discovered": self.raw_results_found,
            "duration_str": (
                f"{int(self.duration_seconds // 3600):02d}:"
                f"{int((self.duration_seconds % 3600) // 60):02d}:"
                f"{int(self.duration_seconds % 60):02d}"
            ),
            "report_path": str(self.report_path) if self.report_path else None,
        }