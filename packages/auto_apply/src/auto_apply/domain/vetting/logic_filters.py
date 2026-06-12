"""Provides deterministic, logic-based filters for job vetting.

This module implements lightweight filters that rely on string manipulation,
set operations, and standard library fuzzy matching. These filters are designed
to run instantly on any hardware with zero overhead.
"""

import logging
from difflib import SequenceMatcher

from auto_apply.domain.models.job import Job
from auto_apply.domain.vetting.base_filter import BaseVettingFilter

logger = logging.getLogger(__name__)


class TitleLogicFilter(BaseVettingFilter):
    """Filters jobs based on title similarity and negative keywords.

    This uses a two-step logic process:
    1. Hard Block: Check for 'negative keywords' (e.g., 'Senior' if user is Entry).
    2. Fuzzy Match: Calculate string similarity against desired titles.
    """

    def filter(self, job: Job) -> tuple[bool, str]:
        title = job.title.lower()

        # 1. Negative Keyword Check (The "Hard Block")
        # If the user is "Entry Level", block "Senior", "Lead", "Principal", "Staff"
        # This logic is derived from the profile's experience level.
        experience_level = (self.profile.search_preferences.experience_level or []).copy()  # noqa: E501

        # Define a basic negative keyword map (This could be moved to a config file later)  # noqa: E501
        # If user wants "Entry", block these:
        blacklist = []
        if any("entry" in lvl.lower() for lvl in experience_level):
            blacklist = ["senior", "lead", "principal", "staff", "manager", "head of", "director"]  # noqa: E501

        for bad_word in blacklist:
            # We pad with spaces to avoid matching "Lead" inside "Leaderboard"
            if f" {bad_word} " in f" {title} ":
                return False, f"Negative Keyword Detected: '{bad_word}'"

        # 2. Fuzzy Matching (The "Soft Check")
        # We check if the job title is sufficiently similar to ANY of the desired titles.  # noqa: E501
        desired_titles = [t.lower() for t in self.profile.search_preferences.desired_job_titles]  # noqa: E501

        best_score = 0.0
        for desired in desired_titles:
            # SequenceMatcher is Python's built-in "diff" tool.
            # It returns a float 0.0 to 1.0 based on similarity.
            score = SequenceMatcher(None, desired, title).ratio()

            # Boost score if the desired title appears exactly inside the job title
            # e.g. desired="Python Dev", job="Junior Python Dev at Google" -> Good match
            if desired in title:
                score = 1.0

            best_score = max(best_score, score)

        # Threshold: 0.4 is a conservative baseline for "somewhat related"
        # We keep it low to avoid false negatives, relying on the negative keywords to filter bad stuff.  # noqa: E501
        if best_score < 0.4:
            return False, f"Low Relevance Score ({best_score:.2f})"

        return True, "Title Match"


class CompanyBlacklistFilter(BaseVettingFilter):
    """Filters jobs from specific companies (e.g., previous employers)."""

    def filter(self, job: Job) -> tuple[bool, str]:
        # We treat the 'non_compete_agreements' in legal_info as a blacklist
        blacklist = [c.lower() for c in self.profile.legal_info.non_compete_agreements]

        if job.company.lower() in blacklist:
            return False, f"Company Blacklisted (Non-Compete): {job.company}"

        return True, "Company Allowed"


class LocationLogicFilter(BaseVettingFilter):
    """Filters jobs based on location string matching."""

    def filter(self, job: Job) -> tuple[bool, str]:
        # If no location preference is set, assume "Anywhere" is fine.
        preferred = self.profile.search_preferences.preferred_locations
        if not preferred:
            return True, "No Location Preference Set"

        # If job has no location data (common in some scrapes), we usually pass it
        # to let the application stage verify it, or we can be strict.
        # For worst-case users, we might want to be strict to save bandwidth.
        if not job.location:
            return True, "Unknown Location (Allowed for Review)"

        job_loc = job.location.lower()

        # Check for "Remote"
        if "remote" in job_loc and any("remote" in p.lower() for p in preferred):
            return True, "Remote Match"

        # Check for City/State Match
        for pref in preferred:
            if pref.lower() in job_loc:
                return True, f"Location Match: {pref}"

        return False, f"Location Mismatch: {job.location}"
