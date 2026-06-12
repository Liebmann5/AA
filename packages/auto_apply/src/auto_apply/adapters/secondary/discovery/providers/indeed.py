"""Provides the specific search strategy for Indeed Jobs."""

import logging
from urllib.parse import urlencode

from auto_apply.adapters.secondary.perception.dom_adapter import SmartTextExtractor

from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    DirectURLNavigation,
    HumanSearchNavigation,
    ResilientNavigator,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.adapters.secondary.evasion.strategies.base import BaseDiscoveryStrategy
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import JobSearchPreferences
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort

logger = logging.getLogger(__name__)


class IndeedProvider(BaseDiscoveryStrategy, DiscoveryProviderPort):
    """A provider that navigates to Indeed to discover job listings."""

    def __init__(self, browser: BrowserInterface, search_prefs: JobSearchPreferences):
        super().__init__(browser, search_prefs)

        self.nav_stack = [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ]

        use_direct = False
        if use_direct:
            self.nav_stack = [DirectURLNavigation(browser)]

        self.navigator = ResilientNavigator(browser, self.nav_stack)

    @property
    def name(self) -> str:
        """Canonical provider name."""
        return "indeed"

    @property
    def requires_live_browser(self) -> bool:
        """Indeed requires a live browser session."""
        return True

    def run(self, override_criteria: dict | None = None) -> list[Job]:
        """Executes the Indeed search workflow across all user preferences."""
        all_jobs: list[Job] = []

        for title in self.prefs.desired_job_titles:
            locations = self.prefs.preferred_locations or ["Remote"]

            for location in locations:
                url = self._construct_url(title, location)
                context = {"query": title, "location": location}

                if not self.navigator.navigate_with_fallback(
                    url, context, self._is_page_healthy
                ):
                    continue

                try:
                    scraper = GenericSERPStrategy(
                        self.browser,
                        self.prefs,
                        source_tag="Indeed",
                        title_parser=SmartTextExtractor(
                            strategies=[
                                "h2.jobTitle",
                                "span[id^='jobTitle']",
                                "a[data-jk]",
                            ]
                        ),
                        company_parser=SmartTextExtractor(
                            strategies=[
                                "span[data-testid='company-name']",
                                "div.company_location",
                            ]
                        ),
                    )

                    found = scraper.run()
                    for job in found:
                        job.source = "Indeed"

                    all_jobs.extend(found)

                except Exception as exc:
                    logger.error("Error during Indeed search: %s", exc)

        return all_jobs

    def _is_page_healthy(self) -> bool:
        if self.is_blocked():
            return False
        return True

    def _construct_url(self, title: str, location: str) -> str:
        params = {"q": title, "l": location}
        return f"https://www.indeed.com/jobs?{urlencode(params)}"