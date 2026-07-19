"""Structured output of SpaCy NLP analysis on a raw job description.

This model is produced by VettingWorkflow._parse_with_spacy() and stored
in job.metadata["parsed"] as a dict (via .model_dump()). Downstream filters
(ExperienceFilter, HardSkillsFilter) read from job.metadata["parsed"] directly
rather than receiving this model object, to avoid coupling filter constructors
to the parsing step.

Fields are all optional with safe defaults so that partial NLP extraction
never blocks the filter chain.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ParsedJobDescription(BaseModel):
    """Immutable structured output of job description NLP analysis."""

    model_config = ConfigDict(frozen=True)

    required_skills: list[str] = Field(
        default_factory=list,
        description="Skills and technologies extracted via SpaCy PhraseMatcher.",
    )
    experience_years_min: int | None = Field(
        None,
        description="Minimum years of experience extracted from description text.",
    )
    experience_years_max: int | None = Field(
        None,
        description="Maximum years of experience, if a range is stated.",
    )
    locations: list[str] = Field(
        default_factory=list,
        description="GPE and LOC named entities extracted from description.",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="ORG named entities extracted from description.",
    )
    employment_type: str | None = Field(
        None,
        description="Employment type string if detectable: 'full-time', 'part-time', 'contract'.",
    )
    seniority_signal: str | None = Field(
        None,
        description=(
            "Seniority level inferred from title/description: "
            "'junior', 'mid', 'senior', 'lead', 'staff', 'principal'."
        ),
    )
    is_remote: bool | None = Field(
        None,
        description=(
            "True if remote indicators found, False if on-site-only indicators found, "
            "None if ambiguous."
        ),
    )