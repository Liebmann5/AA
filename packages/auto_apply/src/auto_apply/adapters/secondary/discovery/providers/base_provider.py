"""Defines the abstract contract for Job Search Providers.

This module provides the `BaseSearchProvider` abstract base class. All concrete
providers (Google, Bing, LinkedIn) must implement this interface. This ensures
the Discovery Engine can treat all sources uniformly, regardless of their
underlying complexity.
"""

import logging
from abc import abstractmethod

from auto_apply.adapters.secondary.browser.page_snapshot import browser_page_snapshot
from auto_apply.adapters.secondary.discovery.strategies.engine_strategies import (
    SearchEngineStrategy,
)
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    ResilientNavigator,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    BLOCK_PAGE_TYPES,
    record_blocked_observation,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.discovery_port import DiscoveryProviderPort
from auto_apply.domain.ports.page_understanding_port import PageContext
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.services.site_restriction import (
    RestrictionCheck,
    check_restriction,
    restriction_of,
)

logger = logging.getLogger(__name__)


class BaseSearchProvider(DiscoveryProviderPort):
    """The abstract contract for a specific job board provider (e.g., Google).

    A Provider acts as a 'Foreman'. It knows the specific URLs, navigation
    quirks, and CSS selectors for a specific website, but delegates the actual
    heavy lifting of scraping to reusable Strategies.

    Every engine provider sets ``navigator`` and ``_engine_strategy`` in its
    constructor; the shared navigation sequence (:meth:`_navigate`) uses them.
    """

    navigator: ResilientNavigator
    _engine_strategy: SearchEngineStrategy

    def __init__(
        self,
        browser: BrowserInterface,
        scroller=None,
        advancer_factory=None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier=None,
        host_pacer=None,
    ) -> None:
        """Initializes the provider with the browser and its page collaborators.

        The scroller and advancer factory are injected rather than
        constructed here: a discovery adapter should ask for the next page,
        not decide how one is fetched. The factory builds a FRESH, stateless
        advancer per query — a shared advancer would leak its page position
        across queries and providers, the exact bug the retired
        PaginationHandler had. ``max_pages`` is a ceiling, defaulting to 1 —
        today's single-page behaviour.

        Args:
            browser: The active browser instance.

        Note:
            The provider no longer receives ``ExecutionContext`` or
            ``UserProfile``.  It is a stateless executor that receives
            exactly one :class:`SearchInstruction` per :meth:`run` call.
        """
        self.browser = browser
        self._scroller = scroller
        self._advancer_factory = advancer_factory
        self._max_pages = max(1, int(max_pages))
        self._observer = observer
        self._reporter = reporter
        self._forced_tier = forced_tier
        self._host_pacer = host_pacer

    def _baseline_scope_for(self, instruction) -> str:
        """"#site" for planner-produced (platform-targeted) instructions, else ""."""
        return "#site" if getattr(instruction, "platform", None) else ""

    def _session_guard_blocks(self, instruction) -> bool:
        """True when this engine was benched this session — no request is sent.

        Checks the base name (a challenged host challenges every query shape)
        and the instruction's scope (a degraded site-restricted path stops
        only site-restricted queries). This check runs BEFORE navigation.
        """
        detector = getattr(self, "_degradation_detector", None)
        if detector is None:
            return False
        name = self.name
        if detector.is_benched(name) or detector.is_benched(
            name + self._baseline_scope_for(instruction)
        ):
            logger.warning(
                "%s: benched for this session — skipping without navigating | title=%r",
                name,
                getattr(instruction, "title", ""),
            )
            return True
        restriction = self._restriction_for(instruction)
        ignored = getattr(detector, "restriction_ignored", None)
        if restriction and callable(ignored) and ignored(name, restriction) is True:
            logger.warning(
                "%s: answered site:%s without the restriction earlier this "
                "session — not sent again | title=%r",
                name,
                restriction,
                getattr(instruction, "title", ""),
            )
            return True
        return False

    @staticmethod
    def _restriction_for(instruction) -> str:
        """The ``site:`` restriction *instruction* asks the engine to keep."""
        try:
            return restriction_of(instruction.effective_query)
        except Exception:
            return ""

    def _navigate(self, instruction) -> bool:
        """Load the search page for *instruction*: the ONE navigation sequence.

        Every engine runs the same sequence: the navigator's strategies in
        order, each landing judged by :meth:`_is_page_healthy`, and no
        further strategy once the engine is benched. Before this, each
        provider passed its own health check (Google's and Bing's always
        answered "healthy") and a blocked engine was retried through its
        home page (Indeed, owner run 2026-11-03).
        """
        self._blocked_observation_emitted = False
        restriction = self._restriction_for(instruction)
        self._restriction_checks: list[tuple[str, RestrictionCheck]] = []
        validator = self._is_page_healthy
        if restriction:
            def validator() -> bool:
                return self._is_page_healthy() and self._kept_restriction(restriction)
        arrived = self.navigator.navigate_with_fallback(
            self._engine_strategy,
            instruction,
            validator,
            should_stop=self._is_benched,
        )
        checks = self._restriction_checks
        if not arrived and checks and all(c.dropped for _, c in checks):
            detector = getattr(self, "_degradation_detector", None)
            mark = getattr(detector, "mark_restriction_ignored", None)
            if callable(mark):
                mark(
                    self.name,
                    restriction,
                    "; ".join(f"{route}: {c.describe()}" for route, c in checks),
                )
        return arrived

    def _kept_restriction(self, restriction: str) -> bool:
        """Did the engine keep *restriction* on the page it just loaded?

        False only when the page shows enough results to judge and none of
        them is on the restricted site (domain/services/site_restriction.py):
        that page answers a different search than the one AA asked for, and
        the navigator tries its next route. Any doubt - no page reader, a
        read that failed, too few results - keeps the page: an unproven drop
        must not throw away a page that may be real.
        """
        route = getattr(self.navigator, "current_strategy", "") or "route"
        reader = getattr(self, "_page_understanding", None)
        if reader is None:
            return True
        try:
            url = self.browser.current_url or ""
            structure = reader.analyze_serp(PageContext(url=url))
            hosts = tuple(getattr(structure, "result_hosts", ()) or ())
        except Exception as exc:
            logger.debug("%s: restriction check unavailable (%s)", self.name, exc)
            return True
        check = check_restriction(restriction, hosts)
        self._restriction_checks.append((route, check))
        if check.dropped:
            logger.warning(
                "%s: the engine dropped site:%s via %s — %s (first: %s); "
                "this page answers another search, so it is not read.",
                self.name.capitalize(),
                restriction,
                route,
                check.describe(),
                ", ".join(dict.fromkeys(hosts[:4])),
            )
            return False
        logger.info(
            "%s: site:%s %s via %s — %s",
            self.name.capitalize(),
            restriction,
            check.state,
            route,
            check.describe(),
        )
        return True

    def _is_benched(self) -> bool:
        """True once this engine is benched for the session."""
        detector = getattr(self, "_degradation_detector", None)
        if detector is None:
            return False
        try:
            return bool(detector.is_benched(self.name))
        except Exception:
            return False

    def _is_page_healthy(self) -> bool:
        """Is the page this engine just loaded usable? The ONE page verdict.

        A CAPTCHA interstitial, a login wall or a 404 is a *blocked* page,
        not an empty result set. A blocked page records one research
        observation per instruction (the navigator may ask twice) and
        benches the engine for the session; any other verdict is healthy
        here, and what the page IS (results, home page) is the reader's
        question, asked of the same verdict.
        """
        url, title, html = browser_page_snapshot(self.browser)
        assessment = assess_page(url=url, title=title, html=html)
        if assessment.kind not in BLOCK_PAGE_TYPES:
            return True
        tag = self.name.capitalize()
        logger.warning(
            "%s: page blocked | kind=%s signals=%s",
            tag,
            assessment.kind.name,
            ",".join(assessment.signals),
        )
        if not getattr(self, "_blocked_observation_emitted", False):
            self._blocked_observation_emitted = True
            record_blocked_observation(
                source_tag=tag,
                browser=self.browser,
                research_observer=getattr(self, "_research_observer", None),
                page_type=assessment.kind,
            )
        detector = getattr(self, "_degradation_detector", None)
        if detector is not None:
            try:
                detector.mark_blocked(self.name, assessment.kind.name)
            except Exception:
                pass
        return False

    def _pace_for(self, instruction) -> None:
        """Per-host pre-navigation pacing; a no-op when no pacer is wired."""
        pacer = self._host_pacer
        if pacer is None:
            return
        strategy = getattr(self, "_engine_strategy", None)
        if strategy is None:
            return
        try:
            url = strategy.build_search_url(instruction)
        except Exception:
            return
        pacer.wait_for_url(url)

    @property
    def name(self) -> str:
        """Returns the canonical lowercase name of the provider.

        Derived from the class name: ``GoogleProvider`` → ``'google'``.
        Subclasses that need a custom name should override this property.
        """
        return self.__class__.__name__.replace("Provider", "").lower()

    @property
    def requires_live_browser(self) -> bool:
        """All current providers require a live browser session."""
        return True

    @abstractmethod
    def run(self, instruction: SearchInstruction) -> list[Job]:
        """Executes the search and extraction workflow for this provider.

        Args:
            instruction: A single, typed search instruction.  The provider
                must NOT build its own query matrix or read the user profile.

        Returns:
            List of unique Job objects discovered. May be empty; never None.
        """
        ...

    def safe_navigate(self, url: str) -> bool:
        """Navigates to a URL, returning False instead of raising on failure.

        This method performs no rate limiting and no page-safety validation.
        Per-host pacing lives in ``_pace_for`` (wired from the composition
        root); page-safety verdicts live in the one page verdict used by the
        SERP block gate and the provider health checks.
        """
        # ── 1. Navigate ───────────────────────────────────────────────────
        try:
            self.browser.get(url)
        except Exception:
            return False

        return True