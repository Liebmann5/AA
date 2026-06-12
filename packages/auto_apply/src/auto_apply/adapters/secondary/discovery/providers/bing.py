"""Provides the specific search provider for Bing Jobs.

This module implements the Bing-specific logic. It acts as the 'Foreman',
configuring the generic SERP strategy with the specific CSS selectors and
URL parameters required to scrape Bing's job search interface.
"""

import logging
from urllib.parse import urlencode

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.adapters.secondary.perception.dom_adapter import (
    SmartTextExtractor,
    SmartURLExtractor,
)
from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    DirectURLNavigation,
    HumanSearchNavigation,
    ResilientNavigator,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.adapters.secondary.evasion.components import behavior
from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)


class BingProvider(BaseSearchProvider):
    """A provider that finds jobs via Bing's job search aggregation."""

    def __init__(self, browser: BrowserInterface, context: ExecutionContext) -> None:
        super().__init__(browser, context)
        self.navigator = ResilientNavigator(browser, [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ])

    def _is_page_healthy(self) -> bool:
        if self.evasion is not None and not self.evasion.check_page_safety():
            return False
        return True

    def run(self, override_criteria: dict | None = None) -> list[Job]:
        """Executes the Bing search workflow.

        It iterates through the user's criteria, navigates to Bing, and
        deploys the generic strategy to extract job cards.
        """
        all_jobs: list[Job] = []

        for title in self.prefs.desired_job_titles:
            locations = self.prefs.preferred_locations or ["Remote"]

            for location in locations:
                url = self._construct_url(title, location)
                context_data = {"query": title, "location": location}
                logger.info(
                    "BingProvider: Processing query '%s' in '%s'",
                    title,
                    location,
                )

                if not self.navigator.navigate_with_fallback(
                    url, context_data, self._is_page_healthy
                ):
                    logger.warning("Skipping URL due to safety/throttling checks.")
                    continue

                behavior.simulate_idle_time(
                    self.browser, min_seconds=2.0, max_seconds=3.0
                )

                scraper = GenericSERPStrategy(
                    browser=self.browser,
                    search_prefs=self.prefs,
                    source_tag="Bing",
                    title_parser=SmartTextExtractor(
                        strategies=[
                            "h2",
                            "a.jobLink",
                            ".jobCardTitle",
                        ]
                    ),
                    company_parser=SmartTextExtractor(
                        strategies=[
                            ".b_factrow",
                            ".companyName",
                            "span[class*='company']",
                        ]
                    ),
                    url_parser=SmartURLExtractor(),
                )

                html_jobs = scraper.execute()
                all_jobs.extend(html_jobs)

        return self._deduplicate(all_jobs)

    def _construct_url(self, title: str, location: str) -> str:
        """Builds the Bing Jobs URL."""
        query = f"{title} jobs in {location}"
        params = {"q": query}
        return f"https://www.bing.com/jobs?{urlencode(params)}"

    def _deduplicate(self, jobs: list[Job]) -> list[Job]:
        """Removes duplicate jobs based on URL."""
        unique_map = {job.url: job for job in jobs}
        return list(unique_map.values())
