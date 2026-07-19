"""Defines the abstract contract for all Application Strategies."""

from abc import ABC, abstractmethod

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.browser_port import BrowserInterface


class BaseApplicationStrategy(ABC):
    """The abstract blueprint for an application automation strategy."""

    def __init__(self, browser: BrowserInterface, profile: UserProfile, job: Job):
        self.browser = browser
        self.profile = profile
        self.job = job

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def apply(self) -> bool:
        """Executes the application workflow.

        Returns:
            True if the application was submitted successfully, False otherwise.
        """