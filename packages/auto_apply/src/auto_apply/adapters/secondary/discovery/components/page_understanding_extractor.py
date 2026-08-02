"""Single-script SERP extraction, with the DOM-walking miner kept as fallback.

``SemanticMiner`` reaches the page one WebDriver round trip at a time. On a
live Google SERP that was measured at ~150 round trips/second with a ~6 ms
median, 93% of the harvest's wall time spent on the wire, and 24% of responses
being "no such element" — the extractors exhausting every candidate selector
against every element and missing.

``MathDOMAdapter._EXTRACTION_SCRIPT`` already walks the entire DOM in one
``execute_script``. It has been built, and injected into ``GoogleProvider``,
and never read. This module is the read.

The fallback is not defensive decoration. ``analyze_serp`` has never produced a
job card on a live SERP — its input stage (``extract_full_dom_tree``) is
production-wired for ``DISCOVER_COMPANY`` and well covered, but its card
*detection* stage is a different implementation from the wired one and carries
two unit pins over a stubbed tree. So the fast path is tried, and the miner
that has worked for years catches it if it comes up empty.
"""

import logging
from typing import Any

from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.page_understanding_port import PageContext

logger = logging.getLogger(__name__)


class PageUnderstandingExtractor:
    """Adapts a :class:`PageUnderstandingPort` to :class:`SerpExtractionPort`.

    Validation is deliberately identical to ``SemanticMiner._extract_single_job``:
    a card becomes a :class:`Job` only if it has both a title and a URL, and an
    empty company becomes ``"Unknown"``. Two extraction routes that disagree
    about what counts as a job would make the fallback incomparable and the
    research dataset inconsistent.
    """

    def __init__(self, page_understanding: Any, browser: Any, observer: Any = None):
        """Store the collaborators.

        Args:
            page_understanding: An object with ``analyze_serp(PageContext)``.
            browser: The live browser, read only for URL and title.
            observer: Optional extraction observer. Receives one
                ``audit_extraction_attempt`` per card, matching the miner's use
                of that method. Nothing else is emitted — the fast path has no
                per-container elements to report, and inventing rows that no
                traversal produced would put fiction in the dataset.
        """
        self._page_understanding = page_understanding
        self._browser = browser
        self._observer = observer

    def _context(self) -> PageContext:
        """Build the page context, tolerating a browser that will not answer."""
        url = title = ""
        try:
            url = self._browser.current_url or ""
        except Exception:  # noqa: BLE001 - a dead browser must not raise here
            pass
        try:
            title = self._browser.title or ""
        except Exception:  # noqa: BLE001
            pass
        return PageContext(url=url, page_title=title)

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Extract listings via one page-understanding pass. Never raises."""
        try:
            structure = self._page_understanding.analyze_serp(self._context())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PageUnderstandingExtractor: analyze_serp failed (%s); "
                "reporting no jobs so the caller can fall back.", exc,
            )
            return []

        jobs: list[Job] = []
        seen = dropped_no_title = dropped_no_url = 0
        for card in getattr(structure, "job_cards", ()) or ():
            seen += 1
            title = (getattr(card, "title", "") or "").strip()
            url = (getattr(card, "url", "") or "").strip()
            company = (getattr(card, "company", "") or "").strip() or "Unknown"

            if not (title and url):
                if not title:
                    dropped_no_title += 1
                else:
                    dropped_no_url += 1
                self._audit({"title": title, "url": url}, False, "missing title or url")
                continue

            try:
                jobs.append(
                    Job(title=title, company=company, url=url, source=source_name)
                )
            except Exception as exc:  # noqa: BLE001
                self._audit({"title": title, "url": url}, False, f"invalid job: {exc}")
                continue
            self._audit({"title": title, "company": company, "url": url}, True)

        # Say what was thrown away, in the console, once per harvest. The
        # per-card audit rows go to the observer and never reach the log a
        # person actually reads, so a route that silently discards everything
        # looks identical to a page with nothing on it.
        if seen and len(jobs) != seen:
            logger.info(
                "%s: %d card(s) seen, %d kept, %d dropped (no title), "
                "%d dropped (no url).",
                source_name, seen, len(jobs), dropped_no_title, dropped_no_url,
            )

        return jobs

    def _audit(self, data: dict, success: bool, reason: str = "") -> None:
        if self._observer is None:
            return
        try:
            self._observer.audit_extraction_attempt(data, success, reason)
        except Exception:  # noqa: BLE001 - observation must never break extraction
            pass


class FallbackSerpExtractor:
    """Tries the fast extractor once, then commits to one route for the page.

    The commitment matters more than it looks. Without it, the dry-scroll tail
    would be the expensive case: a feed that is genuinely exhausted returns no
    new jobs for ``dry_scroll_limit`` consecutive harvests, and an
    "empty means fall back" rule would run a full miner pass on every one of
    them — making a search *slower* than before this class existed.

    So the decision is taken once per instance, on the first harvest, and
    logged:

    * fast path returns jobs        -> use it for the rest of the page
    * fast path returns nothing     -> use the miner for the rest of the page
    * fast path raises              -> use the miner for the rest of the page

    A page with genuinely no listings therefore costs one wasted fast attempt
    (tens of milliseconds) plus exactly what it costs today. That is the
    intended worst case: never worse than the miner alone.
    """

    def __init__(self, fast: Any, fallback: Any):
        self._fast = fast
        self._fallback = fallback
        self._chosen: Any = None
        self._route = "undecided"

    @property
    def route_label(self) -> str:
        """Which route this instance committed to — for logs and pins."""
        return self._route

    def mine_jobs(self, source_name: str) -> list[Job]:
        """Harvest via the committed route, choosing one on the first call."""
        if self._chosen is not None:
            return self._chosen.mine_jobs(source_name=source_name)

        try:
            jobs = self._fast.mine_jobs(source_name=source_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s: fast SERP extraction raised (%s) — falling back to the "
                "DOM miner for this page.", source_name, exc,
            )
            self._commit(self._fallback, "fallback:error")
            return self._fallback.mine_jobs(source_name=source_name)

        if jobs:
            self._commit(self._fast, "fast")
            logger.info(
                "%s: fast SERP extraction produced %d listings — using it for "
                "this page.", source_name, len(jobs),
            )
            return jobs

        logger.info(
            "%s: fast SERP extraction found no listings — falling back to the "
            "DOM miner for this page.", source_name,
        )
        self._commit(self._fallback, "fallback:empty")
        return self._fallback.mine_jobs(source_name=source_name)

    def _commit(self, route: Any, label: str) -> None:
        self._chosen = route
        self._route = label
