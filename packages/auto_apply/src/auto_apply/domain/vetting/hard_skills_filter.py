"""Vetting filter that enforces hard-skill overlap between job and user profile.

This filter reads structured NLP output stored in job.metadata["parsed"] by
VettingWorkflow._parse_with_spacy() and compares the job's required skills
against the user's self-declared skills in profile.search_preferences.skills.

Overlap is computed as:
    matched = intersection(required_skills, user_skills)
    overlap_ratio = len(matched) / max(len(required_skills), 1)

The threshold is configurable via the config key "vetting.hard_skills_min_overlap"
(default 0.5 = 50%). A job with no listed required skills always passes.

To extend: add the new filter's constructor to the composition_root filter_pipeline
list. Adjust the threshold in runtime_defaults.yaml under vetting.hard_skills_min_overlap.
"""
from __future__ import annotations

import logging

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.vetting.base_filter import BaseVettingFilter

logger = logging.getLogger(__name__)


class HardSkillsFilter(BaseVettingFilter):
    """Passes jobs where the user's skills cover enough of the required skills.

    Reads job.metadata["parsed"]["required_skills"] set by
    VettingWorkflow._parse_with_spacy() and profile.search_preferences.skills.
    """

    def __init__(
        self,
        profile: UserProfile,
        config: dict | None = None,
    ) -> None:
        """Initializes the filter.

        Args:
            profile: The active user profile.
            config: Optional config dict with dot-path keys (e.g.
                    {"vetting": {"hard_skills_min_overlap": 0.5}}).
        """
        super().__init__(profile)
        self._raw_config: dict = config or {}

    def _cfg(self, key: str, default):
        """Read a dot-path config key from self._raw_config with a fallback.

        Args:
            key: Dot-separated config path, e.g. "vetting.hard_skills_min_overlap".
            default: Value to return when the key is absent.

        Returns:
            The config value at that path, or default.
        """
        parts = key.split(".")
        node = self._raw_config
        for part in parts:
            if not isinstance(node, dict):
                return default
            node = node.get(part, default)
            if node is default:
                return default
        return node

    def filter(self, job: Job) -> tuple[bool, str]:
        """Checks whether the user's skills meet the job's hard-skill requirements.

        Args:
            job: The Job candidate. Reads job.metadata["parsed"] for NLP output.

        Returns:
            (True, reason) if overlap meets threshold or no skills listed.
            (False, reason) with up to 5 missing skills listed on failure.
        """
        parsed: dict = job.metadata.get("parsed", {}) if hasattr(job, "metadata") else {}
        required = [s.lower() for s in parsed.get("required_skills", [])]

        if not required:
            return True, "no_skills_listed"

        prefs = getattr(self.profile, "search_preferences", None)
        user_skills_raw = getattr(prefs, "skills", []) or []
        user_skills = [s.lower() for s in user_skills_raw]

        matched = set(required) & set(user_skills)
        overlap_ratio = len(matched) / max(len(required), 1)

        threshold: float = self._cfg("vetting.hard_skills_min_overlap", 0.5)

        if overlap_ratio >= threshold:
            return True, f"skills_ok:{len(matched)}/{len(required)}={overlap_ratio:.2f}"

        missing = list(set(required) - set(user_skills))[:5]
        return (
            False,
            f"skills_gap:{overlap_ratio:.2f}<{threshold} missing={missing}",
        )
