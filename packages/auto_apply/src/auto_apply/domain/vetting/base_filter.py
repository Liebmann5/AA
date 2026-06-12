"""Defines the abstract contract for Job Vetting Filters.

This module provides the `BaseVettingFilter` class. All specific logic filters
(Title, Location, Blacklist) must implement this interface. This ensures the
Vetting Engine can chain them together regardless of their internal logic.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile


class BaseVettingFilter(ABC):
    """The abstract contract for a vetting rule.

    A Filter is a deterministic gatekeeper. It analyzes a Job against the UserProfile
    and decides if it is worth pursuing.
    """

    def __init__(self, profile: UserProfile):
        """Initializes the filter with the user's data.

        Args:
            profile (UserProfile): The user's configuration and preferences.
        """
        self.profile = profile

    @property
    def name(self) -> str:
        """Returns the class name for logging."""
        return self.__class__.__name__

    @abstractmethod
    def filter(self, job: Job) -> tuple[bool, str]:
        """Evaluates a job against the filter's logic.

        Args:
            job (Job): The job candidate to evaluate.

        Returns:
            Tuple[bool, str]:
                - bool: True if the job PASSES (keep it). False if it FAILS (drop it).
                - str: A reason for the decision (e.g., "Title Mismatch").
        """
        ...

    def check(self, job: Job) -> tuple[bool, str]:
        """Preferred API alias for filter() — called by VettingWorkflow.

        Args:
            job: The job candidate to evaluate.

        Returns:
            Tuple[bool, str]: (passed, reason).
        """
        return self.filter(job)
