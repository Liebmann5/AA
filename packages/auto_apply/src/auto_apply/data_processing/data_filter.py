"""Provides a class for filtering and cleaning raw search results.

This module contains the `DataFilter`, which is responsible for the initial
processing of job search results. It prepares the raw data from the scraping
phase, ensuring it is clean and ready for the application workflow.
"""
import logging
from typing import List
from ..scraping.search.search_result import SearchResult
from ..user_data.applied_jobs_manager import AppliedJobsManager

logger = logging.getLogger(__name__)

class DataFilter:
    """Cleans a list of SearchResult objects by removing duplicates and applied-to jobs.

    This class performs a two-stage filtering process:
    1.  **Deduplication:** It removes any duplicate job postings from the raw
        list based on their unique URLs.
    2.  **History Check:** It removes any jobs that already exist in the
        `AppliedJobsManager` database, ensuring the agent does not re-apply
        to the same position.
    """

    def __init__(self, job_manager: AppliedJobsManager):
        """Initializes the filter with a connection to the job database.

        Args:
            job_manager: An instantiated `AppliedJobsManager` that provides access
                to the database of previously applied-to jobs.
        """
        self.jobs_manager = job_manager

    def filter_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Processes and cleans a list of raw search results.

        This is the main public method of the class. It takes a raw list of
        `SearchResult` objects and applies the two-stage filtering process.

        Args:
            results: A list of `SearchResult` objects, typically from an
                `AdaptiveSearchManager` run.

        Returns:
            A cleaned list of `SearchResult` objects, containing only unique
            jobs that have not been previously applied to. This list is
            ready for the next stage of the workflow.
        """
        logger.info("Starting data filtering process on %d raw results.", len(results))

        unique_results: List[SearchResult] = []
        seen_urls = set()
        for result in results:
            if result.url not in seen_urls:
                unique_results.append(result)
                seen_urls.add(result.url)

        num_duplicates = len(results) - len(unique_results)
        if num_duplicates > 0:
            logger.info("Removed %d duplicate results.", num_duplicates)

        final_results: List[SearchResult] = []
        for result in unique_results:
            if not self.jobs_manager.has_been_applied_to(result.url):
                final_results.append(result)

        num_applied = len(unique_results) - len(final_results)
        if num_applied > 0:
            logger.info("Removed %d jobs that have been previously applied to.", num_applied)

        logger.info("Filtering complete. %d jobs remain for processing.", len(final_results))
        return final_results