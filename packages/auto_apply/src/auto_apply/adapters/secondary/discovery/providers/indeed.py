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
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.adapters.secondary.evasion.manager import EvasionManager
from auto_apply.adapters.secondary.perception.dom_adapter import SmartTextExtractor
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort

logger = logging.getLogger(__name__)


class IndeedProvider(BaseSearchProvider):
    """A provider that navigates to Indeed to discover job listings.

    Inherits from BaseSearchProvider for a uniform provider hierarchy.
    Supports an optional evasion manager to check page safety.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        evasion_manager: EvasionManager | None = None,
    ) -> None:
        super().__init__(browser)

        # ── Engine‑specific strategy (URL construction, toolbar interactions) ──
        self._engine_strategy = IndeedSearchStrategy()

        self.nav_stack = [
            DirectURLNavigation(browser),
            HumanSearchNavigation(browser),
        ]

        self.navigator = ResilientNavigator(browser, self.nav_stack)

        # ── Evasion (optional) ───────────────────────────────────────────────
        # No auto-construct fallback: if the caller doesn't explicitly supply
        # an EvasionManager, this provider genuinely performs no evasion
        # checking (matches the `| None = None` default honestly). Wiring a
        # real EvasionManager for production use belongs in the composition
        # root, which is where cross-cutting concerns like this should be
        # assembled explicitly rather than adapters silently self-configuring.
        self._evasion_manager = evasion_manager

    @property
    def name(self) -> str:
        """Canonical provider name."""
        return "indeed"

    @property
    def requires_live_browser(self) -> bool:
        """Indeed requires a live browser session."""
        return True

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

        if not self.navigator.navigate_with_fallback(
            self._engine_strategy, instruction, self._is_page_healthy
        ):
            logger.warning(
                "IndeedProvider: navigation/health check failed — returning empty"
            )
            return []

        # ── Apply toolbar filters (date, etc.) after navigation ─────────────
        self._engine_strategy.apply_toolbar_filters(self.browser, instruction)

        try:
            scraper = GenericSERPStrategy(
                self.browser,
                None,
                source_tag="Indeed",
                max_results=instruction.max_results,
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
        """Check page safety using the evasion manager, if available.

        Returns False if a known block/CAPTCHA is detected.
        """
        if self._evasion_manager:
            # check_page_safety returns True if safe, False if blocked
            if not self._evasion_manager.check_page_safety():
                return False
        return True