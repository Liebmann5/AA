"""Provides a generic, reusable strategy for scraping Search Engine Results Pages (SERPs).

This module contains the `GenericSERPStrategy`. It implements a high-level
algorithm: "Find the list container, iterate through items, parse details."
It relies on dependency injection for the specific finding and parsing logic,
making it adaptable to almost any list-based website (Google, Bing, Indeed).
"""

import json
import logging
import time
import urllib.parse
from typing import Optional

# Components
from auto_apply.domain.models.analysis_tier import PageAnalysisTier
from auto_apply.domain.ports.extraction_observer_port import (
    NullAuditReporter,
    NullExtractionObserver,
)
from auto_apply.domain.ports.research_port import (
    DiscoveryObservation,
    NullResearchObserver,
    ResearchObserverPort,
)
from auto_apply.adapters.secondary.discovery.components.miner import SemanticMiner
from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    FallbackSerpExtractor,
)
from auto_apply.adapters.secondary.browser.page_snapshot import browser_page_snapshot
from auto_apply.adapters.secondary.navigation.interruption import InterruptionHandler
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import JobSearchPreferences
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.page_advance_port import PageAdvancePort
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

from auto_apply.adapters.secondary.perception.dom_adapter import (
    BaseExtractor,
    SmartTextExtractor,
    SmartURLExtractor,
)

logger = logging.getLogger(__name__)

# Page types that mean "we were blocked", not "there are no jobs". A blocked
# page must never become a zero-yield measurement or a degradation-guard
# baseline. Public because two gates classify by it: this strategy's, and
# IndeedProvider's navigation health check.
BLOCK_PAGE_TYPES = frozenset({
    PageType.CAPTCHA_BLOCK,
    PageType.LOGIN_REQUIRED,
    PageType.ERROR_404,
})


def record_blocked_observation(
    *,
    source_tag: str,
    browser: BrowserInterface,
    research_observer: ResearchObserverPort | None,
    page_type: PageType,
) -> None:
    """Emit a blocked-page discovery observation (consent-gated).

    The observation carries the block verdict — it is an access-equity
    datum for the research record, not an empty harvest. Shared by
    GenericSERPStrategy (blocked mid-strategy) and IndeedProvider (blocked
    during navigation) so one blocked page produces one observation shape,
    whoever met it.
    """
    if research_observer is None or not research_observer.is_enabled:
        return
    try:
        host = ""
        try:
            host = urllib.parse.urlsplit(
                getattr(browser, "current_url", "") or ""
            ).netloc.lower()
        except Exception:
            pass
        research_observer.observe_discovery(
            DiscoveryObservation(
                provider=source_tag,
                page_host=host,
                page_state=page_type.name.lower(),
                blocked=True,
                architecture="none",
                card_count=0,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "%s: blocked-page observation failed (non-fatal): %s",
            source_tag,
            exc,
        )


def _stamp_job_page(job, page_index: int, rank: int) -> None:
    """Record which results page and position a listing came from.

    Jobs carry this in their metadata scratch-pad (reserved keys, documented
    on the model). Listings from test doubles or older extractors that have
    no metadata dict are left untouched — evidence must never break a harvest.
    """
    metadata = getattr(job, "metadata", None)
    if isinstance(metadata, dict):
        metadata["page_index"] = page_index
        metadata["rank"] = rank


class GenericSERPStrategy:
    """A reusable blueprint for scraping any page containing a list of search results.

    This class does not know *which* site it is scraping. It simply executes
    the provided extractors on whatever page the browser is currently on.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        search_prefs: JobSearchPreferences | None,
        source_tag: str,
        title_parser: BaseExtractor | None = None,
        company_parser: BaseExtractor | None = None,
        url_parser: BaseExtractor | None = None,
        max_results: int = 30,
        dry_scroll_limit: int = 3,
        inter_scroll_delay_s: float = 2.0,
        scroller=None,
        advancer: PageAdvancePort | None = None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier: PageAnalysisTier | None = None,
        fast_extractor=None,
        degradation_detector=None,
        research_observer=None,
        page_action=None,
    ):
        """Initializes the strategy with specific parsing tools.

        Args:
            fast_extractor: Optional SerpExtractionPort tried before the DOM
                miner. When None (the default) the miner is used directly and
                nothing about discovery changes.
            research_observer: Optional ResearchObserverPort. Receives a
                blocked-page observation when a block page is detected; the
                null observer (default) makes that cost exactly nothing.
        """
        self.browser = browser
        self.prefs = search_prefs
        self.source_tag = source_tag
        # Resolved per-query result cap (from SearchInstruction.max_results,
        # which the workflow fills from the low-resource-clamped session plan).
        self.max_results = max_results
        # Scroll bounds — parametric, not magic numbers. dry_scroll_limit stops
        # the harvest after N consecutive scrolls that reveal no new jobs;
        # inter_scroll_delay_s paces between scrolls (0.0 in tests for speed).
        self._dry_scroll_limit = max(1, int(dry_scroll_limit))
        self._inter_scroll_delay_s = max(0.0, float(inter_scroll_delay_s))
        # Scrolling and page advance arrive as collaborators. This adapter no
        # longer imports them across the layer boundary, and no longer
        # decides how a page advances — it asks, and trusts only a VERIFIED
        # advance (see _mine_all_pages).
        self._scroller = scroller
        self._advancer = advancer
        # Ceiling, not a quota. Default 1 = today's single-page behaviour.
        self._max_pages = max(1, int(max_pages))

        self.interruption_handler = InterruptionHandler(
            browser, page_action=page_action
        )
        # Auditing is observation. Nulls by default, so an unwired audit
        # trail can never change or break what discovery extracts.
        self._observer = observer or NullExtractionObserver()
        self.auditor = reporter or NullAuditReporter()
        # None (the default) leaves the JSON-LD-then-mine order untouched.
        self._forced_tier = forced_tier
        # None (unwired) leaves discovery byte-identical to before S8k.
        self._degradation_detector = degradation_detector
        self._research_observer = research_observer or NullResearchObserver()
        self._page_action = page_action

        self.title_parser = title_parser or SmartTextExtractor()
        self.company_parser = company_parser or SmartTextExtractor(strategies=["div.company", "span.company", "a.company"])
        self.url_parser = url_parser or SmartURLExtractor()

        semantic_miner = SemanticMiner(
            browser=browser,
            title_parser=self.title_parser,
            url_parser=self.url_parser,
            company_parser=self.company_parser,
            observer=self._observer,
        )

        # The miner is never replaced — only wrapped, and only when a provider
        # supplies a fast route. Unwired (fast_extractor=None) self.miner IS
        # the SemanticMiner instance, so discovery behaves exactly as before.
        self.miner = (
            FallbackSerpExtractor(fast_extractor, semantic_miner)
            if fast_extractor is not None
            else semantic_miner
        )

    # ------------------------------------------------------------------
    # Block detection (D5) — one gate, both entry paths
    # ------------------------------------------------------------------

    def _page_block_type(self) -> PageType | None:
        """Return the blocking PageType for the current page, or None.

        A CAPTCHA interstitial, a login wall, or a 404 is a *blocked* page,
        not an empty result set. This helper exists so both ``execute()``
        and ``run()`` apply the identical check instead of one path having
        it and the other not.
        """
        url, title, html = browser_page_snapshot(self.browser)
        assessment = assess_page(url=url, title=title, html=html)
        if assessment.kind in BLOCK_PAGE_TYPES:
            logger.info(
                "%s: page verdict %s | signals=%s",
                self.source_tag,
                assessment.kind.name,
                ",".join(assessment.signals),
            )
            return assessment.kind
        return None

    def _abort_blocked(self, page_type: PageType, context: str) -> list[Job]:
        """Log and record a blocked page, then return no jobs.

        The observation carries the block verdict — it is an access-equity
        datum for the research record, not an empty harvest.
        """
        logger.warning(
            "%s: Page failed health check (%s). Aborting strategy.",
            self.source_tag,
            page_type.name,
        )
        self._emit_blocked_observation(page_type)
        return []

    def _emit_blocked_observation(self, page_type: PageType) -> None:
        """Emit a blocked-page discovery observation (consent-gated)."""
        record_blocked_observation(
            source_tag=self.source_tag,
            browser=self.browser,
            research_observer=self._research_observer,
            page_type=page_type,
        )

    def _mine_all_pages(self, scroller) -> dict:
        """Mines the current page, then advances while pages remain.

        With ``max_pages == 1`` (the shipped default) this runs the harvest
        exactly once and never touches the advancer, so discovery output is
        byte-for-byte what it was before pagination existed.

        Every advance is VERIFIED — the advancer only reports success when
        the page provably changed, so the old page is never re-mined wearing
        a new number. And every new page is treated as a new page: the block
        verdict and overlay dismissal re-run before it is mined, and pacing
        between pages comes from the interaction tool's macro pause, never
        a bare sleep.

        Args:
            scroller: The injected scroll collaborator.

        Returns:
            The merged dict of unique jobs across every page visited.
        """
        unique = self._scroll_and_mine(scroller, page_index=0, advance_method="")

        pages_visited = 1
        methods_used: list[str] = []
        stop_reason = "page-cap"
        for page in range(1, self._max_pages):
            if len(unique) >= self.max_results:
                stop_reason = "result-cap"
                break
            if self._advancer is None:
                stop_reason = "no-advancer"
                break
            try:
                outcome = self._advancer.advance()
            except Exception as exc:
                logger.debug("%s: page advance failed: %s", self.source_tag, exc)
                stop_reason = "advance-error"
                break
            if not outcome.advanced:
                logger.info(
                    "%s: no further pages after page %d (%s)",
                    self.source_tag,
                    page,
                    outcome.stop_reason or "no next page",
                )
                stop_reason = outcome.stop_reason or "no-next"
                break
            pages_visited += 1
            methods_used.append(outcome.method)
            logger.info(
                "%s: advanced to page %d via %s (verified)",
                self.source_tag,
                page + 1,
                outcome.method,
            )
            # A new page is a new page: the block verdict re-runs FIRST — a
            # CAPTCHA on page 2 is a block, never an empty harvest — then
            # overlays are dismissed and pacing is applied before mining.
            block_type = self._page_block_type()
            if block_type is not None:
                logger.warning(
                    "%s: page %d failed health check (%s). Stopping pagination.",
                    self.source_tag,
                    page + 1,
                    block_type.name,
                )
                self._emit_blocked_observation(block_type)
                stop_reason = f"blocked:{block_type.name.lower()}"
                break
            self._dismiss_overlays()
            self._pause_between_pages()
            unique.update(
                self._scroll_and_mine(
                    scroller, page_index=page, advance_method=outcome.method
                )
            )

        self._record_pagination_summary(
            pages_visited, methods_used, stop_reason, len(unique)
        )
        return unique

    def _dismiss_overlays(self) -> None:
        """Dismiss cookie banners / popups on the current page. Never raises."""
        try:
            self.interruption_handler.handle_interruptions()
        except Exception:
            pass

    def _pause_between_pages(self) -> None:
        """Pacing between page fetches: the tool's macro pause, which is a
        measured human reading pause — never a bare sleep. Rate limits are
        real (Google's /sorry/ at ~3 searches/minute); pages are paced."""
        tool = self._page_action
        if tool is None:
            return
        try:
            tool.macro_pause()
        except Exception:
            pass

    def _record_pagination_summary(
        self,
        pages_visited: int,
        methods_used: list[str],
        stop_reason: str,
        job_count: int,
    ) -> None:
        """Emit one query-level pagination summary observation (consent-gated).

        Only when pagination was actually in play (an advancer wired AND the
        ceiling above one page), so the shipped single-page default records
        exactly what it recorded before. The summary row carries
        ``page_index=-1`` to distinguish it from per-page rows: it is a
        query record, not a results page.
        """
        if self._advancer is None or self._max_pages <= 1:
            return
        observer = self._research_observer
        if observer is None or not getattr(observer, "is_enabled", False):
            return
        try:
            host = ""
            try:
                host = urllib.parse.urlsplit(
                    getattr(self.browser, "current_url", "") or ""
                ).netloc.lower()
            except Exception:
                pass
            observer.observe_discovery(
                DiscoveryObservation(
                    provider=self.source_tag,
                    page_host=host,
                    page_state="normal",
                    blocked=False,
                    architecture="",
                    card_count=job_count,
                    page_index=-1,
                    advance_method=";".join(methods_used) or "none",
                    stop_reason=stop_reason,
                    page_count=pages_visited,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "%s: pagination summary failed (non-fatal): %s",
                self.source_tag,
                exc,
            )

    def _paginate_json_ld(self, jobs: list[Job]) -> list[Job]:
        """Advance a JSON-LD page through the same verified ladder.

        Ruled: a JSON-LD page MAY advance — structured data describes the
        current page, not the site's size. Only attempted when the ceiling
        allows more pages and an advancer is wired, so the shipped default
        (one page) is byte-identical to before. Each new page re-runs the
        block verdict and overlay dismissal before extraction.
        """
        seen = {j.url for j in jobs}
        for _page in range(1, self._max_pages):
            if len(jobs) >= self.max_results or self._advancer is None:
                break
            try:
                outcome = self._advancer.advance()
            except Exception as exc:
                logger.debug(
                    "%s: JSON-LD page advance failed: %s", self.source_tag, exc
                )
                break
            if not outcome.advanced:
                break
            block_type = self._page_block_type()
            if block_type is not None:
                self._emit_blocked_observation(block_type)
                break
            self._dismiss_overlays()
            self._pause_between_pages()
            for job in self._try_extract_json_ld():
                if len(jobs) >= self.max_results:
                    break
                if job.url and job.url not in seen:
                    seen.add(job.url)
                    jobs.append(job)
        return jobs

    def _extractor_label(self) -> str:
        """Name the route that produced the last harvest, for the log line."""
        return getattr(self.miner, "route_label", type(self.miner).__name__)

    def _is_provider_benched(self) -> bool:
        """True if the silent-degradation guard benched this provider."""
        if self._degradation_detector is None:
            return False
        benched = self._degradation_detector.is_benched(self.source_tag)
        if benched:
            logger.warning(
                "%s: provider is benched this session (silent-degradation "
                "guard) — returning no results",
                self.source_tag,
            )
        return benched

    def _evaluate_first_harvest(self, visible: list[Job], elapsed_s: float) -> bool:
        """Feed this page's FIRST harvest to the degradation guard.

        Only the first harvest is evaluated and recorded — the dry-scroll
        tail is expected to thin and must never reach the baseline. Returns
        False if the guard just benched the provider (caller fails closed).
        """
        if self._degradation_detector is None:
            return True
        try:
            page_bytes = len(getattr(self.browser, "page_source", "") or "")
        except Exception:
            page_bytes = 0
        self._degradation_detector.evaluate_first_harvest(
            provider=self.source_tag,
            visible_count=len(visible),
            page_bytes=page_bytes,
            elapsed_seconds=elapsed_s,
            route=self._extractor_label(),
        )
        if self._degradation_detector.is_benched(self.source_tag):
            logger.warning(
                "%s: harvest discarded — %d record(s) in %.1fs over %d bytes "
                "collapsed versus this provider's baseline. Treated as "
                "degraded content, NOT a valid harvest (fail closed).",
                self.source_tag,
                len(visible),
                elapsed_s,
                page_bytes,
            )
            return False
        return True

    def _scroll_height(self):
        """Read ``document.body.scrollHeight``; None if the browser cannot say.

        Read-only probe used purely for the scroll-observability log line.
        Never raises — a browser that cannot answer yields ``None``, which
        the log renders as ``None`` rather than breaking the harvest.
        """
        try:
            return self.browser.execute_script("return document.body.scrollHeight")
        except Exception:
            return None

    def _scroll_metrics(self):
        """Read ``(scrollHeight, scrollY + innerHeight)`` after a scroll step.

        One round trip for both values. Never raises — returns
        ``(None, None)`` when the browser cannot answer (static mode, mocks,
        dead session).
        """
        try:
            result = self.browser.execute_script(
                "return [document.body.scrollHeight, "
                "window.scrollY + window.innerHeight]"
            )
            if isinstance(result, (list, tuple)) and len(result) == 2:
                return result[0], result[1]
        except Exception:
            pass
        return None, None

    def _scroll_and_mine(
        self, scroller, page_index: int = 0, advance_method: str = ""
    ) -> dict:
        """Single source of truth for the scroll-and-mine harvest loop.

        Scrolls and mines the current page, deduplicating jobs, until one of
        three bounds is hit: the resolved result cap (self.max_results), the
        feed is exhausted (dry_scroll_limit consecutive scrolls with no new
        jobs — the guard the old naive loop lacked), or the scroller reports the
        end of the feed. Returns the {key: Job} map. Every provider path funnels
        through here so the stop conditions are identical everywhere.
        """
        unique: dict = {}
        consecutive_dry = 0
        first_harvest = True
        step = 0
        while True:
            harvest_started = time.monotonic()
            visible = self.miner.mine_jobs(source_name=self.source_tag)
            harvest_seconds = time.monotonic() - harvest_started

            if first_harvest:
                first_harvest = False
                if not self._evaluate_first_harvest(visible, harvest_seconds):
                    return unique  # empty — fail closed, discard the harvest

            new_count = 0
            for rank, job in enumerate(visible):
                key = job.url if job.url else f"{job.title}|{job.company}"
                if key not in unique:
                    _stamp_job_page(job, page_index, rank)
                    unique[key] = job
                    new_count += 1

            # Elapsed and route are logged per harvest so a growth curve is
            # readable straight from the console capture. Both live runs had to
            # be reconstructed from timestamps between log lines, and the
            # per-harvest cost (40 / 70 / 96 / 123s on one Google search) is
            # still unexplained on a page measured as structurally static.
            logger.info(
                "  %s harvest: %d visible, %d new (total %d) in %.1fs via %s.",
                self.source_tag, len(visible), new_count, len(unique),
                harvest_seconds, self._extractor_label(),
            )

            if len(unique) >= self.max_results:
                logger.info("  Result cap reached (%d). Stopping.", self.max_results)
                break

            consecutive_dry = consecutive_dry + 1 if new_count == 0 else 0
            if consecutive_dry >= self._dry_scroll_limit:
                logger.info(
                    "  Feed exhausted (%d dry scrolls). Stopping.", consecutive_dry
                )
                break

            if scroller is None:
                # No scroll collaborator (static mode, or no driver): mine
                # what is on the page and stop. Never raise — discovery
                # degrading to one screenful beats it dying.
                break
            height_before = self._scroll_height()
            if not scroller.next_page():
                logger.info("  Scroller reports end of feed. Stopping.")
                break
            step += 1
            height_after, viewport_bottom = self._scroll_metrics()
            logger.info(
                "  %s scroll %d: height %s -> %s, viewport bottom %s; "
                "harvest: %d new (total %d), dry %d/%d.",
                self.source_tag,
                step,
                height_before,
                height_after,
                viewport_bottom,
                new_count,
                len(unique),
                consecutive_dry,
                self._dry_scroll_limit,
            )

            time.sleep(self._inter_scroll_delay_s)

        # ── Deferred resolution, once the scroll loop is done ────────────
        # Activation clicks happen here — never mid-loop, so a click cannot
        # contaminate a harvest. Extra jobs arrive already gated; merge them
        # with the same dedup keys and the same result cap.
        finalize = getattr(self.miner, "finalize_harvest", None)
        if callable(finalize):
            try:
                for job in (
                    finalize(
                        source_name=self.source_tag,
                        page_index=page_index,
                        advance_method=advance_method,
                    )
                    or []
                ):
                    if len(unique) >= self.max_results:
                        break
                    key = job.url if job.url else f"{job.title}|{job.company}"
                    if key not in unique:
                        _stamp_job_page(job, page_index, -1)
                        unique[key] = job
            except Exception as exc:
                logger.debug("%s: finalize merge failed: %s", self.source_tag, exc)

        return unique

    def execute(self) -> list[Job]:
        """Executes the scraping logic: Audit → Clean → Check JSON‑LD → Scroll → Mine.

        Returns:
            List[Job]: A list of unique, valid jobs found.
        """
        if self._is_provider_benched():
            return []

        # 1. Audit & Health Check
        self.auditor.log_state(f"{self.source_tag} - Pre-Scrape")

        # Block check (D5): a blocked page is not an empty result set.
        block_type = self._page_block_type()
        if block_type is not None:
            return self._abort_blocked(block_type, "execute")

        # 2. Clear Interruptions (Cookies/Popups)
        self.interruption_handler.handle_interruptions()

        # ── 2a. Fast path: JSON‑LD structured data ───────────────────────────
        json_ld_jobs = (
            self._try_extract_json_ld() if self._json_ld_allowed() else []
        )
        if json_ld_jobs:
            logger.info(
                "%s: Extracted %d jobs via JSON‑LD — skipping scroll+mine.",
                self.source_tag,
                len(json_ld_jobs),
            )
            json_ld_jobs = self._paginate_json_ld(json_ld_jobs)
            self._observer.audit_final_job_list(json_ld_jobs, self.source_tag)
            return json_ld_jobs

        # 3. The Extraction Loop (Scroll & Mine)
        scroller = self._scroller

        logger.info(f"{self.source_tag}: Starting Scroll & Mine Loop...")
        unique_jobs = self._mine_all_pages(scroller)
        results = list(unique_jobs.values())
        self._observer.audit_final_job_list(results, self.source_tag)
        if not results:
            self._observer.audit_candidate_containers([], self.source_tag)
        logger.info(f"{self.source_tag}: Strategy complete. Total unique jobs: {len(results)}")
        return results

    def run(self) -> list[Job]:
        """Executes the scraping logic using 'Harvest-Then-Scroll'."""

        if self._is_provider_benched():
            return []

        # Block check (D5): run() uses the identical gate as execute().
        block_type = self._page_block_type()
        if block_type is not None:
            return self._abort_blocked(block_type, "run")

        # Overlay dismissal: run() previously never dismissed popups at all
        # (only execute() did). Both entry paths now dismiss once per page;
        # later pages are dismissed inside _mine_all_pages after each advance.
        self._dismiss_overlays()

        scroller = self._scroller

        logger.info(f"{self.source_tag}: Starting robust infinite scroll extraction...")

        # ── Fast path: JSON‑LD ───────────────────────────────────────────────
        json_ld_jobs = (
            self._try_extract_json_ld() if self._json_ld_allowed() else []
        )
        if json_ld_jobs:
            logger.info(
                "%s: Extracted %d jobs via JSON‑LD — skipping scroll.",
                self.source_tag,
                len(json_ld_jobs),
            )
            json_ld_jobs = self._paginate_json_ld(json_ld_jobs)
            self._observer.audit_final_job_list(json_ld_jobs, self.source_tag)
            return json_ld_jobs

        unique_jobs_map = self._mine_all_pages(scroller)
        jobs = list(unique_jobs_map.values())
        self._observer.audit_final_job_list(jobs, self.source_tag)
        if not jobs:
            self._observer.audit_candidate_containers([], self.source_tag)
        return jobs

    # ------------------------------------------------------------------
    # JSON‑LD fast‑path extraction
    # ------------------------------------------------------------------

    def _json_ld_allowed(self) -> bool:
        """Whether the JSON-LD fast path may run for this page.

        Unforced (the default) it always may, so discovery behaves exactly as
        it did. Forcing STRUCTURED_DATA also allows it — that IS the structured
        tier. Forcing any other tier skips the fast path so the forced
        extraction route is the one actually exercised, which is what makes a
        tier comparison meaningful rather than accidental.

        Note the fast path is still allowed to come up empty: a page with no
        JSON-LD falls through to mining as before, so forcing STRUCTURED_DATA
        on a page that has none degrades to a normal harvest instead of
        returning nothing.
        """
        return (
            self._forced_tier is None
            or self._forced_tier is PageAnalysisTier.STRUCTURED_DATA
        )

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
