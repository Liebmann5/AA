"""Provides a generic, reusable strategy for scraping Search Engine Results Pages (SERPs).

This module contains the `GenericSERPStrategy`. It implements a high-level
algorithm: "Find the list container, iterate through items, parse details."
It relies on dependency injection for the specific finding and parsing logic,
making it adaptable to almost any list-based website (Google, Bing, Indeed).
"""  # noqa: E501

import logging
import time

# Components
from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.adapters.secondary.discovery.components.miner import SemanticMiner
from auto_apply.application.services.auditing.reporter import AuditReporter
from auto_apply.application.services.dom.classifier import PageClassifier
from auto_apply.application.services.navigation.interruption import InterruptionHandler
from auto_apply.application.services.navigation.pagination import InfiniteScrollStrategy
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import JobSearchPreferences
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import PageType

from auto_apply.adapters.secondary.perception.dom_adapter import (
    BaseExtractor,
    SmartTextExtractor,
    SmartURLExtractor,
)
from auto_apply.adapters.secondary.evasion.detection import DefaultDetectionStrategy

logger = logging.getLogger(__name__)


class GenericSERPStrategy:
    """A reusable blueprint for scraping any page containing a list of search results.

    This class does not know *which* site it is scraping. It simply executes
    the provided extractors on whatever page the browser is currently on.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        search_prefs: JobSearchPreferences,
        source_tag: str,
        title_parser: BaseExtractor | None = None,
        company_parser: BaseExtractor | None = None,
        url_parser: BaseExtractor | None = None,
    ):
        """Initializes the strategy with specific parsing tools.

        Args:
            browser (BrowserInterface): The active browser.
            search_prefs (JobSearchPreferences): User settings.
            source_tag (str): The name to tag jobs with (e.g., "Google").
            title_parser (BaseExtractor): Tool to extract job titles.
            company_parser (BaseExtractor): Tool to extract company names.
            url_parser (BaseExtractor): Tool to extract job links.
        """
        self.browser = browser
        self.prefs = search_prefs
        self.source_tag = source_tag

        #self.health_check = PageHealth(browser)
        self.interruption_handler = InterruptionHandler(browser)
        self.auditor = AuditReporter(browser)

        # Configure Extractors (Default to Smart Extractors if not provided)
        self.title_parser = title_parser or SmartTextExtractor()
        self.company_parser = company_parser or SmartTextExtractor(strategies=["div.company", "span.company", "a.company"])  # noqa: E501
        self.url_parser = url_parser or SmartURLExtractor()

        # Initialize the Miner (The component that actually touches the DOM)
        self.miner = SemanticMiner(
            browser=browser,
            title_parser=self.title_parser,
            url_parser=self.url_parser,
            company_parser=self.company_parser
        )

    def execute(self) -> list[Job]:
        """Executes the scraping logic: Audit -> Clean -> Scroll -> Mine.

        Returns:
            List[Job]: A list of unique, valid jobs found.
        """
        # 1. Audit & Health Check
        self.auditor.log_state(f"{self.source_tag} - Pre-Scrape")

        # Instantiate the classifier with a real detection strategy and the pre-built miner.
        classifier = PageClassifier(
            self.browser,
            DefaultDetectionStrategy(self.browser),
            self.miner,
        )

        page_type = classifier.classify()

        if page_type in {PageType.CAPTCHA_BLOCK, PageType.LOGIN_REQUIRED, PageType.ERROR_404}:  # noqa: E501
            logger.warning(f"{self.source_tag}: Page failed health check ({page_type.name}). Aborting strategy.")  # noqa: E501
            return []

        # 2. Clear Interruptions (Cookies/Popups)
        self.interruption_handler.handle_interruptions()

        # 3. The Extraction Loop (Scroll & Mine)
        # We delegate scrolling to the InfiniteScrollStrategy
        scroller = InfiniteScrollStrategy(self.browser)

        unique_jobs = {}
        max_scroll_attempts = 5  # Safety cap to prevent infinite loops

        logger.info(f"{self.source_tag}: Starting Scroll & Mine Loop...")

        for i in range(max_scroll_attempts):
            # A. Mine visible jobs
            batch = self.miner.mine_jobs(source_name=self.source_tag)

            new_count = 0
            for job in batch:
                if job.url not in unique_jobs:
                    unique_jobs[job.url] = job
                    new_count += 1

            logger.info(f"  Loop {i+1}: Found {len(batch)} visible items ({new_count} new).")  # noqa: E501

            # B. Stop Conditions
            if len(unique_jobs) >= 50: # Cap per query to keep it fast
                logger.info("  Cap reached. Stopping.")
                break

            # C. Scroll
            if not scroller.next_page():
                logger.info("  Infinite Scroll hit bottom (Page did not expand).")
                break

        results = list(unique_jobs.values())
        DiscoveryMathAuditor.audit_final_job_list(results, self.source_tag)
        if not results:
            DiscoveryMathAuditor.audit_candidate_containers([], self.source_tag)
        logger.info(f"{self.source_tag}: Strategy complete. Total unique jobs: {len(results)}")  # noqa: E501
        return results

    def run(self) -> list[Job]:
        """Executes the scraping logic using 'Harvest-Then-Scroll'."""

        # 1. Setup
        scroller = InfiniteScrollStrategy(self.browser)
        unique_jobs_map = {} # Key: Hash of (Title + Company), Value: Job Object

        # Safety circuit breakers
        consecutive_scrolls_without_new_data = 0
        MAX_DRY_SCROLLS = 3  # If we scroll 3 times and find nothing new, stop.
        # FIXED attribute reference error here
        MAX_TOTAL_JOBS = getattr(self.prefs, "max_search_results", 30)

        logger.info(f"{self.source_tag}: Starting robust infinite scroll extraction...")

        while True:
            # --- PHASE A: HARVEST ---
            # Extract everything currently visible on screen.
            # CRITICAL: We extract DATA now. We do not store Element References.
            visible_jobs = self.miner.mine_jobs(source_name=self.source_tag)

            new_items_in_this_batch = 0

            for job in visible_jobs:
                # Create a stable fingerprint for the job
                # We use URL if available, otherwise Title+Company
                job_hash = job.url if job.url else f"{job.title}|{job.company}"

                if job_hash not in unique_jobs_map:
                    unique_jobs_map[job_hash] = job
                    new_items_in_this_batch += 1

            logger.info(f"  Batch: Found {len(visible_jobs)} visible, {new_items_in_this_batch} new.")  # noqa: E501

            # --- PHASE B: EVALUATE PROGRESS ---

            # Check User Limit
            if len(unique_jobs_map) >= MAX_TOTAL_JOBS:
                logger.info("  User defined job limit reached. Stopping.")
                break

            # Check for "Dry Spells" (The fix for Virtualization)
            if new_items_in_this_batch == 0:
                consecutive_scrolls_without_new_data += 1
                logger.debug(f"  No new items found. Dry scroll count: {consecutive_scrolls_without_new_data}")  # noqa: E501
            else:
                # Reset counter if we found something, because there might be more
                consecutive_scrolls_without_new_data = 0

            if consecutive_scrolls_without_new_data >= MAX_DRY_SCROLLS:
                logger.info("  Infinite scroll appears exhausted (multiple dry scrolls). Stopping.")  # noqa: E501
                break

            # --- PHASE C: SCROLL ---
            # We attempt to scroll. If the SCROLLER fails (physically can't move), we also stop.  # noqa: E501
            if not scroller.next_page():
                logger.info("  Scroller reports end of page/feed.")
                break

            # Evasion pause is handled inside scroller.next_page() usually,
            # but ensure we wait for network stability here.
            time.sleep(2.0)

        # return list(unique_jobs_map.values())
        jobs = list(unique_jobs_map.values())
        DiscoveryMathAuditor.audit_final_job_list(jobs, self.source_tag)
        if not jobs:
            DiscoveryMathAuditor.audit_candidate_containers([], self.source_tag)
        return jobs