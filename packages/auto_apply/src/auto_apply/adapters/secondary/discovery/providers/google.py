"""Provides the specific search provider for Google Jobs.

This module implements the Google‑specific logic. It acts as the 'Foreman',
configuring the generic SERP strategy with the specific CSS selectors and
URL parameters required to scrape Google's 'Jobs Widget' interface.

The provider no longer builds its own search URL — that knowledge lives in
:class:`~auto_apply.adapters.secondary.discovery.strategies.engine_strategies.GoogleSearchStrategy`.

JSON‑LD extraction is now handled universally by
:class:`GenericSERPStrategy`, so the provider does not duplicate it.
"""

import logging
import urllib.parse

from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    GoogleSearchStrategy,
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
from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    PageUnderstandingExtractor,
)
from auto_apply.domain.ports.page_understanding_port import (
    NullPageUnderstandingAdapter,
)
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class GoogleProvider(BaseSearchProvider):
    """A provider that finds jobs via Google's 'ibp=htl;jobs' widget."""

    def __init__(
        self,
        browser: BrowserInterface,
        ats_registry=None,
        page_understanding_port=None,
        scroller=None,
        paginator=None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier=None,
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
        # Optional ATSRegistry: when provided, find_company_career_page() builds
        # the site‑filter list from loaded descriptors rather than a hardcoded set.
        self._ats_registry = ats_registry
        self._page_understanding = page_understanding_port

        # ── Engine‑specific strategy (URL construction, toolbar interactions) ──
        self._engine_strategy = GoogleSearchStrategy()

        self.navigator = ResilientNavigator(browser, [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ])

    def _fast_extractor(self):
        """The single-script extraction route, or None if unavailable.

        ``page_understanding_port`` has been injected here since the math
        subsystem was built and read by nothing. This is where it is read.
        Returning None leaves the strategy on the DOM miner alone, which is the
        behaviour every previous run had.
        """
        if self._page_understanding is None:
            return None
        if isinstance(self._page_understanding, NullPageUnderstandingAdapter):
            # The Null adapter answers every analyze_serp with an empty
            # SERPStructure. Wrapping it would produce a harvest logged as
            # "fallback:empty" — indistinguishable from a real page where the
            # detector found nothing, which is the one question the next live
            # run exists to answer. Report no fast route instead.
            logger.info(
                "GoogleProvider: page understanding is the Null adapter — no "
                "fast SERP route; using the DOM miner."
            )
            return None
        return PageUnderstandingExtractor(
            page_understanding=self._page_understanding,
            browser=self.browser,
            observer=self._observer,
        )

    def _is_page_healthy(self) -> bool:
        # If an evasion manager is wired, use it; otherwise assume healthy.
        return True

    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Executes a single Google search for the given instruction.

        Args:
            instruction: A typed search instruction — must NOT be None.

        Returns:
            List of Job objects discovered for this single instruction.
        """
        logger.info(
            "GoogleProvider: Processing instruction | title=%r location=%r "
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
                "GoogleProvider: navigation/health check failed — returning empty"
            )
            return []

        # ── Apply toolbar filters (date, etc.) after navigation ─────────────
        self._engine_strategy.apply_toolbar_filters(self.browser, instruction)

        behavior.simulate_idle_time(
            self.browser, min_seconds=2.0, max_seconds=4.0
        )

        scraper = GenericSERPStrategy(
            browser=self.browser,
            search_prefs=None,
            source_tag="Google",
            max_results=instruction.max_results,
            fast_extractor=self._fast_extractor(),
            scroller=self._scroller,
            paginator=self._paginator,
            max_pages=self._max_pages,
            observer=self._observer,
            reporter=self._reporter,
            forced_tier=self._forced_tier,
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

        # The scraper handles the full extraction (JSON‑LD, scrolling, mining)
        return scraper.execute()


    # ------------------------------------------------------------------
    # Company career‑page discovery (kept for DISCOVER_COMPANY tasks)
    # ------------------------------------------------------------------

    def find_company_career_page(self, company_name: str) -> str | None:
        """Performs a targeted search to find a company's official career page.

        This is the core of the 'Recursive Discovery' feature.  When an
        ATSRegistry was provided at construction, the site‑filter list is
        built dynamically from loaded YAML descriptors so newly‑added ATS
        platforms are automatically included without code changes.

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

    Extracts the last two dot‑separated parts of each descriptor's first URL
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