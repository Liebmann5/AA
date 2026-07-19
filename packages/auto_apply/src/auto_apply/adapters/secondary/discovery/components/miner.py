"""Provides a context-aware Semantic Miner for extracting job data.

This module implements the 'Mining' phase. It is a pure extraction component.
It traverses the DOM tree (including Iframes) and extracts job data from
visible containers. It relies on the Strategy to handle scrolling/loading.
"""

import logging

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.adapters.secondary.perception.dom_adapter import BaseExtractor

from auto_apply.adapters.secondary.browser.context_manager import ContextManager
from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

class SemanticMiner:
    """Explores the browser context to mine Job objects using heuristic scoring."""

    def __init__(
        self,
        browser: BrowserInterface,
        title_parser: BaseExtractor,
        url_parser: BaseExtractor,
        company_parser: BaseExtractor
    ):
        self.browser = browser
        self.ctx_mgr = ContextManager(browser)
        self.title_parser = title_parser
        self.url_parser = url_parser
        self.company_parser = company_parser

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Recursively scans all contexts to find and extract jobs from CURRENT view."""

        all_jobs: list[Job] = []

        def _scan_context(browser) -> bool:
            # 1. Find Candidates (Broad Search)
            candidates = browser.find_elements(Locator.CSS_SELECTOR, "ul, div[role='list'], div[role='feed'], div[id='search'], div, section, main")  # noqa: E501

            highest_score = 0
            extracted_in_context: list[Job] = []

            for container in candidates:
                try:
                    score, jobs = self._score_and_extract(container, source_name)
                    if score > highest_score:
                        highest_score = score
                        extracted_in_context = jobs
                except Exception:
                    continue

            # If we found a high-confidence container
            if highest_score > 0:
                # logger.debug(f"Miner: Found container with {highest_score} valid jobs in this context.")  # noqa: E501
                all_jobs.extend(extracted_in_context)
                return True

            return False

        # Execute Deep Scan
        self.ctx_mgr.find_context_with_content(_scan_context)

        return all_jobs

    def _score_and_extract(self, container: ElementInterface, source: str) -> tuple[int, list[Job]]:  # noqa: E501
        valid_jobs = []
        try:
            children = container.find_elements(Locator.XPATH, "./*")
            if len(children) < 2:
                return 0, []  # Relaxed constraint

            DiscoveryMathAuditor.audit_candidate_containers([container], 'SemanticMiner')

            for child in children:
                job = self._extract_single_job(child, source)
                if job:
                    valid_jobs.append(job)
                else:
                    DiscoveryMathAuditor.audit_extraction_attempt({}, False, 'SemanticMiner extraction failed')
        except Exception:
            pass

        return len(valid_jobs), valid_jobs

    def _extract_single_job(self, element: ElementInterface, source: str) -> Job | None:
        try:
            # 1. Structural Validation
            size = element.get_size()
            if size[0] < 50 or size[1] < 20:
                return None

            # 2. Extraction
            title = self.title_parser.extract(element)
            url = self.url_parser.extract(element)
            company = self.company_parser.extract(element) or "Unknown"

            # 3. Validation
            if title and url:
                return Job(
                    title=title,
                    company=company,
                    url=url,
                    source=source
                )
        except Exception:
            pass
        return None