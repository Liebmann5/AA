"""Provides a generic, reusable strategy for scraping Search Engine Results Pages (SERPs).

This module contains the `GenericSERPStrategy`. It implements a high-level
algorithm: "Find the list container, iterate through items, parse details."
It relies on dependency injection for the specific finding and parsing logic,
making it adaptable to almost any list-based website (Google, Bing, Indeed).
"""

import json
import logging
import time
from typing import Optional

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
        max_results: int = 30,
    ):
        """Initializes the strategy with specific parsing tools."""
        self.browser = browser
        self.prefs = search_prefs
        self.source_tag = source_tag
        # Resolved per-query result cap (from SearchInstruction.max_results,
        # which the workflow fills from the low-resource-clamped session plan).
        self.max_results = max_results

        self.interruption_handler = InterruptionHandler(browser)
        self.auditor = AuditReporter(browser)

        self.title_parser = title_parser or SmartTextExtractor()
        self.company_parser = company_parser or SmartTextExtractor(strategies=["div.company", "span.company", "a.company"])
        self.url_parser = url_parser or SmartURLExtractor()

        self.miner = SemanticMiner(
            browser=browser,
            title_parser=self.title_parser,
            url_parser=self.url_parser,
            company_parser=self.company_parser
        )

    def execute(self) -> list[Job]:
        """Executes the scraping logic: Audit → Clean → Check JSON‑LD → Scroll → Mine.

        Returns:
            List[Job]: A list of unique, valid jobs found.
        """
        # 1. Audit & Health Check
        self.auditor.log_state(f"{self.source_tag} - Pre-Scrape")

        classifier = PageClassifier(
            self.browser,
            DefaultDetectionStrategy(self.browser),
            self.miner,
        )

        page_type = classifier.classify()

        if page_type in {PageType.CAPTCHA_BLOCK, PageType.LOGIN_REQUIRED, PageType.ERROR_404}:
            logger.warning(f"{self.source_tag}: Page failed health check ({page_type.name}). Aborting strategy.")
            return []

        # 2. Clear Interruptions (Cookies/Popups)
        self.interruption_handler.handle_interruptions()

        # ── 2a. Fast path: JSON‑LD structured data ───────────────────────────
        json_ld_jobs = self._try_extract_json_ld()
        if json_ld_jobs:
            logger.info(
                "%s: Extracted %d jobs via JSON‑LD — skipping scroll+mine.",
                self.source_tag,
                len(json_ld_jobs),
            )
            DiscoveryMathAuditor.audit_final_job_list(json_ld_jobs, self.source_tag)
            return json_ld_jobs

        # 3. The Extraction Loop (Scroll & Mine)
        scroller = InfiniteScrollStrategy(self.browser)

        unique_jobs = {}
        max_scroll_attempts = 5

        logger.info(f"{self.source_tag}: Starting Scroll & Mine Loop...")

        for i in range(max_scroll_attempts):
            batch = self.miner.mine_jobs(source_name=self.source_tag)

            new_count = 0
            for job in batch:
                if job.url not in unique_jobs:
                    unique_jobs[job.url] = job
                    new_count += 1

            logger.info(f"  Loop {i+1}: Found {len(batch)} visible items ({new_count} new).")

            if len(unique_jobs) >= 50:
                logger.info("  Cap reached. Stopping.")
                break

            if not scroller.next_page():
                logger.info("  Infinite Scroll hit bottom (Page did not expand).")
                break

        results = list(unique_jobs.values())
        DiscoveryMathAuditor.audit_final_job_list(results, self.source_tag)
        if not results:
            DiscoveryMathAuditor.audit_candidate_containers([], self.source_tag)
        logger.info(f"{self.source_tag}: Strategy complete. Total unique jobs: {len(results)}")
        return results

    def run(self) -> list[Job]:
        """Executes the scraping logic using 'Harvest-Then-Scroll'."""

        scroller = InfiniteScrollStrategy(self.browser)
        unique_jobs_map = {}
        consecutive_scrolls_without_new_data = 0
        MAX_DRY_SCROLLS = 3
        MAX_TOTAL_JOBS = self.max_results

        logger.info(f"{self.source_tag}: Starting robust infinite scroll extraction...")

        # ── Fast path: JSON‑LD ───────────────────────────────────────────────
        json_ld_jobs = self._try_extract_json_ld()
        if json_ld_jobs:
            logger.info(
                "%s: Extracted %d jobs via JSON‑LD — skipping scroll.",
                self.source_tag,
                len(json_ld_jobs),
            )
            DiscoveryMathAuditor.audit_final_job_list(json_ld_jobs, self.source_tag)
            return json_ld_jobs

        while True:
            # --- PHASE A: HARVEST ---
            visible_jobs = self.miner.mine_jobs(source_name=self.source_tag)
            new_items_in_this_batch = 0

            for job in visible_jobs:
                job_hash = job.url if job.url else f"{job.title}|{job.company}"
                if job_hash not in unique_jobs_map:
                    unique_jobs_map[job_hash] = job
                    new_items_in_this_batch += 1

            logger.info(f"  Batch: Found {len(visible_jobs)} visible, {new_items_in_this_batch} new.")

            # --- PHASE B: EVALUATE PROGRESS ---
            if len(unique_jobs_map) >= MAX_TOTAL_JOBS:
                logger.info("  User defined job limit reached. Stopping.")
                break

            if new_items_in_this_batch == 0:
                consecutive_scrolls_without_new_data += 1
                logger.debug(f"  No new items found. Dry scroll count: {consecutive_scrolls_without_new_data}")
            else:
                consecutive_scrolls_without_new_data = 0

            if consecutive_scrolls_without_new_data >= MAX_DRY_SCROLLS:
                logger.info("  Infinite scroll appears exhausted (multiple dry scrolls). Stopping.")
                break

            if not scroller.next_page():
                logger.info("  Scroller reports end of page/feed.")
                break

            time.sleep(2.0)

        jobs = list(unique_jobs_map.values())
        DiscoveryMathAuditor.audit_final_job_list(jobs, self.source_tag)
        if not jobs:
            DiscoveryMathAuditor.audit_candidate_containers([], self.source_tag)
        return jobs

    # ------------------------------------------------------------------
    # JSON‑LD fast‑path extraction
    # ------------------------------------------------------------------

    def _try_extract_json_ld(self) -> list[Job]:
        """Try to extract job postings from ``application/ld+json`` blocks.

        Uses BeautifulSoup to parse the page source and run the JSON‑LD logic
        without needing the live browser's JavaScript execution.

        Returns:
            List of Job objects; empty list if no JSON‑LD found or parsing fails.
        """
        page_source = ""
        try:
            page_source = getattr(self.browser, "page_source", "") or ""
        except Exception:
            return []

        if 'application/ld+json' not in page_source:
            return []

        try:
            from bs4 import BeautifulSoup  # noqa: PLC0415
        except ImportError:
            logger.debug("BeautifulSoup not available — cannot parse JSON‑LD statically")
            return []

        soup = BeautifulSoup(page_source, "html.parser")
        jobs: list[Job] = []

        for script in soup.find_all("script", type="application/ld+json"):
            content = script.string
            if not content:
                continue
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                continue

            # JSON‑LD can be a single object or a graph (list)
            graph = data.get("@graph", [data])
            if not isinstance(graph, list):
                graph = [graph]

            for item in graph:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    title = item.get("title", "")
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                    url = item.get("url", "")

                    if not url:
                        url = f"https://www.google.com/search?q={title}+{company}+jobs"

                    if title:
                        jobs.append(
                            Job(
                                title=title,
                                company=company,
                                url=url,
                                source=f"{self.source_tag} (JSON‑LD)",
                                location=(
                                    item.get("jobLocation", {})
                                    .get("address", {})
                                    .get("addressLocality")
                                ),
                            )
                        )

        return jobs