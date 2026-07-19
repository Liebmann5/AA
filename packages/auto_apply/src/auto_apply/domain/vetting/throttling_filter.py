"""Provides sophisticated rate-limiting logic based on company history.

This module implements a hierarchical decision engine to determine if a company
is currently in a 'Cooldown' period.
"""

import logging
from datetime import datetime, timezone

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.repository_port import JobRepositoryPort

logger = logging.getLogger(__name__)


class ThrottlingFilter:
    """Gatekeeper that enforces application limits and cooldown periods."""

    MAX_APPLICATIONS_PER_COMPANY: int = 3

    def __init__(
        self,
        profile: UserProfile,
        job_repo: JobRepositoryPort,
        *,
        cooldown_days_default: int,
    ) -> None:
        """Initializes the filter.

        Args:
            profile: User settings containing default preferences.
            job_repo: Port for querying persisted application history.
            cooldown_days_default: System cooldown used when higher authorities
                do not provide a value.
        """
        self._profile = profile
        self._job_repo = job_repo
        self._cooldown_days_default = cooldown_days_default
        self._daily_limit: int = getattr(
            getattr(profile, "app_config", None),
            "daily_application_limit",
            200,
        )

    def filter(self, job: Job) -> tuple[bool, str]:
        """Evaluates if the job's company allows a new application.

        Hierarchy of Authority:
        1. Company Mandate (scraped from "Thank You" page text).
        2. User Preference (profile settings).
        3. System Default (180 days).

        Args:
            job: The candidate job.

        Returns:
            A ``(pass, reason)`` tuple — ``True`` means the job cleared
            throttling, ``False`` means it was blocked.
        """
        company_name = job.company
        if not company_name or company_name.lower() == "unknown":
            return True, "Unknown Company (Pass Open)"

        app_count = self._job_repo.count_applications_for_company(company_name)
        if app_count >= self.MAX_APPLICATIONS_PER_COMPANY:
            limit = self.MAX_APPLICATIONS_PER_COMPANY
            return False, f"Max applications ({limit}) reached for {company_name}"

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

    def check(self, job: Job) -> tuple[bool, str]:
        """Preferred API alias for filter() — called by VettingWorkflow."""
        return self.filter(job)
