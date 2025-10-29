"""Defines the abstract contract for all job search strategies.

This module contains the `BaseSearchStrategy` abstract base class (ABC) and
the `StrategyResult` dataclass. Together, they form a standardized contract
that ensures every search strategy, regardless of the website it targets,
behaves predictably and communicates its outcome in a uniform way to the
`AdaptiveSearchManager`.
"""
from abc import ABC, abstractmethod
from selenium.webdriver.remote.webdriver import WebDriver
from auto_apply.user_data.user_profile import JobSearchPreferences
from .search_result import SearchResult
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class StrategyResult:
    """A standardized data structure for returning the outcome of a search strategy.

    Using a dataclass ensures that every strategy communicates its results in a
    consistent, predictable format, which is essential for the orchestrator
    that calls it.

    Attributes:
        success: A boolean indicating whether the strategy completed without
            encountering a blocking issue (like a CAPTCHA). Note that a
            successful run can still have zero results.
        results: A list of `SearchResult` objects found by the strategy.
        failure_reason: An optional string providing a machine-readable code
            for why a strategy failed (e.g., "CAPTCHA_DETECTED").
    """
    success: bool
    results: List[SearchResult] = field(default_factory=list)
    failure_reason: Optional[str] = None


class BaseSearchStrategy(ABC):
    """The abstract base class that all search strategies must inherit from.

    This class defines the common interface for executing a job search on a
    specific platform (e.g., Google, Bing). It ensures that the
    `AdaptiveSearchManager` can treat all strategy objects interchangeably.
    """

    @property
    def name(self) -> str:
        """Returns the name of the strategy class."""
        return self.__class__.__name__

    @abstractmethod
    def search(self) -> StrategyResult:
        """Executes a single, specific search strategy.

        This method must be implemented by all concrete strategy classes. It
        should contain the entire logic for a single search attempt, including
        navigation, scraping, and handling of expected failures.

        Returns:
            A `StrategyResult` object indicating the outcome of the search.
            - On success (even with 0 jobs found), it should return
              `StrategyResult(success=True, results=[...])`.
            - On a graceful, expected failure (like a CAPTCHA), it should return
              `StrategyResult(success=False, failure_reason="...")`.
            - On an unexpected, critical error, it should raise an exception.
        """
        pass