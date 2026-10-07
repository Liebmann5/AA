"""Provides the specific search strategy for Indeed Jobs.

The provider no longer builds its own search URL — that knowledge lives in
:class:`~auto_apply.adapters.secondary.discovery.strategies.engine_strategies.IndeedSearchStrategy`.
"""

import logging

from auto_apply.adapters.secondary.discovery.providers.base_provider import (
    BaseSearchProvider,
)
from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    IndeedSearchStrategy,
)
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    DirectURLNavigation,
    HumanSearchNavigation,
    ResilientNavigator,
)
from auto_apply.adapters.secondary.browser.page_snapshot import browser_page_snapshot
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    BLOCK_PAGE_TYPES,
    GenericSERPStrategy,
    record_blocked_observation,
)
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.adapters.secondary.perception.dom_adapter import SmartTextExtractor
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort
from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    PageUnderstandingExtractor,
)
from auto_apply.domain.ports.page_understanding_port import (
    NullPageUnderstandingAdapter,
)

logger = logging.getLogger(__name__)


class IndeedProvider(BaseSearchProvider):
    """A provider that navigates to Indeed to discover job listings.

    Inherits from BaseSearchProvider for a uniform provider hierarchy.
    Page safety is the ONE page verdict (domain/services/page_assessment.py),
    asked in ``_is_page_healthy`` during navigation; a blocked page is
    recorded as a blocked observation, not an empty harvest.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        scroller=None,
        advancer_factory=None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier=None,
        degradation_detector=None,
        page_understanding_port=None,
        research_observer=None,
        readiness=None,
        page_action=None,
    ) -> None:
        super().__init__(
            browser,
            scroller,
            advancer_factory,
            max_pages,
            observer,
            reporter,
            forced_tier,
        )
        self._degradation_detector = degradation_detector
        self._page_understanding = page_understanding_port
        self._research_observer = research_observer
        self._readiness = readiness
        # The interaction tool: toolbar clicks, human search navigation and
        # card-activation clicks go through it (C3). The composition root
        # always injects it; a bare construction degrades honestly.
        self._page_action = page_action

        # ── Engine‑specific strategy (URL construction, toolbar interactions) ──
        self._engine_strategy = IndeedSearchStrategy(page_action=self._page_action)

        self.nav_stack = [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser, page_action=self._page_action),
        ]

        self.navigator = ResilientNavigator(browser, self.nav_stack)

        # The block verdict comes from the ONE page verdict
        # (_is_page_healthy below). One blocked page is one observation per
        # run: the navigator may health-check more than once.
        self._blocked_observation_emitted: bool = False

    @property
    def name(self) -> str:
        """Canonical provider name."""
        return "indeed"

    @property
    def requires_live_browser(self) -> bool:
        """Indeed requires a live browser session."""
        return True

    def _fast_extractor(self):
        """The single-script extraction route, or None if unavailable.

        Mirrors ``GoogleProvider._fast_extractor`` exactly: when no real
        page-understanding adapter is wired there is no fast route, and the
        provider falls back to the DOM miner. The Null-adapter check is
        deliberate — it keeps a ``fallback:empty`` log line meaning "the
        detector ran and found nothing", never "no detector was wired".
        """
        if self._page_understanding is None:
            return None
        if isinstance(self._page_understanding, NullPageUnderstandingAdapter):
            logger.info(
                "IndeedProvider: page understanding is the Null adapter — no "
                "fast SERP route; using the DOM miner."
            )
            return None
        return PageUnderstandingExtractor(
            page_understanding=self._page_understanding,
            browser=self.browser,
            observer=self._observer,
            readiness=self._readiness,
            research_observer=self._research_observer,
            page_action=self._page_action,
        )

    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Executes a single Indeed search for the given instruction.

        Args:
            instruction: A typed search instruction — must NOT be None.

        Returns:
            List of Job objects discovered for this single instruction.
        """
        logger.info(
            "IndeedProvider: Processing instruction | title=%r location=%r "
            "raw_query=%s date_range=%s",
            instruction.title,
            instruction.location,
            bool(instruction.raw_query_string),
            instruction.date_range or "none",
        )

        self._blocked_observation_emitted = False
        if not self.navigator.navigate_with_fallback(
            self._engine_strategy, instruction, self._is_page_healthy
        ):
            logger.warning(
                "IndeedProvider: navigation/health check failed — returning empty"
            )
            return []

        # ── Apply toolbar filters (date, etc.) after navigation ─────────────
        self._engine_strategy.apply_toolbar_filters(self.browser, instruction)

        # Fresh, stateless advancer per query — a shared one would leak its
        # page position into the next search.
        advancer = (
            self._advancer_factory() if callable(self._advancer_factory) else None
        )

        try:
            scraper = GenericSERPStrategy(
                self.browser,
                None,
                source_tag="Indeed",
                max_results=instruction.max_results,
                fast_extractor=self._fast_extractor(),
                scroller=self._scroller,
                advancer=advancer,
                max_pages=self._max_pages,
                observer=self._observer,
                reporter=self._reporter,
                forced_tier=self._forced_tier,
                degradation_detector=self._degradation_detector,
                research_observer=self._research_observer,
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

            return found

        except Exception as exc:
            logger.error("Error during Indeed search: %s", exc)
            return []

    def _is_page_healthy(self) -> bool:
        """Check page safety with the ONE page verdict.

        A CAPTCHA interstitial, a login wall, or a 404 is a *blocked* page,
        not an empty result set. When blocked, record the observation the
        SERP gate records — once per run, since the navigator may
        health-check more than once — and report unhealthy.
        """
        url, title, html = browser_page_snapshot(self.browser)
        assessment = assess_page(url=url, title=title, html=html)
        if assessment.kind not in BLOCK_PAGE_TYPES:
            return True
        logger.warning(
            "IndeedProvider: page blocked | kind=%s signals=%s",
            assessment.kind.name,
            ",".join(assessment.signals),
        )
        if not self._blocked_observation_emitted:
            self._blocked_observation_emitted = True
            record_blocked_observation(
                source_tag="Indeed",
                browser=self.browser,
                research_observer=self._research_observer,
                page_type=assessment.kind,
            )
        return False
