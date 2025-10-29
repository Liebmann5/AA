"""Provides an intelligent and self-healing search strategy for Bing Jobs.

This module contains the `BingGUISearch` strategy, which is designed to be
highly resilient to website changes. It leverages the heuristic analysis
framework to dynamically find job containers rather than relying on brittle,
hardcoded selectors.
"""
import logging
from typing import List, Set
from urllib.parse import urlencode
from pathlib import Path

from ...core.browser_interface import BrowserInterface
from ...user_data.user_profile import JobSearchPreferences
from .base_search_strategy import BaseSearchStrategy, SearchResult, StrategyResult
from ...evasion import detection
from ..utils.page_interruption import ensure_page_is_ready
from selenium.webdriver.common.by import By

from ..utils.heuristic_analyzer import HeuristicSelectorFinder
from ..utils.selector_cache import SelectorCache
from ..utils.heuristic_rules import BingJobRuleSet

logger = logging.getLogger(__name__)

class BingGUISearch(BaseSearchStrategy):
    """An intelligent, adaptive search strategy for Bing Jobs.

    This strategy uses a self-healing framework to discover job postings. It
    first tries a cached "last known good" selector, and if that fails, it
    falls back to a full heuristic analysis of the page to find the job
    container, making it highly resilient to layout changes.
    """

    def __init__(self, browser: BrowserInterface, search_prefs: JobSearchPreferences, max_results: int, cache_path: Path, all_results_list: List[SearchResult], seen_urls_set: Set[str]):
        """Initializes the Bing GUI search strategy.

        Args:
            browser: The framework-agnostic browser adapter instance.
            search_prefs: The user's job search preferences.
            max_results: The maximum number of jobs to scrape.
            cache_path: The path to the directory for caching selectors.
            all_results_list: A mutable list to which all found results are appended.
            seen_urls_set: A mutable set to track URLs and prevent duplicates.
        """
        self.browser = browser
        self.search_prefs = search_prefs
        self.max_results = max_results
        self.all_results = all_results_list
        self.seen_urls = seen_urls_set
        self.cache = SelectorCache(cache_path / "selector_cache_bing.json")

    def _find_job_list_container(self):
        """Finds the main container element holding the job listings.

        This method embodies the self-healing logic of the strategy. It first
        attempts to retrieve a known, working selector from the cache. If the
        cached selector fails or doesn't exist, it triggers the heuristic
        analyzer to scan the page and find a new best selector. The newly
        found selector is then saved to the cache for future runs.

        Returns:
            The `ElementInterface` of the container holding the job listings.

        Raises:
            TimeoutError: If both the cached selector and the heuristic analysis
                fail to find a valid job container.
        """
        by, selector = self.cache.get_selector("bing_jobs_container")
        if selector:
            container = self.browser.wait_for_element(by, selector, timeout=5)
            if container:
                logger.info("Successfully found job container using cached selector.")
                return container
            logger.warning("Cached selector failed. Falling back to heuristic analysis.")

        analyzer = HeuristicSelectorFinder(self.browser, rule_set=BingJobRuleSet())
        by, selector = analyzer.find_best_selector()
        if not selector: raise TimeoutError("Heuristic selector '{selector}' failed verification on Bing.")

        container = self.browser.wait_for_element(by, selector)
        if not container: raise TimeoutError(f"Selector '{selector}' failed for Bing.")

        logger.info(f"Heuristic analysis successful. Caching new selector: '{selector}'")
        self.cache.save_selector("bing_jobs_container", by, selector)
        return container

    def _construct_query_url(self, title: str, location: str) -> str:
        """Builds a valid Bing search URL from the job title and location.

        Args:
            title: The desired job title.
            location: The desired job location.

        Returns:
            A string containing the fully encoded Bing search URL.
        """
        query = f'{title} jobs in {location}'
        return f"https://www.bing.com/search?{urlencode({'q': query})}"

    def search(self) -> StrategyResult:
        """Executes the Bing GUI search and scraping process.

        This method orchestrates the entire lifecycle for a Bing search: it
        loops through the user's search criteria, navigates to the constructed
        URL, handles potential CAPTCHAs, uses the self-healing mechanism to
        find the job container, and extracts the job data.

        Returns:
            A `StrategyResult` indicating the outcome of the search.
        """
        logger.info("--- Executing Strategy: Bing GUI Search (Heuristic Engine) ---")

        for title in self.search_prefs.desired_job_titles:
            for location in self.search_prefs.preferred_locations or ["Remote"]:
                if len(self.all_results) >= self.max_results: break

                query_url = self._construct_query_url(title, location)
                logger.info(f"Navigating to Bing Jobs for query: '{query_url}'")

                try:
                    self.browser.get(query_url)
                    ensure_page_is_ready(self.browser)

                    if detection.is_captcha_present(self.browser):
                        return StrategyResult(success=False, failure_reason="CAPTCHA_DETECTED")

                    job_list_container = self._find_job_list_container()

                    job_elements = job_list_container.find_elements(By.XPATH, "./*")

                    for card in job_elements:
                        if len(self.all_results) >= self.max_results: break
                        try:
                            link_element = card.find_element(By.TAG_NAME, 'a')
                            url = link_element.get_attribute('href')

                            if url and url not in self.seen_urls:
                                text_parts = card.text.split('\n')
                                job_title = text_parts[0]
                                company = text_parts[1]

                                self.seen_urls.add(url)
                                result = SearchResult(url=url, title=job_title, company=company, source="BingGUI-Heuristic")
                                self.all_results.append(result)
                        except Exception:
                            continue
                except Exception as e:
                    logger.error(f"An unexpected error occurred during Bing search for '{title}': {e}", exc_info=True)
                    continue

        logger.info(f"Bing GUI strategy found {len(self.all_results)} potential jobs.")
        return StrategyResult(success=True, results=self.all_results)