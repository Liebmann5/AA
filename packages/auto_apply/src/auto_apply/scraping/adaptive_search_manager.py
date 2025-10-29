"""Provides a resilient, multi-strategy manager for discovering job postings.

This module contains the `AdaptiveSearchManager`, which orchestrates the job
discovery phase of the workflow. It is designed to be highly resilient to
changes in website structure or anti-bot measures by executing a pipeline of
different search strategies in a prioritized order until one succeeds.
"""
import logging
from typing import List
from pathlib import Path
from .search.base_search_strategy import BaseSearchStrategy, StrategyResult, SearchResult
from ..core.browser_interface import BrowserInterface
from ..audit.auditor import audit_and_log_state

logger = logging.getLogger(__name__)

class AdaptiveSearchManager:
    """Manages and executes a pipeline of job search strategies.

    This class allows for the registration of multiple `BaseSearchStrategy`
    implementations. When its `execute` method is called, it attempts to run
    each strategy in the order they were registered. It returns the results
    from the first strategy that completes successfully, making the overall
    search process highly adaptive and resilient.
    """

    def __init__(self, screenshots_dir: Path):
        """
        Initializes the manager.
        Args:
            screenshots_dir: The directory where failure screenshots should be saved.
        """
        self.strategies: List[BaseSearchStrategy] = []
        self.screenshots_dir = screenshots_dir

    def register_strategy(self, strategy: BaseSearchStrategy):
        """Adds a search strategy to the execution pipeline.

        Args:
            strategy: An instantiated object that inherits from `BaseSearchStrategy`.
        """
        self.strategies.append(strategy)

    def execute(self, browser: BrowserInterface) -> List[SearchResult]:
        """Executes the registered search strategies in order until one succeeds.

        This method iterates through the pipeline, performing a comprehensive
        browser audit before and after each strategy attempt. This provides
        invaluable, context-rich data for debugging, especially in cases of
        failure.

        - If a strategy fails gracefully (e.g., CAPTCHA detected), it logs a
          warning and proceeds to the next strategy.
        - If a strategy encounters a critical, unexpected error, it logs the
          error and still proceeds to the next, ensuring maximum resilience.
        - If a strategy succeeds, the process stops, and its results are returned.

        Args:
            browser: The active, framework-agnostic browser adapter instance.

        Returns:
            A list of `SearchResult` objects from the first successful
            strategy. Returns an empty list if all strategies fail.
        """
        if not self.strategies:
            logger.error("No search strategies have been registered.")
            return []

        logger.info(f"Executing adaptive search with {len(self.strategies)} strategies.")

        for strategy in self.strategies:
            strategy_name = strategy.name
            audit_and_log_state(browser, f"Before running {strategy_name}")
            try:
                result = strategy.search()
                if result.success:
                    logger.info(f"Strategy '{strategy_name}' succeeded.")
                    audit_and_log_state(browser, f"After successful {strategy_name}")
                    return result.results
                else:
                    logger.warning(
                        f"Strategy '{strategy_name}' failed gracefully. "
                        f"Reason: {result.failure_reason}. Trying next strategy."
                    )
                    filepath = self.screenshots_dir / f"failure_{strategy_name}.png"
                    browser.save_screenshot(str(filepath))
            except Exception as e:
                logger.error(f"Strategy '{strategy_name}' raised a critical error: {e}", exc_info=True)
                audit_and_log_state(browser, f"After CRITICAL failure in {strategy_name}")
                filepath = self.screenshots_dir / f"critical_failure_{strategy_name}.png"
                browser.save_screenshot(str(filepath))
        logger.critical("All registered search strategies failed.")
        return []