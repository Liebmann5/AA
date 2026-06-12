"""Defines the standardized data model for a Job Opportunity.

This module contains the `Job` model, which acts as the universal currency
across the application. The Discovery engine produces `Job` objects, the
Vetting engine filters them, and the Application engine consumes them.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from auto_apply.domain.types import JobStatus


class Job(BaseModel):
    """Represents a single job posting discovered on the web."""
    model_config = ConfigDict(frozen=False)

    title: str = Field(..., description="The job title (e.g. 'Software Engineer').")
    company: str = Field(..., description="The name of the hiring company.")
    url: str = Field(..., description="The direct URL to the job posting.")
    location: str | None = Field(None, description="The job location.")

    source: str = Field(..., description="Where this job was found (e.g. 'Google', 'LinkedIn').")  # noqa: E501
    discovery_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Status tracking for the pipeline
    status: JobStatus = JobStatus.FOUND
    is_vetted: bool = False
    fit_score: float = 0.0
    rejection_reason: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Mutable scratch-pad attached to this job during pipeline processing. "
            "Reserved keys: "
            "'form_location' (str) — URL or CSS selector of the apply form; "
            "'ats' (str | None) — matched ATS platform name from ATSRegistry; "
            "'provider' (str) — discovery source name; "
            "'parsed' (dict) — output of ParsedJobDescription.model_dump(); "
            "'apply_url' (str | None) — direct apply button URL if different from job.url; "
            "'company_cooldown_days' (int | None) — cooldown extracted from confirmation page."
        ),
    )

    def __hash__(self):
        """Allows Jobs to be used in sets for easy deduplication based on URL."""
        return hash(self.url)

    def __eq__(self, other):
        """Checks equality based on the URL."""
        if isinstance(other, Job):
            return self.url == other.url
        return False