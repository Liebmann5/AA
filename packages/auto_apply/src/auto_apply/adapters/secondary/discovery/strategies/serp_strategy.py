"""Provides a generic, reusable strategy for scraping Search Engine Results Pages (SERPs).

This module contains the `GenericSERPStrategy`. It implements a high-level
algorithm: "Find the list container, iterate through items, parse details."
It relies on dependency injection for the specific finding and parsing logic,
making it adaptable to almost any list-based website (Google, Bing, Indeed).
"""

import json
import logging
import time
from typing import Optional

# Components
from auto_apply.domain.models.analysis_tier import PageAnalysisTier
from auto_apply.domain.ports.extraction_observer_port import (
    NullAuditReporter,
    NullExtractionObserver,
)
from auto_apply.adapters.secondary.discovery.components.miner import SemanticMiner
from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (
    FallbackSerpExtractor,
)
from auto_apply.application.services.dom.classifier import PageClassifier
from auto_apply.application.services.navigation.interruption import InterruptionHandler
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import JobSearchPreferences
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.types import PageType

from auto_apply.adapters.secondary.perception.dom_adapter import (
    BaseExtractor,
    SmartTextExtractor,
    SmartURLExtractor,
)
from auto_apply.adapters.secondary.evasion.detection import DefaultDetectionStrategy

logger = logging.getLogger(__name__)


class GenericSERPStrategy:
    """A reusable blueprint for scraping any page containing a list of search results.

    This class does not know *which* site it is scraping. It simply executes
    the provided extractors on whatever page the browser is currently on.
    """

    def __init__(
        self,
        browser: BrowserInterface,
        search_prefs: JobSearchPreferences,
        source_tag: str,
        title_parser: BaseExtractor | None = None,
        company_parser: BaseExtractor | None = None,
        url_parser: BaseExtractor | None = None,
        max_results: int = 30,
        dry_scroll_limit: int = 3,
        inter_scroll_delay_s: float = 2.0,
        scroller=None,
        paginator=None,
        max_pages: int = 1,
        observer=None,
        reporter=None,
        forced_tier: PageAnalysisTier | None = None,
        fast_extractor=None,
    ):
        """Initializes the strategy with specific parsing tools.

        Args:
            fast_extractor: Optional SerpExtractionPort tried before the DOM
                miner. When None (the default) the miner is used directly and
                nothing about discovery changes.
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
        # Scrolling and pagination arrive as collaborators. This adapter no
        # longer imports them across the layer boundary, and no longer
        # decides how a page advances — it only asks for the next one.
        self._scroller = scroller
        self._paginator = paginator
        # Ceiling, not a quota. Default 1 = today's single-page behaviour.
        self._max_pages = max(1, int(max_pages))

        self.interruption_handler = InterruptionHandler(browser)
        # Auditing is observation. Nulls by default, so an unwired audit
        # trail can never change or break what discovery extracts.
        self._observer = observer or NullExtractionObserver()
        self.auditor = reporter or NullAuditReporter()
        # None (the default) leaves the JSON-LD-then-mine order untouched.
        self._forced_tier = forced_tier

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

    def _mine_all_pages(self, scroller) -> dict:
        """Mines the current page, then advances while pages remain.

        With ``max_pages == 1`` (the shipped default) this runs the harvest
        exactly once and never touches the paginator, so discovery output is
        byte-for-byte what it was before pagination existed.

        Args:
            scroller: The injected scroll collaborator.

        Returns:
            The merged dict of unique jobs across every page visited.
        """
        unique = self._scroll_and_mine(scroller)

        for page in range(1, self._max_pages):
            if len(unique) >= self.max_results:
                break
            if self._paginator is None:
                break
            try:
                if not self._paginator.navigate_to_next_page():
                    logger.info(
                        "%s: no further pages after page %d", self.source_tag, page
                    )
                    break
            except Exception as exc:
                logger.debug("%s: pagination failed: %s", self.source_tag, exc)
                break
            logger.info("%s: advanced to page %d", self.source_tag, page + 1)
            unique.update(self._scroll_and_mine(scroller))

        return unique

    def _extractor_label(self) -> str:
        """Name the route that produced the last harvest, for the log line."""
        return getattr(self.miner, "route_label", type(self.miner).__name__)

    def _scroll_and_mine(self, scroller) -> dict:
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
        while True:
            harvest_started = time.monotonic()
            visible = self.miner.mine_jobs(source_name=self.source_tag)
            harvest_seconds = time.monotonic() - harvest_started
            new_count = 0
            for job in visible:
                key = job.url if job.url else f"{job.title}|{job.company}"
                if key not in unique:
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
            if not scroller.next_page():
                logger.info("  Scroller reports end of feed. Stopping.")
                break

            time.sleep(self._inter_scroll_delay_s)

        return unique

    def execute(self) -> list[Job]:
        """Executes the scraping logic: Audit → Clean → Check JSON‑LD → Scroll → Mine.

        Returns:
            List[Job]: A list of unique, valid jobs found.
        """
        # 1. Audit & Health Check
        self.auditor.log_state(f"{self.source_tag} - Pre-Scrape")

        # Health check only. The classifier does not mine — see
        # PageClassifier.classify for why the mine probe was removed.
        classifier = PageClassifier(
            self.browser,
            DefaultDetectionStrategy(self.browser),
        )

        page_type = classifier.classify()

        if page_type in {PageType.CAPTCHA_BLOCK, PageType.LOGIN_REQUIRED, PageType.ERROR_404}:
            logger.warning(f"{self.source_tag}: Page failed health check ({page_type.name}). Aborting strategy.")
            return []

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