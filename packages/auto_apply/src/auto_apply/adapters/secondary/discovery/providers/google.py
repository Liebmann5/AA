"""Provides the specific search provider for Google Jobs.

This module implements the Google-specific logic. It acts as the 'Foreman',
configuring the generic SERP strategy with the specific CSS selectors and
URL parameters required to scrape Google's 'Jobs Widget' interface.
"""

import logging
import urllib.parse
from urllib.parse import urlencode

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.adapters.secondary.perception.dom_adapter import (
    JSONLDParser,
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
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class GoogleProvider(BaseSearchProvider):
    """A provider that finds jobs via Google's 'ibp=htl;jobs' widget."""

    def __init__(
        self,
        browser: BrowserInterface,
        context: ExecutionContext,
        ats_registry=None,
        page_understanding_port=None,          # NEW: injectable geometric analysis
        math_analyzer=None,                     # DEPRECATED: use page_understanding_port
    ) -> None:
        super().__init__(browser, context)
        # Optional ATSRegistry: when provided, find_company_career_page() builds
        # the site-filter list from loaded descriptors rather than a hardcoded set.
        self._ats_registry = ats_registry
        self.navigator = ResilientNavigator(browser, [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ])
        # Store page understanding port (preferred) and deprecated math_analyzer
        self._page_understanding = page_understanding_port
        self._math_analyzer = math_analyzer
        if math_analyzer is not None:
            logger.warning(
                "GoogleProvider: math_analyzer is deprecated; use page_understanding_port instead."
            )

    def _is_page_healthy(self) -> bool:
        if self.evasion is not None and not self.evasion.check_page_safety():
            return False
        return True

    def run(self, override_criteria: dict | None = None) -> list[Job]:
        """Executes the Google search workflow for all user preferences.

        It iterates through the user's desired titles and locations, constructs
        the specific Google URLs, and deploys the GenericSERPStrategy to scrape
        them.
        """
        all_jobs: list[Job] = []

        for title in self.prefs.desired_job_titles:
            locations = self.prefs.preferred_locations or ["Remote"]

            for location in locations:
                url = self._construct_url(title, location)
                context_data = {"query": title, "location": location}
                logger.info(
                    "GoogleProvider: Processing query '%s' in '%s'",
                    title,
                    location,
                )

                if not self.navigator.navigate_with_fallback(
                    url, context_data, self._is_page_healthy
                ):
                    logger.warning("Skipping URL due to safety/throttling checks.")
                    continue

                behavior.simulate_idle_time(
                    self.browser, min_seconds=2.0, max_seconds=4.0
                )

                json_parser = JSONLDParser(self.browser)
                raw_data = json_parser.parse_page()
                if raw_data:
                    json_jobs = self._convert_json_to_jobs(raw_data)
                    if json_jobs:
                        all_jobs.extend(json_jobs)
                        logger.info(
                            "  Found %d jobs via JSON-LD. Skipping HTML scrape.",
                            len(json_jobs),
                        )
                        continue

                scraper = GenericSERPStrategy(
                    browser=self.browser,
                    search_prefs=self.prefs,
                    source_tag="Google",
                    title_parser=SmartTextExtractor(
                        strategies=[
                            "div[role='heading']",
                            ".v0nnCb",
                            "h3",
                            ".BjJfJf",
                        ]
                    ),
                    company_parser=SmartTextExtractor(
                        strategies=[
                            "div.vNnecGC",
                            "span.VuuXrf",
                            "div.nJlQNd",
                        ]
                    ),
                    url_parser=SmartURLExtractor(),
                )

                html_jobs = scraper.execute()
                all_jobs.extend(html_jobs)

        return self._deduplicate(all_jobs)

    def _construct_url(self, title: str, location: str) -> str:
        """Builds the Google Jobs URL with strict locale enforcement."""
        query = f"{title} jobs in {location}"
        params = {
            "q": query,
            "ibp": "htl;jobs",
            "hl": "en",
            "gl": "us",
            "start": 0,
        }
        return f"https://www.google.com/search?{urlencode(params)}"

    def _convert_json_to_jobs(self, raw_data: list[dict]) -> list[Job]:
        """Normalizes raw JSON-LD dictionaries into Job objects."""
        jobs = []
        for item in raw_data:
            try:
                title = item.get("title")
                org = item.get("hiringOrganization", {})
                company = org.get("name") if isinstance(org, dict) else "Unknown"
                url = item.get("url")

                if not url:
                    url = f"https://www.google.com/search?q={title}+{company}+jobs"

                if title:
                    jobs.append(
                        Job(
                            title=title,
                            company=company,
                            url=url,
                            source="Google (JSON-LD)",
                            location=(
                                item.get("jobLocation", {})
                                .get("address", {})
                                .get("addressLocality")
                            ),
                        )
                    )
            except Exception:
                continue
        return jobs

    def _deduplicate(self, jobs: list[Job]) -> list[Job]:
        """Removes duplicate jobs based on URL."""
        unique_map = {job.url: job for job in jobs}
        return list(unique_map.values())

    def find_company_career_page(self, company_name: str) -> str | None:
        """Performs a targeted search to find a company's official career page.

        This is the core of the 'Recursive Discovery' feature. When an
        ATSRegistry was provided at construction, the site-filter list is built
        dynamically from loaded YAML descriptors so newly-added ATS platforms
        are automatically included without code changes.

        Args:
            company_name: The name of the target company (e.g., "Meta").

        Returns:
            The URL of the career page, or None if not found.
        """
        site_filters = _ats_site_filters(self._ats_registry)
        site_query = " OR ".join(f"site:{d}" for d in site_filters)
        query = f"{company_name} careers ({site_query} OR site:{company_name}.com)"
        encoded_query = urllib.parse.quote_plus(query)
        search_url = (
            f"https://www.google.com/search?q={encoded_query}&hl=en&gl=us"
        )

        logger.info("GoogleProvider: Hunting for ATS link: %s", search_url)

        try:
            self.browser.get(search_url)

            first_result = self.browser.find_element(
                Locator.CSS_SELECTOR, "div.g a"
            )

            if first_result:
                url = first_result.get_attribute("href")
                if url and "google.com" not in url:
                    logger.info(
                        "GoogleProvider: Discovered career page -> %s", url
                    )
                    return url

            logger.warning(
                "GoogleProvider: No clear ATS link found for %s", company_name
            )
            return None

        except Exception as exc:
            logger.error(
                "GoogleProvider: Recursive search failed: %s", exc
            )
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ats_site_filters(registry) -> list[str]:
    """Returns root domains for all loaded ATS descriptors.

    Extracts the last two dot-separated parts of each descriptor's first URL
    pattern hostname (e.g. ``*.greenhouse.io/jobs/*`` → ``greenhouse.io``).
    Falls back to a hardcoded list when no registry is provided or when
    domain extraction yields no results.
    """
    _FALLBACK = ["greenhouse.io", "lever.co", "workday.com", "ashbyhq.com"]

    if registry is None:
        return _FALLBACK

    domains: list[str] = []
    seen: set[str] = set()
    for descriptor in registry.all_descriptors():
        for pattern in descriptor.url_patterns:
            host = pattern.split("/")[0].lstrip("*").lstrip(".")
            parts = host.split(".")
            if len(parts) >= 2:
                root = ".".join(parts[-2:])
                if root not in seen:
                    seen.add(root)
                    domains.append(root)
                    break  # one root domain per descriptor is enough

    return domains or _FALLBACK