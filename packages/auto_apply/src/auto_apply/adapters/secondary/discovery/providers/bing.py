"""Provides the specific search provider for Bing Jobs.

This module implements the Bing‑specific logic. It acts as the 'Foreman',
configuring the generic SERP strategy with the specific CSS selectors and
URL parameters required to scrape Bing's job search interface.

The provider no longer builds its own search URL — that knowledge lives in
:class:`~auto_apply.adapters.secondary.discovery.strategies.engine_strategies.BingSearchStrategy`.
"""

import logging
from urllib.parse import urlencode

from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    BingSearchStrategy,
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
from auto_apply.adapters.secondary.perception.dom_adapter import (
    SmartTextExtractor,
    SmartURLExtractor,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)


class BingProvider(BaseSearchProvider):
    """A provider that finds jobs via Bing's job search aggregation."""

    def __init__(
        self,
        browser: BrowserInterface,
        scroller=None,
        paginator=None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier=None,
        degradation_detector=None,
    ) -> None:
        super().__init__(
            browser,
            scroller,
            paginator,
            max_pages,
            observer,
            reporter,
            forced_tier,
        )
        self._degradation_detector = degradation_detector

        # ── Engine‑specific strategy (URL construction, toolbar interactions) ──
        self._engine_strategy = BingSearchStrategy()

        self.navigator = ResilientNavigator(browser, [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ])

    def _is_page_healthy(self) -> bool:
        return True

    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Executes a single Bing search for the given instruction.

        Args:
            instruction: A typed search instruction — must NOT be None.

        Returns:
            List of Job objects discovered for this single instruction.
        """
        logger.info(
            "BingProvider: Processing instruction | title=%r location=%r "
            "raw_query=%s date_range=%s",
            instruction.title,
            instruction.location,
            bool(instruction.raw_query_string),
            instruction.date_range or "none",
        )

        if not self.navigator.navigate_with_fallback(
            self._engine_strategy, instruction, self._is_page_healthy
        ):
            logger.warning(
                "BingProvider: navigation/health check failed — returning empty"
            )
            return []

        # ── Apply toolbar filters (date, etc.) after navigation ─────────────
        self._engine_strategy.apply_toolbar_filters(self.browser, instruction)

        behavior.simulate_idle_time(
            self.browser, min_seconds=2.0, max_seconds=3.0
        )

        scraper = GenericSERPStrategy(
            browser=self.browser,
            search_prefs=None,
            source_tag="Bing",
            max_results=instruction.max_results,
            scroller=self._scroller,
            paginator=self._paginator,
            max_pages=self._max_pages,
            observer=self._observer,
            reporter=self._reporter,
            degradation_detector=self._degradation_detector,
            forced_tier=self._forced_tier,
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

        # The scraper handles deduplication and JSON‑LD extraction.
        return scraper.execute()