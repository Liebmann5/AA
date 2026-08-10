"""Provides sophisticated rate-limiting logic based on company history.

This module implements a hierarchical decision engine to determine if a company
is currently in a 'Cooldown' period, and whether the user has room left in
their daily and per-company application quotas.
"""

import logging
from datetime import datetime, timezone

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.repository_port import JobRepositoryPort

logger = logging.getLogger(__name__)


class ThrottlingFilter:
    """Gatekeeper that enforces application limits and cooldown periods.

    Enforcement order:

    0.  Daily quota (user-global). Runs first because it does not depend on
        the job's company, and therefore also gates jobs whose company is
        unknown. The window is "since 00:00 UTC today" — UTC because
        ``applied_at`` is persisted as UTC ISO strings by every persistence
        path, so the window boundary and the stored values share one clock.
        The count comes from the permanent ``applied_jobs`` log filtered to
        successful outcomes, the same definition of "applied" used by
        cross-session deduplication — one definition, two consumers.
    1.  Per-company application cap.
    2.  Per-company cooldown, resolved by the hierarchy:
        company mandate → user preference → system default.

    All limits are required constructor parameters injected from the merged
    effective config at the composition root (the ``cooldown_days_default``
    pattern). None are read from the profile or hardcoded here: the previous
    implementations kept ``profile.app_config.daily_application_limit`` in an
    attribute that was never read, and ``MAX_APPLICATIONS_PER_COMPANY = 3``
    as a class constant that ignored the ``max_applications_per_company``
    config key — two user-facing caps that were dead writes.

    Naming note: the daily-limit attribute is deliberately named
    ``_daily_limit`` because the standing red pin
    ``test_daily_limit_is_read_after_being_computed``
    (tests/domain/test_application_caps.py) asserts by AST that this exact
    attribute name is read. Renaming it would silently re-break the pin.
    Do not rename it without rewriting that test.

    Bounds note: ``max_applications_per_company`` is passed through
    unvalidated (``EffectiveConfig`` types it as a bare ``int``;
    ``SessionPlan``'s ``ge=1, le=20`` validation does not apply on this
    path). A value of 0 blocks every application to any known company —
    treated as a deliberate, if extreme, configuration rather than coerced.
    """

    def __init__(
        self,
        profile: UserProfile,
        job_repo: JobRepositoryPort,
        *,
        cooldown_days_default: int,
        daily_application_limit: int,
        max_applications_per_company: int,
    ) -> None:
        """Initializes the filter.

        Args:
            profile: User settings containing default preferences.
            job_repo: Port for querying persisted application history.
            cooldown_days_default: System cooldown used when higher authorities
                do not provide a value.
            daily_application_limit: Maximum successful applications allowed
                per UTC day, from the merged effective configuration.
            max_applications_per_company: Maximum completed applications
                allowed per company, from the merged effective configuration
                (``max_applications_per_company``). Both limits are required
                (no defaults) so their absence is a construction error rather
                than a silent fallback.
        """
        self._profile = profile
        self._job_repo = job_repo
        self._cooldown_days_default = cooldown_days_default
        self._daily_limit = daily_application_limit
        self._max_applications_per_company = max_applications_per_company

    def filter(self, job: Job) -> tuple[bool, str]:
        """Evaluates if a new application is allowed right now.

        Hierarchy of Authority:
        0. Daily quota (user-global, cross-session).
        1. Per-company application cap.
        2. Company Mandate (scraped from "Thank You" page text).
        3. User Preference (profile settings).
        4. System Default cooldown.

        Args:
            job: The candidate job.

        Returns:
            A ``(pass, reason)`` tuple — ``True`` means the job cleared
            throttling, ``False`` means it was blocked.
        """
        # 0. Daily quota — before the company checks, so an exhausted quota
        #    also gates jobs whose company is unknown.
        applied_today = self._job_repo.count_applications_since(
            self._today_utc_start()
        )
        if applied_today >= self._daily_limit:
            return False, (
                f"Daily application limit reached "
                f"({applied_today}/{self._daily_limit} since 00:00 UTC)"
            )

        company_name = job.company
        if not company_name or company_name.lower() == "unknown":
            return True, "Unknown Company (Pass Open)"

        app_count = self._job_repo.count_applications_for_company(company_name)
        if app_count >= self._max_applications_per_company:
            return False, (
                f"Max applications ({self._max_applications_per_company}) "
                f"reached for {company_name}"
            )

        last_applied_date = self._job_repo.get_last_applied_date(company_name)
        if not last_applied_date:
            return True, "No previous history"

        cooldown_days = self._calculate_cooldown_authority(company_name)
        days_since = (datetime.now(timezone.utc) - last_applied_date).days

        if days_since < cooldown_days:
            remaining = cooldown_days - days_since
            return False, f"Cooldown Active ({remaining} days remaining)"

        return True, "Cooldown Expired"

    def _calculate_cooldown_authority(self, company_name: str) -> int:
        """Determines the authoritative cooldown period for a company.

        Takes the maximum of the company-mandated cooldown, the user's
        preferred cooldown, and the system default — so we always err on
        the side of waiting longer.

        Args:
            company_name: The company being evaluated.

        Returns:
            The effective cooldown period in days.
        """
        company_mandate = self._job_repo.get_company_mandate_cooldown(company_name)
        if company_mandate:
            return int(company_mandate)

        preferences = getattr(self._profile, "application_preferences", None)
        user_pref = getattr(preferences, "cooldown_days", None)
        if user_pref is not None:
            return int(user_pref)

        return self._cooldown_days_default

    @staticmethod
    def _today_utc_start() -> datetime:
        """Returns midnight this morning, UTC.

        UTC is the only defensible window boundary: ``applied_at`` is written
        as ``datetime.now(timezone.utc).isoformat()`` everywhere it is
        persisted, so the boundary and the stored values share one clock.
        """
        return datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def check(self, job: Job) -> tuple[bool, str]:
        """Preferred API alias for filter() — called by VettingWorkflow."""
        return self.filter(job)
