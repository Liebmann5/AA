"""Defines the abstract contract for Job Discovery Strategies.

This module provides the `BaseDiscoveryStrategy` ABC. It integrates the
`EvasionManager` to ensure all strategies perform safety checks (CAPTCHA detection)
before attempting to scrape data.
"""


#NOTE ON IMPORT PATHS:
# You are in strategies/.
#     .. -> discovery/              # "One dot up" (..)
#     ... -> domains/               # "Two dots up" (...)
#     .... -> auto_apply/ (Root)
#     ..... -> (Outside Package)



from abc import ABC, abstractmethod

from auto_apply.adapters.secondary.evasion.manager import EvasionManager
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import JobSearchPreferences
from auto_apply.domain.ports.browser_port import BrowserInterface


class BaseDiscoveryStrategy(ABC):
    """The abstract blueprint for a job discovery strategy."""

    def __init__(self, browser: BrowserInterface, search_prefs: JobSearchPreferences):
        """Initializes the strategy.

        Args:
            browser (BrowserInterface): The active browser instance.
            search_prefs (JobSearchPreferences): The user's search criteria.
        """
        self.browser = browser
        self.prefs = search_prefs
        self.evasion = EvasionManager(browser)

    @property
    def name(self) -> str:
        """Returns the user-friendly name of the strategy."""
        return self.__class__.__name__

    def is_blocked(self) -> bool:
        """Checks if the current page is blocked by a CAPTCHA/Firewall.

        Returns:
            bool: True if blocked, False if safe.
        """
        return not self.evasion.check_page_safety()

    @abstractmethod
    def run(self) -> list[Job]:
        """Executes the strategy to find jobs.

        Returns:
            List[Job]: A list of discovered Job objects.
        """
        ...
