"""Service for resolving a job posting URL into a Job object.

Used by the orchestrator to handle RESOLVE_JOB_URL tasks: given a URL,
navigates to the page if a live browser is available and extracts
title/company, or constructs a best-effort stub from URL analysis.
"""

from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import urlparse

from auto_apply.domain.models.job import Job
from auto_apply.domain.ports.browser_port import BrowserInterface

logger = logging.getLogger(__name__)

# Generic subdomain labels used by ATS/careers portals that are never
# themselves a company name (e.g. "jobs.techco.com" — "jobs" should be
# skipped in favor of "techco"). Anything NOT in this list is assumed to be
# a genuine, specific label (a company name, or a company's own subdomain)
# and is kept as-is rather than skipped.
_GENERIC_SUBDOMAIN_LABELS = frozenset({
    "jobs", "job", "careers", "career", "apply", "applications",
    "boards", "board", "recruiting", "recruit", "talent", "hiring",
})


class JobPostingResolver:
    """Resolves a raw job URL to a :class:`Job` using a live browser or URL heuristics.

    Inject into :class:`AgentOrchestrator` via the composition root.  The
    resolver is stateless; the driver is passed per call so that the same
    instance works with any active browser session.

    Args:
        idle_simulator: Optional callable ``(driver, min_seconds, max_seconds) ->
            None`` invoked after navigation to pause briefly before reading
            the page title, giving the page time to render and looking more
            human. Application-layer code stays decoupled from any specific
            evasion adapter — composition_root injects the real
            implementation (``adapters.secondary.evasion.components.behavior
            .simulate_idle_time``). If not supplied, navigation proceeds
            without an idle pause (graceful degradation, not a hard
            requirement of resolving a URL).
    """

    def __init__(
        self,
        idle_simulator: "Callable[..., None] | None" = None,
    ) -> None:
        self._idle_simulator = idle_simulator

    def resolve(self, url: str, driver: BrowserInterface | None = None) -> Job:
        """Attempt to navigate to *url* and extract metadata, falling back to a stub.

        Args:
            url: The job posting URL to resolve.
            driver: An optional active browser driver.  If provided (and
                succeeds), the page title and URL domain become the job's
                ``title`` and ``company`` fields.  Otherwise a best-effort
                stub is built from the URL alone.

        Returns:
            A :class:`~auto_apply.domain.models.job.Job` – never ``None``.
        """
        job: Job | None = None

        if driver is not None:
            job = self._extract_from_browser(url, driver)

        if job is not None:
            return job

        return self._build_stub(url)

    def _extract_from_browser(
        self, url: str, driver: BrowserInterface
    ) -> Job | None:
        """Navigate to the URL and extract title and company from the page.

        Returns ``None`` on any navigation or extraction failure.
        """
        try:
            driver.get(url)
            # Human-like settle pause — lets the page fully render
            if self._idle_simulator is not None:
                try:
                    self._idle_simulator(driver, min_seconds=1.5, max_seconds=3.0)
                except Exception:
                    pass

            # Get page title as job title proxy
            page_title = ""
            try:
                page_title = driver.title or ""
                # Strip common ATS suffixes ("— Greenhouse", "| Lever", etc.)
                for suffix in [" — ", " | ", " - ", " · "]:
                    if suffix in page_title:
                        page_title = page_title.split(suffix)[0].strip()
            except Exception:
                pass

            # Extract company from URL domain. Use the registrable-domain
            # label (second-from-last, e.g. "techco" in "jobs.techco.com" or
            # "careers.techco.com"), not naively the first label — a naive
            # split(".")[0] would incorrectly extract the subdomain itself
            # ("jobs", "careers") as the company name for any host that has
            # one, which is extremely common for ATS/careers subdomains.
            domain = self._company_label_from_netloc(url)
            company = domain or "Unknown Company"

            if not page_title:
                page_title = "Job Opening"

            return Job(
                title=page_title[:200],
                company=company[:200],
                url=url,
                location=None,
                source="user_direct_input",
            )

        except Exception as exc:
            logger.warning(
                "JobPostingResolver: navigation failed for %.60s — %s", url, exc
            )
            return None

    @staticmethod
    def _company_label_from_netloc(url: str) -> str:
        """Return the best-guess company-name label for *url*'s host, title-cased.

        Keeps the leftmost DNS label as the company name UNLESS it's a known
        generic ATS/careers-portal prefix (see ``_GENERIC_SUBDOMAIN_LABELS``,
        e.g. "jobs", "careers", "apply"), in which case that generic label is
        skipped in favor of the next one — "jobs.techco.com" should resolve
        to "Techco", not "Jobs". A label that ISN'T a known generic prefix is
        assumed to already be the company's own (sub)domain and is kept
        as-is, even if a further label follows — "this-is-a-very-long-
        company-name.example.com" should resolve to the long descriptive
        label, not to "example".
        """
        netloc = urlparse(url).netloc.replace("www.", "")
        labels = [p for p in netloc.split(".") if p]
        if not labels:
            return ""
        if labels[0].lower() in _GENERIC_SUBDOMAIN_LABELS and len(labels) >= 2:
            return labels[1].title()
        return labels[0].title()

    def _build_stub(self, url: str) -> Job:
        """Build a minimal stub Job from URL analysis (fallback)."""
        parsed = urlparse(url)
        domain = self._company_label_from_netloc(url)
        path_parts = [
            p.replace("-", " ").replace("_", " ")
            for p in parsed.path.strip("/").split("/")
            if p and not p.isdigit() and len(p) > 3
        ]
        title_hint = path_parts[-1].title() if path_parts else "Job Opening"

        logger.info(
            "JobPostingResolver: built stub Job | title=%s company=%s",
            title_hint,
            domain,
        )
        return Job(
            title=title_hint[:200],
            company=domain[:200] or "Unknown Company",
            url=url,
            location=None,
            source="user_direct_input",
        )