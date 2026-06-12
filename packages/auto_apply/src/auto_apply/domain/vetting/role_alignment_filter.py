"""Vetting filter that enforces semantic alignment between job title and desired titles.

This filter uses a TextSimilarityPort (structurally satisfied by TextMatcher)
to score the job title against each of the user's desired_job_titles. The highest
similarity score is compared against a configurable threshold.

The port abstraction keeps domain/ pure: RoleAlignmentFilter never imports from
application/ or adapters/. TextMatcher is injected as a TextSimilarityPort
(domain/ports/text_similarity_port.py) so the dependency flows domain ← application.

Algorithm:
    scores = [similarity(job.title, desired) for desired in desired_job_titles]
    best_score = max(scores)
    passes if best_score >= threshold (default 0.6)

Threshold is read from config key "vetting.role_alignment_threshold" (default 0.6).
If desired_job_titles is empty, the filter passes (never blocks on missing config).
"""
from __future__ import annotations

import logging

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.text_similarity_port import TextSimilarityPort
from auto_apply.domain.vetting.base_filter import BaseVettingFilter

logger = logging.getLogger(__name__)


class RoleAlignmentFilter(BaseVettingFilter):
    """Passes jobs whose title is semantically close to at least one desired title.

    Requires a TextSimilarityPort (injected) to score title similarity.
    Falls back to 0.0 for all scores if similarity_port is None (always passes —
    never blocks on missing optional dependency).
    """

    def __init__(
        self,
        profile: UserProfile,
        similarity_port: TextSimilarityPort | None = None,
        config: dict | None = None,
    ) -> None:
        """Initializes the filter.

        Args:
            profile: The active user profile.
            similarity_port: A TextSimilarityPort implementation for title scoring.
                             If None, the filter passes all jobs (graceful degradation).
            config: Optional config dict with dot-path keys (e.g.
                    {"vetting": {"role_alignment_threshold": 0.6}}).
        """
        super().__init__(profile)
        self._similarity_port = similarity_port
        self._raw_config: dict = config or {}

    def _cfg(self, key: str, default):
        """Read a dot-path config key from self._raw_config with a fallback.

        Args:
            key: Dot-separated config path, e.g. "vetting.role_alignment_threshold".
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
        """Checks whether the job title aligns with any of the user's desired titles.

        Args:
            job: The Job candidate.

        Returns:
            (True, reason) if best similarity score meets threshold or no desired
            titles are configured. (False, reason) on mismatch.
        """
        prefs = getattr(self.profile, "search_preferences", None)
        desired_titles: list[str] = getattr(prefs, "desired_job_titles", []) or []

        if not desired_titles:
            return True, "no_target_titles_configured"

        if self._similarity_port is None:
            return True, "similarity_port_unavailable"

        job_title = job.title or ""
        scores: list[float] = []
        for title in desired_titles:
            try:
                scores.append(self._similarity_port.get_similarity(job_title, title))
            except Exception as exc:
                logger.warning(
                    "RoleAlignmentFilter: similarity call failed | job=%s title=%s error=%s",
                    job_title, title, exc,
                )
                scores.append(0.0)

        best_score = max(scores, default=0.0)
        best_match = desired_titles[scores.index(best_score)] if scores else ""
        threshold: float = self._cfg("vetting.role_alignment_threshold", 0.6)

        if best_score >= threshold:
            return True, f"role_ok:{best_score:.2f}>={threshold} match='{best_match}'"

        return False, f"role_mismatch:{best_score:.2f}<{threshold} best='{best_match}'"
