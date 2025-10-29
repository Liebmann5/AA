"""Provides multiple, resilient strategies for scraping Google's job search UI.

This module contains concrete implementations of the `BaseSearchStrategy` for
interacting with Google. Due to the complexity and high level of protection on
Google's search pages, this module provides two different approaches:

1.  `GoogleDirectURLSearch`: A fast but potentially more detectable strategy
    that constructs a precise URL to land directly on the job results page.
2.  `GoogleHumanTypingSearch`: A slower but more evasive strategy that mimics
    a human user by navigating to the homepage and typing a search query.

Both strategies inherit from `GoogleCommon` to share state and utility methods.
"""
import logging
import time
import json
import random
from typing import List, Set
from pathlib import Path
from urllib.parse import urlencode

from ...core.browser_interface import BrowserInterface, ElementInterface
from ...user_data.user_profile import JobSearchPreferences
from .base_search_strategy import BaseSearchStrategy, SearchResult, StrategyResult
from ...evasion import behavior, detection
from ..utils.heuristic_analyzer import HeuristicSelectorFinder
from ..utils.selector_cache import SelectorCache
from ..utils.heuristic_rules import GoogleJobRuleSet
from ..utils.page_interruption import ensure_page_is_ready
from ..utils.pagination_strategy import KeywordPaginationStrategy, NumberedPaginationStrategy, ArrowPaginationStrategy
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

logger = logging.getLogger(__name__)

class GoogleCommon(BaseSearchStrategy):
    """A base class providing shared state and utilities for Google search strategies.

    This class is not intended to be used directly. It holds common attributes
    like the browser instance, search preferences, and pagination logic that
    are shared between different Google-specific search strategies to avoid
    code duplication.
    """

    def __init__(self, browser: BrowserInterface, search_prefs: JobSearchPreferences, max_results: int, cache_path: Path, all_results_list: List[SearchResult], seen_urls_set: Set[str]):
        """Initializes the common state for Google strategies.

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
        self.cache = SelectorCache(cache_path / "selector_cache.json")
        self.all_results = all_results_list
        self.seen_urls = seen_urls_set
        self.current_page_number = 1
        self.pagination_strategies = [ArrowPaginationStrategy(self.browser), NumberedPaginationStrategy(self.browser, self), KeywordPaginationStrategy(self.browser)]

    def search(self) -> StrategyResult:
        """Abstract method to be implemented by concrete subclasses."""
        raise NotImplementedError("This method must be implemented by subclasses")

class GoogleDirectURLSearch(GoogleCommon):
    """A search strategy that navigates directly to a pre-constructed Google Jobs URL."""

    def _find_job_list_container(self) -> ElementInterface:
        """Finds the main job container using a golden selector with a heuristic fallback."""
        logger.info("Attempting to find job container with 'Golden Selector' strategy.")
        golden_selector = (By.ID, "Odp5De")
        try:
            container = self.browser.find_element(*golden_selector)
            if container:
                logger.info("Golden Selector found. Proceeding with high confidence.")
                return container
        except Exception:
            logger.warning("Golden Selector failed. Falling back to full-page heuristic analysis.")
        analyzer = HeuristicSelectorFinder(self.browser, rule_set=GoogleJobRuleSet())
        by, selector = analyzer.find_best_selector()
        if not selector: raise TimeoutError("Heuristic analysis failed as a fallback.")
        container = self.browser.wait_for_element(by, selector)
        if not container: raise TimeoutError(f"Heuristic selector '{selector}' failed.")
        return container
    def _extract_jobs_from_json(self, container_element: ElementInterface) -> List[SearchResult]:
        """
        Attempts to find and parse job data embedded in a JSON script tag.
        This is the primary, most reliable method for data extraction on Google.
        """
        try:
            json_script_element = container_element.find_element(By.XPATH, ".//script[contains(text(), 'window.google.search.immersive.jobs.config')]")
            if not json_script_element:
                return []

            script_content = json_script_element.text
            json_start_index = script_content.find('{"provider_id"')
            if json_start_index == -1:
                return []

            json_end_index = script_content.rfind("}');")
            if json_end_index == -1:
                json_end_index = len(script_content)

            json_string = script_content[json_start_index:json_end_index]
            json_data = json.loads(json_string)
            job_results = json_data.get("initial_results", {}).get("results", [])
            extracted = []
            for job_blob in job_results:
                job_data = job_blob.get("job", {})
                if not job_data: continue

                url = job_data.get("url")
                title = job_data.get("title")
                company = job_data.get("company_name")

                if url and title and company:
                    extracted.append(SearchResult(url=url, title=title, company=company, source="GoogleJSON"))

            if extracted:
                logger.info(f"Successfully extracted {len(extracted)} jobs from embedded JSON.")
            return extracted
        except Exception:
            logger.warning("Could not find or parse embedded job JSON. Falling back to HTML scraping.", exc_info=True)
            return []
    def _extract_jobs_from_html(self, container_element: ElementInterface) -> List[SearchResult]:
        """
        Fallback method to scrape job data directly from HTML elements.
        This is less reliable than JSON but essential as a backup.
        """
        extracted = []
        job_cards = container_element.find_elements(By.CSS_SELECTOR, "div[role='row']")

        for card in job_cards:
            try:
                link_element = card.find_element(By.CSS_SELECTOR, "a[role='link']")
                url = link_element.get_attribute('href')
                if not url: continue

                title = card.find_element(By.CSS_SELECTOR, "div[role='heading']").text
                company = card.find_element(By.CSS_SELECTOR, "div[jsname='vHQ7hf']").text

                if title and company:
                    extracted.append(SearchResult(url=url, title=title, company=company, source="GoogleHTML"))
            except Exception:
                continue

        if extracted:
            logger.info(f"Successfully extracted {len(extracted)} jobs via HTML fallback.")
        return extracted
    def _handle_pagination(self) -> bool:
        """
        Tries multiple pagination strategies in order to find and click the next page element.
        """
        logger.debug("Attempting to find and click next page button...")
        for strategy in self.pagination_strategies:
            try:
                if strategy.find_and_click():
                    logger.info(f"Pagination successful using {strategy.__class__.__name__}.")
                    time.sleep(random.uniform(2.5, 4.0))
                    ensure_page_is_ready(self.browser)
                    return True
            except Exception as e:
                logger.debug(f"Pagination strategy {strategy.__class__.__name__} failed: {e}")
                continue
        logger.info("All pagination strategies failed. Reached the last page of results.")
        return False
    def _scrape_loop(self):
        """The main loop for extracting data and handling pagination for a single query."""
        try:
            job_list_container = self._find_job_list_container()
        except TimeoutError as e:
            logger.error(f"Could not find job container on page: {e}")
            return

        page_count = 1
        while len(self.all_results) < self.max_results:
            logger.info(f"Scraping page {page_count}...")

            newly_found_jobs = self._extract_jobs_from_json(job_list_container)

            if not newly_found_jobs:
                newly_found_jobs = self._extract_jobs_from_html(job_list_container)

            if not newly_found_jobs:
                logger.warning("No jobs found on the current page. Ending search for this query.")
                break

            jobs_added_this_page = 0
            for job in newly_found_jobs:
                if job.url not in self.seen_urls:
                    self.seen_urls.add(job.url)
                    self.all_results.append(job)
                    jobs_added_this_page += 1

            logger.info(f"Added {jobs_added_this_page} new unique jobs from this page.")

            if jobs_added_this_page == 0 and page_count > 1:
                logger.info("No new unique jobs found on this page. Ending pagination.")
                break

            if len(self.all_results) >= self.max_results:
                logger.info(f"Reached max results limit of {self.max_results}.")
                break

            if not self._handle_pagination():
                break

            page_count += 1

    def _construct_search_url(self, title, location, experience_levels):
        """Builds a URL with query parameters for Google's job search interface."""
        query_parts = [f'"{title}"']
        if location: query_parts.append(f'in "{location}"')
        params = {"q": f'{" ".join(query_parts)} jobs', "ibp": "htl;jobs", "htivrt": 'jobs'}
        chips = ["date_posted:today"] + [f"req_exp:{level}" for level in experience_levels or []]
        params['htichips'] = ",".join(chips)
        return f"https://www.google.com/search?{urlencode(params)}"

    def search(self) -> StrategyResult:
        """Executes the direct URL search strategy.

        This method iterates through the user's desired job titles and locations,
        constructs a highly specific URL for each combination, navigates to it,
        and then initiates the scraping process.

        Returns:
            A `StrategyResult` indicating the outcome of the search.
        """
        logger.info("--- Executing Strategy: Google Direct URL ---")
        for title in self.search_prefs.desired_job_titles:
            for location in self.search_prefs.preferred_locations or ["Remote"]:
                if len(self.all_results) >= self.max_results: break
                query_url = self._construct_search_url(title, location, self.search_prefs.experience_level)
                self.browser.get(query_url)
                ensure_page_is_ready(self.browser)
                if not self.browser.wait_for_element(By.ID, "rcnt", timeout=25): return StrategyResult(success=False, failure_reason="PAGE_LOAD_TIMEOUT")
                if detection.is_captcha_present(self.browser): return StrategyResult(success=False, failure_reason="CAPTCHA_DETECTED")
                self._scrape_loop()
        return StrategyResult(success=True, results=self.all_results)

class GoogleHumanTypingSearch(GoogleCommon):
    """A search strategy that mimics a human typing a query on the Google homepage."""

    def _find_job_list_container(self) -> ElementInterface:
        """Finds the main job container using a golden selector with a heuristic fallback."""
        logger.info("Attempting to find job container with 'Golden Selector' strategy.")
        golden_selector = (By.ID, "Odp5De")
        try:
            container = self.browser.find_element(*golden_selector)
            if container:
                logger.info("Golden Selector found. Proceeding with high confidence.")
                return container
        except Exception:
            logger.warning("Golden Selector failed. Falling back to full-page heuristic analysis.")
        analyzer = HeuristicSelectorFinder(self.browser, rule_set=GoogleJobRuleSet())
        by, selector = analyzer.find_best_selector()
        if not selector: raise TimeoutError("Heuristic analysis failed as a fallback.")
        container = self.browser.wait_for_element(by, selector)
        if not container: raise TimeoutError(f"Heuristic selector '{selector}' failed.")
        return container
    def _extract_jobs_from_json(self, container_element: ElementInterface) -> List[SearchResult]:
        """
        Attempts to find and parse job data embedded in a JSON script tag.
        This is the primary, most reliable method for data extraction on Google.
        """
        try:
            json_script_element = container_element.find_element(By.XPATH, ".//script[contains(text(), 'window.google.search.immersive.jobs.config')]")
            if not json_script_element:
                return []

            script_content = json_script_element.text
            json_start_index = script_content.find('{"provider_id"')
            if json_start_index == -1:
                return []

            json_end_index = script_content.rfind("}');")
            if json_end_index == -1:
                json_end_index = len(script_content)

            json_string = script_content[json_start_index:json_end_index]
            json_data = json.loads(json_string)
            job_results = json_data.get("initial_results", {}).get("results", [])
            extracted = []
            for job_blob in job_results:
                job_data = job_blob.get("job", {})
                if not job_data: continue

                url = job_data.get("url")
                title = job_data.get("title")
                company = job_data.get("company_name")

                if url and title and company:
                    extracted.append(SearchResult(url=url, title=title, company=company, source="GoogleJSON"))
            if extracted:
                logger.info(f"Successfully extracted {len(extracted)} jobs from embedded JSON.")
            return extracted
        except Exception:
            logger.warning("Could not find or parse embedded job JSON. Falling back to HTML scraping.", exc_info=True)
            return []
    def _extract_jobs_from_html(self, container_element: ElementInterface) -> List[SearchResult]:
        """
        Fallback method to scrape job data directly from HTML elements.
        This is less reliable than JSON but essential as a backup.
        """
        extracted = []
        job_cards = container_element.find_elements(By.CSS_SELECTOR, "div[role='row']")

        for card in job_cards:
            try:
                link_element = card.find_element(By.CSS_SELECTOR, "a[role='link']")
                url = link_element.get_attribute('href')
                if not url: continue

                title = card.find_element(By.CSS_SELECTOR, "div[role='heading']").text
                company = card.find_element(By.CSS_SELECTOR, "div[jsname='vHQ7hf']").text

                if title and company:
                    extracted.append(SearchResult(url=url, title=title, company=company, source="GoogleHTML"))
            except Exception:
                continue
        if extracted:
            logger.info(f"Successfully extracted {len(extracted)} jobs via HTML fallback.")
        return extracted
    def _handle_pagination(self) -> bool:
        """
        Tries multiple pagination strategies in order to find and click the next page element.
        """
        logger.debug("Attempting to find and click next page button...")
        for strategy in self.pagination_strategies:
            try:
                if strategy.find_and_click():
                    logger.info(f"Pagination successful using {strategy.__class__.__name__}.")
                    time.sleep(random.uniform(2.5, 4.0))
                    ensure_page_is_ready(self.browser)
                    return True
            except Exception as e:
                logger.debug(f"Pagination strategy {strategy.__class__.__name__} failed: {e}")
                continue
        logger.info("All pagination strategies failed. Reached the last page of results.")
        return False
    def _scrape_loop(self):
        """The main loop for extracting data and handling pagination for a single query."""
        try:
            job_list_container = self._find_job_list_container()
        except TimeoutError as e:
            logger.error(f"Could not find job container on page: {e}")
            return

        page_count = 1
        while len(self.all_results) < self.max_results:
            logger.info(f"Scraping page {page_count}...")

            newly_found_jobs = self._extract_jobs_from_json(job_list_container)

            if not newly_found_jobs:
                newly_found_jobs = self._extract_jobs_from_html(job_list_container)

            if not newly_found_jobs:
                logger.warning("No jobs found on the current page. Ending search for this query.")
                break

            jobs_added_this_page = 0
            for job in newly_found_jobs:
                if job.url not in self.seen_urls:
                    self.seen_urls.add(job.url)
                    self.all_results.append(job)
                    jobs_added_this_page += 1
            logger.info(f"Added {jobs_added_this_page} new unique jobs from this page.")

            if jobs_added_this_page == 0 and page_count > 1:
                logger.info("No new unique jobs found on this page. Ending pagination.")
                break

            if len(self.all_results) >= self.max_results:
                logger.info(f"Reached max results limit of {self.max_results}.")
                break

            if not self._handle_pagination():
                break

            page_count += 1

    def _construct_query_text(self, title, location):
        """Builds a simple, human-readable search string."""
        return f'"{title}" in "{location}" jobs'

    def search(self) -> StrategyResult:
        """Executes the human-like typing search strategy.

        This method first navigates to the Google homepage, finds the search
        bar, types the job query with human-like delays, and then initiates
        the scraping process on the results page.

        Returns:
            A `StrategyResult` indicating the outcome of the search.
        """
        logger.info("--- Executing Strategy: Google Human Typing ---")
        self.browser.get("https://www.google.com")
        ensure_page_is_ready(self.browser)
        if detection.is_captcha_present(self.browser): return StrategyResult(success=False, failure_reason="CAPTCHA_ON_HOMEPAGE")
        for title in self.search_prefs.desired_job_titles:
            for location in self.search_prefs.preferred_locations or ["Remote"]:
                if len(self.all_results) >= self.max_results: break
                query_text = self._construct_query_text(title, location)
                search_bar = self.browser.wait_for_element(By.CSS_SELECTOR, "textarea[name='q']")
                if not search_bar: return StrategyResult(success=False, failure_reason="SEARCH_BAR_NOT_FOUND")
                behavior.human_like_typing(search_bar, query_text)
                search_bar.send_keys(Keys.RETURN)
                ensure_page_is_ready(self.browser)
                if not self.browser.wait_for_element(By.ID, "rcnt", timeout=25): return StrategyResult(success=False, failure_reason="RESULTS_PAGE_LOAD_TIMEOUT")
                if detection.is_captcha_present(self.browser): return StrategyResult(success=False, failure_reason="CAPTCHA_TRIGGERED_BY_SEARCH")
                self._scrape_loop()
        return StrategyResult(success=True, results=self.all_results)