"""Vetting filter that enforces minimum experience requirements.

This filter reads structured NLP output stored in job.metadata["parsed"] by
VettingWorkflow._parse_with_spacy() and compares the job's required minimum
experience against the user's self-declared experience level.

The mapping from experience_level strings to approximate years:
    ENTRY / JUNIOR         → 0–2  years (represented as max 2)
    MID / ASSOCIATE        → 2–5  years (represented as max 5)
    SENIOR                 → 5–10 years (represented as max 10)
    LEAD / STAFF / PRINCIPAL → 10+ years (represented as max 15)

To extend this mapping, add entries to ExperienceFilter.LEVEL_TO_YEARS.

If the job description specifies no minimum experience, the filter passes.
If the user's profile has no experience_level set, the filter passes (never
blocks on missing profile data).
"""
from __future__ import annotations

import logging

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.vetting.base_filter import BaseVettingFilter

logger = logging.getLogger(__name__)


class ExperienceFilter(BaseVettingFilter):
    """Passes jobs whose experience requirement the user's level can satisfy.

    Reads job.metadata["parsed"]["experience_years_min"] set by
    VettingWorkflow._parse_with_spacy(). Compares against
    profile.search_preferences.experience_level via LEVEL_TO_YEARS mapping.
    """

    LEVEL_TO_YEARS: dict[str, int] = {
        "ENTRY": 2,
        "JUNIOR": 2,
        "ASSOCIATE": 5,
        "MID": 5,
        "MIDLEVEL": 5,
        "MID-LEVEL": 5,
        "SENIOR": 10,
        "LEAD": 15,
        "STAFF": 15,
        "PRINCIPAL": 15,
        "DIRECTOR": 15,
        "MANAGER": 10,
        "EXPERT": 15,
    }

    def filter(self, job: Job) -> tuple[bool, str]:
        """Checks whether the user's experience level satisfies the job requirement.

        Args:
            job: The Job candidate. Reads job.metadata["parsed"] for NLP output.

        Returns:
            (True, reason) if the user meets or exceeds the requirement or the
            requirement is absent/ambiguous. (False, reason) if under-qualified.
        """
        parsed: dict = job.metadata.get("parsed", {}) if hasattr(job, "metadata") else {}
        min_years = parsed.get("experience_years_min")

        if min_years is None:
            return True, "no_experience_requirement_detected"

        prefs = getattr(self.profile, "search_preferences", None)
        experience_level = getattr(prefs, "experience_level", None)

        if not experience_level:
            return True, "experience_level_not_set"

        if isinstance(experience_level, list):
            experience_level = experience_level[0] if experience_level else None

        if not experience_level:
            return True, "experience_level_not_set"

        user_years = self.LEVEL_TO_YEARS.get(str(experience_level).upper().strip(), 0)

        if user_years >= min_years:
            return True, f"experience_ok:{user_years}>={min_years}"

        return False, f"requires_{min_years}_years_have_{user_years}"
