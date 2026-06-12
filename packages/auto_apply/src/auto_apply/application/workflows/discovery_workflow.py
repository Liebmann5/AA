"""Discovery Workflow — finds, pre-filters, deduplicates, and enqueues job listings.

What this engine does:
    Coordinate multiple job-search providers (Google, Bing, Indeed, company pages)
    to collect raw job listings, pre-screen them against blocked vocabularies and
    locations, deduplicate by URL, classify by ATS platform, and enqueue each
    unique candidate as a VET WorkUnit for the Vetting engine to process.

9-step sequence:
    1. _initialize_sources       — filter providers by runtime availability
    2. _build_search_queries     — cross-product of titles × locations × workplace types
    3. _execute_serp_discovery   — fan out to all active providers via ThreadPoolExecutor
    4. _scrape_company_pages     — optional direct-careers-page mining
    5. _prefilter_with_spacy     — drop blocked vocab/company/location matches cheaply
    6. _normalize_and_deduplicate — skip URL-duplicates, emit TASK_SKIPPED_DUPLICATE
    7. _classify_job_source      — stamp job.metadata["ats"] and ["provider"]
    8. _enqueue_vet_tasks        — push WorkUnit(VET) into task queue
    9. _emit_completion_summary  — publish DISCOVERY_COMPLETE with aggregate stats

Inputs:
    profile         — UserProfile (search criteria, blocked lists)
    providers       — list[DiscoveryProviderPort] (each implements .run())
    task_queue      — WorkQueuePort (receives VET WorkUnits)
    event_bus       — EventBus (receives discovery events)
    dedup           — DeduplicationManager (URL fingerprinting)
    text_matcher    — TextMatcher (entity extraction for pre-filtering)
    plan            — SessionPlan (frozen, single source of truth for runtime parameters)

Outputs:
    Returns int — count of VET WorkUnits enqueued.
    Publishes: JOBS_DISCOVERED, TASK_SKIPPED_DUPLICATE, DISCOVERY_COMPLETE.

Existing classes assembled here:
    DeduplicationManager  — application/services/data_processing/deduplication_manager.py
    TextMatcher           — application/services/text_matching.py
    ATSRegistry           — adapters/secondary/discovery/ats_registry.py
    EventBus              — application/agent/event_bus.py
    WorkUnit / TaskType   — domain/models/work_unit.py

How to extend:
    To add a new discovery source: implement DiscoveryProviderPort
    (domain/ports/discovery_port.py) and register the concrete class in
    infrastructure/composition_root.py under the providers list.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.session import SessionPlan
from auto_apply.domain.models.work_unit import TaskType, WorkUnit

logger = logging.getLogger(__name__)


@dataclass
class _SearchQuery:
    """A single job search query produced from the user's profile."""
    title: str
    location: str
    workplace_type: str
    raw_criteria: dict = field(default_factory=dict)


@dataclass
class _DiscoveryStats:
    queries_run: int = 0
    providers_attempted: int = 0
    providers_failed: int = 0
    raw_found: int = 0
    prefiltered_dropped: int = 0
    deduped_dropped: int = 0
    enqueued: int = 0


class DiscoveryWorkflow:
    """Orchestrates the full Discovery pipeline from search queries to VET queue entries."""

    def __init__(
        self,
        profile: UserProfile,
        providers: list,
        task_queue,
        event_bus,
        dedup,
        text_matcher,
        ats_registry=None,
        research_collector=None,
        company_page_miner=None,
        company_page_scraper=None,
        plan: SessionPlan = None,
        browser_lease=None,                 # NEW: BrowserLeaseManager or None
    ) -> None:
        """Initialize with all dependencies injected.

        Args:
            profile: The active user profile.
            providers: list[DiscoveryProviderPort] — job-search adapters.
            task_queue: WorkQueuePort — receives VET WorkUnits.
            event_bus: EventBus — receives discovery events.
            dedup: DeduplicationManager — URL fingerprinting and seen-URL tracking.
            text_matcher: TextMatcher — entity extraction for pre-filtering.
            ats_registry: ATSRegistry | None — ATS platform detection.
            research_collector: ResearchCollector | None — anonymized telemetry.
            company_page_miner: Callable | None — direct company page scraper.
            company_page_scraper: Callable[[str], list[Job]] | None — given a
                single careers-page URL, returns the jobs found on it. Used by
                :meth:`discover_company_page` to service DISCOVER_COMPANY tasks.
            plan: SessionPlan — frozen runtime configuration (replaces config dict).
            browser_lease: Optional BrowserLeaseManager for concurrency control.
        """
        self._profile = profile
        self._providers = providers
        self._task_queue = task_queue
        self._event_bus = event_bus
        self._dedup = dedup
        self._text_matcher = text_matcher
        self._ats_registry = ats_registry
        self._research_collector = research_collector
        self._company_page_miner = company_page_miner
        self._company_page_scraper = company_page_scraper
        self._plan = plan
        self._browser_lease = browser_lease          # NEW

        # If no plan was provided (backward compatibility), create a minimal
        # plan with sane defaults.
        if self._plan is None:
            self._plan = SessionPlan()

    # =========================================================================
    # Configuration access — all values come from the SessionPlan
    # =========================================================================

    @property
    def _max_concurrent_sources(self) -> int:
        """Maximum number of concurrent provider workers (1 = serial)."""
        return self._plan.max_concurrency

    @property
    def _max_queries_per_session(self) -> int:
        """Cap on cross-product queries per session."""
        return self._plan.max_queries_per_session

    @property
    def _has_live_browser(self) -> bool:
        """Whether a live browser is available (controls provider filtering)."""
        return self._plan.has_live_browser

    # =========================================================================
    # Public API
    # =========================================================================

    def _initialize_sources(self) -> list:
        """Filter providers by runtime availability.

        Providers with requires_live_browser=True are only included when the
        plan indicates a live browser is available.

        Returns:
            Filtered list of active providers.
        """
        active = []
        for provider in self._providers:
            needs_browser = getattr(provider, "requires_live_browser", False)
            if needs_browser and not self._has_live_browser:
                logger.info(
                    "DiscoveryWorkflow: skipping provider %s (requires live browser)",
                    getattr(provider, "name", type(provider).__name__),
                )
                continue
            active.append(provider)

        logger.info(
            "DiscoveryWorkflow: %d/%d providers active",
            len(active), len(self._providers),
        )
        return active

    def _build_search_queries(self) -> list[_SearchQuery]:
        """Cross-product of desired titles × preferred locations × workplace types.

        Returns:
            List of _SearchQuery objects, capped at max_queries_per_session.
        """
        prefs = getattr(self._profile, "search_preferences", None)
        titles: list[str] = getattr(prefs, "desired_job_titles", []) or []
        locations: list[str] = getattr(prefs, "preferred_locations", []) or [""]
        workplace_types: list[str] = getattr(prefs, "workplace_types", ["remote"]) or ["remote"]

        queries: list[_SearchQuery] = []
        for title in titles:
            for location in locations:
                for wtype in workplace_types:
                    queries.append(_SearchQuery(
                        title=title,
                        location=location,
                        workplace_type=wtype,
                        raw_criteria={
                            "title": title,
                            "location": location,
                            "workplace_type": wtype,
                        },
                    ))

        cap = self._max_queries_per_session
        if len(queries) > cap:
            logger.info(
                "DiscoveryWorkflow: capping queries %d → %d",
                len(queries), cap,
            )
            queries = queries[:cap]

        return queries

    def _execute_serp_discovery(
        self, queries: list[_SearchQuery], active_providers: list
    ) -> list[Job]:
        """Fan out to all active providers via ThreadPoolExecutor.

        Each (query, provider) pair is submitted as a future. A single provider
        failure never kills the pool — it is caught and logged individually.

        Args:
            queries: List of _SearchQuery objects.
            active_providers: Providers to use.

        Returns:
            Flat list of Job objects from all providers.
        """
        all_jobs: list[Job] = []

        def _run_provider(provider, criteria: dict) -> list[Job]:
            name = getattr(provider, "name", type(provider).__name__)
            try:
                # ❯❯❯ CONCURRENCY SAFETY: wrap provider.run() with browser lease ❮❮❮
                if self._browser_lease:
                    with self._browser_lease.acquire():
                        results = provider.run(override_criteria=criteria)
                else:
                    results = provider.run(override_criteria=criteria)
                logger.info(
                    "DiscoveryWorkflow: provider=%s found=%d",
                    name, len(results),
                )
                return results or []
            except Exception as exc:
                logger.warning(
                    "DiscoveryWorkflow: provider=%s failed: %s", name, exc
                )
                return []

        max_workers = self._max_concurrent_sources
        if max_workers <= 1:
            # Serial execution — no ThreadPoolExecutor overhead.
            for query in queries:
                for provider in active_providers:
                    all_jobs.extend(_run_provider(provider, query.raw_criteria))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_run_provider, provider, query.raw_criteria): (provider, query)
                    for query in queries
                    for provider in active_providers
                }
                for future in as_completed(futures):
                    all_jobs.extend(future.result())

        return all_jobs

    def _scrape_company_pages(self, discovered_jobs: list[Job]) -> list[Job]:
        """Mine direct company careers pages if a miner is configured.

        Args:
            discovered_jobs: Already-found jobs (used for ATS matching).

        Returns:
            Additional jobs found from company pages, or empty list.
        """
        if self._company_page_miner is None:
            logger.debug("DiscoveryWorkflow: no company_page_miner configured")
            return []

        extra: list[Job] = []
        for job in discovered_jobs:
            if self._ats_registry is None:
                continue
            try:
                descriptor = self._ats_registry.match(job.url)
                if descriptor is None:
                    continue
                mined = self._company_page_miner(job.url)
                if mined:
                    extra.extend(mined)
            except Exception as exc:
                logger.warning(
                    "DiscoveryWorkflow: company page mining failed url=%s error=%s",
                    job.url, exc,
                )
        return extra

    def _prefilter_with_spacy(self, jobs: list[Job]) -> list[Job]:
        """Drop blocked vocab/company/location matches before full vetting.

        Args:
            jobs: Raw job list.

        Returns:
            Filtered job list.
        """
        prefs = getattr(self._profile, "search_preferences", None)
        blocked_vocab: list[str] = [
            t.lower() for t in (getattr(prefs, "blocked_vocabulary", []) or [])
        ]
        blocked_companies: list[str] = [
            c.lower() for c in (getattr(prefs, "blocked_companies", []) or [])
        ]
        blocked_locations: list[str] = [
            loc.lower() for loc in (getattr(prefs, "blocked_locations", []) or [])
        ]

        if not (blocked_vocab or blocked_companies or blocked_locations):
            return jobs

        passed: list[Job] = []
        for job in jobs:
            text = f"{job.title or ''} {job.location or ''}"
            try:
                entities = self._text_matcher.extract_entities(text)
            except Exception:
                entities = {"skills": [], "locations": [], "organizations": [], "experience_years": []}

            title_lower = (job.title or "").lower()
            if any(word in title_lower for word in blocked_vocab):
                logger.debug("DiscoveryWorkflow: prefilter drop (vocab) | %s", job.title)
                continue

            orgs = [o.lower() for o in entities.get("organizations", [])]
            if any(bc in orgs for bc in blocked_companies):
                logger.debug("DiscoveryWorkflow: prefilter drop (company) | %s", job.company)
                continue

            locs = [loc.lower() for loc in entities.get("locations", [])]
            if any(bl in locs for bl in blocked_locations):
                logger.debug("DiscoveryWorkflow: prefilter drop (location) | %s", job.location)
                continue

            passed.append(job)

        dropped = len(jobs) - len(passed)
        if dropped:
            logger.info("DiscoveryWorkflow: prefilter dropped %d jobs", dropped)
        return passed

    def _normalize_and_deduplicate(self, jobs: list[Job]) -> list[Job]:
        """Skip URL-duplicates, emitting TASK_SKIPPED_DUPLICATE per drop.

        Args:
            jobs: Pre-filtered job list.

        Returns:
            Unique jobs only.
        """
        unique: list[Job] = []
        for job in jobs:
            try:
                is_dup = self._dedup.is_duplicate(job.url)
            except Exception:
                is_dup = False

            if is_dup:
                try:
                    self._event_bus.publish(
                        Event.TASK_SKIPPED_DUPLICATE, {"url": job.url}
                    )
                except Exception:
                    pass
                continue

            try:
                self._dedup.mark_seen(job.url)
            except Exception:
                pass

            unique.append(job)

        dropped = len(jobs) - len(unique)
        if dropped:
            logger.info("DiscoveryWorkflow: dedup dropped %d jobs", dropped)
        DiscoveryMathAuditor.audit_final_job_list(unique, 'after_dedup')
        return unique

    def _classify_job_source(self, jobs: list[Job]) -> None:
        """Stamp ATS platform and provider source into each job's metadata.

        Args:
            jobs: Deduplicated job list (mutated in place).
        """
        for job in jobs:
            if not hasattr(job, "metadata"):
                continue
            if self._ats_registry is not None:
                try:
                    descriptor = self._ats_registry.match(job.url)
                    job.metadata["ats"] = descriptor.name if descriptor else None
                except Exception:
                    job.metadata["ats"] = None
            job.metadata["provider"] = getattr(job, "source", None)

    def _enqueue_vet_tasks(self, jobs: list[Job]) -> int:
        """Push a VET WorkUnit for each job into the task queue.

        Args:
            jobs: Classified, unique job list.

        Returns:
            Count of WorkUnits enqueued.
        """
        enqueued = 0
        for job in jobs:
            try:
                self._task_queue.queue_task(
                    WorkUnit(
                        priority=5,
                        task_type=TaskType.VET,
                        payload=job,
                        source=getattr(job, "source", "discovery") or "discovery",
                        context_data={},
                    )
                )
                enqueued += 1
            except Exception as exc:
                logger.warning(
                    "DiscoveryWorkflow: failed to enqueue job=%s error=%s",
                    job.url, exc,
                )

        try:
            self._event_bus.publish(
                Event.JOBS_DISCOVERED, {"count": enqueued, "source": "discovery"}
            )
        except Exception as exc:
            logger.warning("DiscoveryWorkflow: failed to publish JOBS_DISCOVERED: %s", exc)

        return enqueued

    def _emit_completion_summary(self, stats: _DiscoveryStats) -> None:
        """Publish DISCOVERY_COMPLETE with aggregate stats.

        Args:
            stats: Accumulated stats from this run.
        """
        payload = {
            "queries_run": stats.queries_run,
            "providers_attempted": stats.providers_attempted,
            "providers_failed": stats.providers_failed,
            "raw_found": stats.raw_found,
            "prefiltered_dropped": stats.prefiltered_dropped,
            "deduped_dropped": stats.deduped_dropped,
            "enqueued": stats.enqueued,
        }
        try:
            self._event_bus.publish(Event.DISCOVERY_COMPLETE, payload)
        except Exception as exc:
            logger.warning("DiscoveryWorkflow: failed to publish DISCOVERY_COMPLETE: %s", exc)

        if self._research_collector is not None:
            try:
                self._research_collector.record_signal(
                    Event.DISCOVERY_COMPLETE,
                    {
                        "queries_run": stats.queries_run,
                        "enqueued": stats.enqueued,
                        "prefiltered_dropped": stats.prefiltered_dropped,
                        "deduped_dropped": stats.deduped_dropped,
                    },
                )
            except Exception:
                pass

    def discover_company_page(
        self, careers_url: str, company_name: str = "Unknown"
    ) -> int:
        """Discover jobs on a single company careers page and enqueue them.

        Services a DISCOVER_COMPANY task: scrape one careers URL via the injected
        ``company_page_scraper``, then run the same pre-filter → dedup → classify
        → enqueue-VET tail the SERP path uses. Reuses the workflow's own
        deduplication and queueing so behaviour matches the main discovery path.

        Args:
            careers_url: The company careers/jobs page to scrape.
            company_name: Optional company label (telemetry only).

        Returns:
            Count of VET WorkUnits enqueued.
        """
        if self._company_page_scraper is None:
            logger.warning(
                "DiscoveryWorkflow: no company_page_scraper configured — "
                "cannot service DISCOVER_COMPANY for %s",
                careers_url,
            )
            return 0

        try:
            jobs: list[Job] = self._company_page_scraper(careers_url) or []
        except Exception as exc:
            logger.warning(
                "DiscoveryWorkflow: company page scrape failed | url=%s error=%s",
                careers_url, exc,
            )
            return 0

        logger.info(
            "DiscoveryWorkflow.discover_company_page | company=%s url=%s raw=%d",
            company_name, careers_url, len(jobs),
        )

        jobs = self._prefilter_with_spacy(jobs)
        jobs = self._normalize_and_deduplicate(jobs)
        self._classify_job_source(jobs)
        return self._enqueue_vet_tasks(jobs)

    def run(self, override_criteria: dict | None = None) -> int:
        """Run the full Discovery workflow end to end.

        Executes steps 1–9 in order. Each step's output feeds the next.
        All exceptions within individual steps are caught and logged — no step
        failure propagates to the caller unless it is a programming error.

        Args:
            override_criteria: If provided, overrides profile-derived search criteria.
                               Used by orchestrator when user provides manual search terms.

        Returns:
            Count of VET WorkUnits enqueued in the task queue.
        """
        stats = _DiscoveryStats()
        logger.info("DiscoveryWorkflow.run() starting")

        active_providers = self._initialize_sources()
        if not active_providers:
            logger.warning("DiscoveryWorkflow: no active providers available, aborting.")
            self._emit_completion_summary(stats)
            return 0

        queries = self._build_search_queries()
        if override_criteria:
            queries = [_SearchQuery(
                title=override_criteria.get("title", ""),
                location=override_criteria.get("location", ""),
                workplace_type=override_criteria.get("workplace_type", "remote"),
                raw_criteria=override_criteria,
            )]
        stats.queries_run = len(queries)
        stats.providers_attempted = len(active_providers)

        all_jobs: list[Job] = []
        all_jobs.extend(self._execute_serp_discovery(queries, active_providers))
        all_jobs.extend(self._scrape_company_pages(all_jobs))
        stats.raw_found = len(all_jobs)

        all_jobs = self._prefilter_with_spacy(all_jobs)
        stats.prefiltered_dropped = stats.raw_found - len(all_jobs)

        all_jobs = self._normalize_and_deduplicate(all_jobs)
        stats.deduped_dropped = (stats.raw_found - stats.prefiltered_dropped) - len(all_jobs)

        self._classify_job_source(all_jobs)
        stats.enqueued = self._enqueue_vet_tasks(all_jobs)
        self._emit_completion_summary(stats)

        logger.info(
            "DiscoveryWorkflow.run() complete | queries=%d raw=%d prefiltered=%d deduped=%d enqueued=%d",
            stats.queries_run, stats.raw_found, stats.prefiltered_dropped,
            stats.deduped_dropped, stats.enqueued,
        )
        return stats.enqueued