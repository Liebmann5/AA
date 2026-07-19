"""Discovery Workflow — finds, pre-filters, deduplicates, and enqueues job listings.

What this engine does:
    Coordinate multiple job-search providers (Google, Bing, Indeed, company pages)
    to collect raw job listings, pre-screen them against blocked vocabularies and
    locations, deduplicate by URL, classify by ATS platform, and enqueue each
    unique candidate as a VET WorkUnit for the Vetting engine to process.

9-step sequence:
    1. _initialize_sources       — filter providers by runtime availability
    2. _build_search_instructions — cross-product of titles × locations × workplace types
    3. _execute_serp_discovery   — fan out to all active providers via ThreadPoolExecutor
    4. _scrape_company_pages     — optional direct-careers-page mining
    5. _prefilter_with_spacy     — drop blocked vocab/company/location matches cheaply
    6. _normalize_and_deduplicate — skip URL-duplicates, emit TASK_SKIPPED_DUPLICATE
    7. _classify_job_source      — stamp job.metadata["ats"] and ["provider"]
    8. _enqueue_vet_tasks        — push WorkUnit(VET) into task queue
    9. _emit_completion_summary  — publish DISCOVERY_COMPLETE with aggregate stats

All configuration comes from the frozen SessionPlan, never from a raw dict.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.research_port import JobPostingObservation, ResearchObserverPort, NullResearchObserver

logger = logging.getLogger(__name__)


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
        company_page_miner=None,
        company_page_scraper=None,
        plan: SessionPlan | None = None,
        browser_lease=None,
        research_observer: ResearchObserverPort | None = None,
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
            company_page_miner: Callable | None — direct company page scraper.
            company_page_scraper: Callable[[str], list[Job]] | None — given a
                single careers‑page URL, returns the jobs found on it.  Used by
                :meth:`discover_company_page` to service DISCOVER_COMPANY tasks.
            plan: SessionPlan — frozen runtime configuration (replaces config dict).
                When None, a minimal fallback plan is created.
            browser_lease: Optional BrowserLeaseManager for concurrency control.
            research_observer: ResearchObserverPort | None — new research signal pipeline.
        """
        self._profile = profile
        self._providers = providers
        self._task_queue = task_queue
        self._event_bus = event_bus
        self._dedup = dedup
        self._text_matcher = text_matcher
        self._ats_registry = ats_registry
        self._research_observer = research_observer or NullResearchObserver()
        self._company_page_miner = company_page_miner
        self._company_page_scraper = company_page_scraper
        self._browser_lease = browser_lease

        # Fallback: a minimal plan is always available
        if plan is not None:
            self._plan = plan
        else:
            self._plan = SessionPlan(session_id="discovery-fallback")

    # ------------------------------------------------------------------
    # Configuration access — all values come from the SessionPlan
    # ------------------------------------------------------------------

    @property
    def _max_concurrent_sources(self) -> int:
        return self._plan.max_concurrency

    @property
    def _max_queries_per_session(self) -> int:
        return self._plan.max_queries_per_session

    @property
    def _has_live_browser(self) -> bool:
        return self._plan.has_live_browser

    # ======================================================================
    # Public API
    # ======================================================================

    def _initialize_sources(self) -> list:
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
        return active

    def _build_search_instructions(
        self,
        override_instructions: list[SearchInstruction] | None = None,
    ) -> list[SearchInstruction]:
        """Builds the ordered list of SearchInstruction objects to execute.

        This is the **single source of truth** for what gets searched.
        Providers never read the profile or build their own matrices.

        When building profile‑derived instructions, the ``date_range`` from
        the frozen ``SessionPlan`` is propagated into every instruction.

        Args:
            override_instructions: When provided (from the orchestrator via
                a user‑specified search), these are used directly — they
                bypass the profile‑derived matrix entirely.  This is how
                the orchestrator's ``_handle_discovery`` communicates the
                user's intent.

        Returns:
            Ordered list of SearchInstruction objects, capped at
            ``max_queries_per_session``.
        """
        # ── Override path: user‑specified instructions from the orchestrator ─
        if override_instructions:
            cap = self._max_queries_per_session
            if len(override_instructions) > cap:
                logger.info(
                    "DiscoveryWorkflow: %d override instructions provided; "
                    "capped at max_queries_per_session=%d",
                    len(override_instructions),
                    cap,
                )
                return override_instructions[:cap]
            return list(override_instructions)

        # ── Profile‑derived path: build title × location × workplace_type ──
        prefs = getattr(self._profile, "search_preferences", None)
        titles: list[str] = getattr(prefs, "desired_job_titles", []) or []
        locations: list[str] = getattr(prefs, "preferred_locations", []) or [""]
        workplace_types: list[str] = getattr(prefs, "workplace_types", ["remote"]) or ["remote"]

        # Propagate the session‑level date_range into every instruction.
        plan_date_range = self._plan.date_range if self._plan else None

        instructions: list[SearchInstruction] = []
        for title in titles:
            for location in locations:
                for wtype in workplace_types:
                    instructions.append(SearchInstruction(
                        title=title,
                        location=location,
                        workplace_type=wtype,
                        date_range=plan_date_range,
                        max_results=self._plan.max_results_per_query,
                    ))

        cap = self._max_queries_per_session
        if len(instructions) > cap:
            logger.info(
                "DiscoveryWorkflow: profile‑derived instructions capped at "
                "max_queries_per_session=%d (generated %d)",
                cap,
                len(instructions),
            )
            instructions = instructions[:cap]

        return instructions

    def _execute_serp_discovery(
        self, instructions: list[SearchInstruction], active_providers: list
    ) -> list[Job]:
        """Fan out to all active providers, passing one instruction per call.

        Each provider receives exactly one :class:`SearchInstruction`.  The
        old override_criteria dict path has been deleted — providers no
        longer have access to the user profile.

        Args:
            instructions: The ordered list of search instructions to execute.
            active_providers: List of providers to fan out to.

        Returns:
            List of Job objects discovered across all providers and instructions.
        """
        all_jobs: list[Job] = []

        def _run_provider(provider, instr: SearchInstruction) -> list[Job]:
            name = getattr(provider, "name", type(provider).__name__)
            try:
                if self._browser_lease:
                    with self._browser_lease.acquire():
                        results = provider.run(instr)
                else:
                    results = provider.run(instr)
                logger.info(
                    "DiscoveryWorkflow: provider=%s instruction=%r found=%d",
                    name,
                    instr.title,
                    len(results),
                )
                return results or []
            except Exception as exc:
                logger.warning(
                    "DiscoveryWorkflow: provider=%s failed: %s", name, exc
                )
                return []

        max_workers = self._max_concurrent_sources
        if max_workers <= 1:
            for instr in instructions:
                for provider in active_providers:
                    all_jobs.extend(_run_provider(provider, instr))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_run_provider, provider, instr): (provider, instr)
                    for instr in instructions
                    for provider in active_providers
                }
                for future in as_completed(futures):
                    all_jobs.extend(future.result())

        return all_jobs

    def _scrape_company_pages(self, discovered_jobs: list[Job]) -> list[Job]:
        if self._company_page_miner is None:
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
                continue

            orgs = [o.lower() for o in entities.get("organizations", [])]
            if any(bc in orgs for bc in blocked_companies):
                continue

            locs = [loc.lower() for loc in entities.get("locations", [])]
            if any(bl in locs for bl in blocked_locations):
                continue

            passed.append(job)

        return passed

    def _normalize_and_deduplicate(self, jobs: list[Job]) -> list[Job]:
        unique: list[Job] = []
        for job in jobs:
            try:
                is_dup = self._dedup.is_duplicate(job.url)
            except Exception:
                is_dup = False
            if is_dup:
                try:
                    self._event_bus.publish(Event.TASK_SKIPPED_DUPLICATE, {"url": job.url})
                except Exception:
                    pass
                continue
            try:
                self._dedup.mark_seen(job.url)
            except Exception:
                pass
            unique.append(job)
        return unique

    def _classify_job_source(self, jobs: list[Job]) -> None:
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

    def _enqueue_vet_tasks(self, jobs: list[Job], execution_mode: SessionExecutionMode) -> int:
        # Respect execution mode – only enqueue VET if vetting is part of the pipeline.
        if not execution_mode.includes_vetting:
            logger.info(
                "DiscoveryWorkflow: execution_mode=%s — skipping VET enqueue for %d jobs",
                execution_mode, len(jobs),
            )
            return 0

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
        except Exception:
            pass

        # --- Research observation for each job -------------------------------------------------
        if self._research_observer is not None:
            for job in jobs:
                try:
                    description = ""  # FIXME: temporary, should be fetched if available
                    posting_hash = job.metadata.get("posting_hash") if hasattr(job, "metadata") else None
                    self._research_observer.observe_job_posting(
                        JobPostingObservation(
                            job_title=job.title,
                            job_description=description,
                            company_name=job.company,
                            location=job.location,
                            salary_min=None,
                            salary_max=None,
                            platform=getattr(job, "source", None),
                            first_seen_date=date.today(),
                            posting_hash=posting_hash,
                            jurisdiction=self._infer_jurisdiction(job.location or ""),
                            application_url_is_generic=self._looks_like_generic_apply_url(job.url),
                            metro_area=self._infer_metro_area(job.location or ""),
                        )
                    )
                except Exception:
                    pass

        return enqueued

    def _emit_completion_summary(self, stats: _DiscoveryStats) -> None:
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
        except Exception:
            pass

    def discover_company_page(self, careers_url: str, company_name: str = "Unknown") -> int:
        if self._company_page_scraper is None:
            return 0
        try:
            jobs: list[Job] = self._company_page_scraper(careers_url) or []
        except Exception as exc:
            logger.warning(
                "DiscoveryWorkflow: company page scrape failed | url=%s error=%s",
                careers_url, exc,
            )
            return 0

        jobs = self._prefilter_with_spacy(jobs)
        jobs = self._normalize_and_deduplicate(jobs)
        self._classify_job_source(jobs)
        # respect plan mode
        return self._enqueue_vet_tasks(jobs, self._plan.execution_mode)

    def run(
        self,
        instructions: list[SearchInstruction] | None = None,
        execution_mode: SessionExecutionMode | None = None,
    ) -> int:
        """Execute discovery and enqueue resulting VET tasks.

        Args:
            instructions: Optional explicit list of search instructions.
                When provided, these completely replace the profile‑derived
                matrix.  This is how the orchestrator communicates user
                overrides.  When None, instructions are built from the
                profile.
            execution_mode: Optional override for the session's execution mode.
                Falls back to self._plan.execution_mode if not provided.

        Returns:
            Number of VET tasks enqueued (0 if vetting is not included in mode).
        """
        mode = execution_mode if execution_mode is not None else self._plan.execution_mode
        stats = _DiscoveryStats()
        logger.info("DiscoveryWorkflow.run() starting | mode=%s", mode.value)

        active_providers = self._initialize_sources()
        if not active_providers:
            self._emit_completion_summary(stats)
            return 0

        search_instructions = self._build_search_instructions(
            override_instructions=instructions,
        )
        stats.queries_run = len(search_instructions)
        stats.providers_attempted = len(active_providers)

        all_jobs: list[Job] = []
        all_jobs.extend(self._execute_serp_discovery(search_instructions, active_providers))
        all_jobs.extend(self._scrape_company_pages(all_jobs))
        stats.raw_found = len(all_jobs)

        all_jobs = self._prefilter_with_spacy(all_jobs)
        stats.prefiltered_dropped = stats.raw_found - len(all_jobs)

        all_jobs = self._normalize_and_deduplicate(all_jobs)
        stats.deduped_dropped = (stats.raw_found - stats.prefiltered_dropped) - len(all_jobs)

        self._classify_job_source(all_jobs)
        stats.enqueued = self._enqueue_vet_tasks(all_jobs, mode)
        self._emit_completion_summary(stats)

        return stats.enqueued

    # ------------------------------------------------------------------
    # Research helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_jurisdiction(location: str) -> str | None:
        """Map a raw location string to a jurisdiction code used in pay_transparency_laws.yaml.

        Returns None if no match can be confidently made.
        """
        if not location:
            return None
        loc = location.lower()
        # State / city shorthand matches
        if any(term in loc for term in ("ca", "california", "san francisco", "los angeles", "san diego")):
            return "CA"
        if any(term in loc for term in ("ny", "new york", "nyc", "brooklyn", "queens", "manhattan")):
            return "NYC"
        if any(term in loc for term in ("wa", "washington", "seattle")):
            return "WA"
        if any(term in loc for term in ("co", "colorado", "denver")):
            return "CO"
        if any(term in loc for term in ("il", "illinois", "chicago")):
            return "IL"
        if any(term in loc for term in ("md", "maryland", "baltimore")):
            return "MD"
        if any(term in loc for term in ("hi", "hawaii", "honolulu")):
            return "HI"
        if any(term in loc for term in ("dc", "washington dc", "washington d.c.")):
            return "DC"
        if any(term in loc for term in ("nj", "new jersey", "newark")):
            return "NJ"
        if any(term in loc for term in ("ma", "massachusetts", "boston")):
            return "MA"
        if any(term in loc for term in ("mn", "minnesota", "minneapolis")):
            return "MN"
        return None

    @staticmethod
    def _infer_metro_area(location: str) -> str | None:
        """Map a location string to a Metropolitan Statistical Area (MSA) key used in col_index.yaml.

        Returns the exact dictionary key expected by the cost-of-living data, or None if no match.
        """
        if not location:
            return None
        loc = location.lower()
        # Prioritize more specific matches first
        mapping = {
            ("san francisco", "sf bay", "bay area"): "San Francisco-Oakland-Berkeley, CA",
            ("san jose", "silicon valley"): "San Jose-Sunnyvale-Santa Clara, CA",
            ("new york", "nyc", "brooklyn", "queens", "manhattan"): "New York-Newark-Jersey City, NY-NJ",
            ("los angeles", "la", "santa monica", "culver city"): "Los Angeles-Long Beach-Anaheim, CA",
            ("seattle", "bellevue"): "Seattle-Tacoma-Bellevue, WA",
            ("boston", "cambridge", "somerville"): "Boston-Cambridge-Newton, MA-NH",
            ("washington", "dc", "arlington", "alexandria"): "Washington-Arlington-Alexandria, DC-VA-MD-WV",
            ("san diego",): "San Diego-Chula Vista-Carlsbad, CA",
            ("denver", "aurora", "boulder"): "Denver-Aurora-Lakewood, CO",
            ("austin", "round rock", "georgetown"): "Austin-Round Rock-Georgetown, TX",
            ("chicago",): "Chicago-Naperville-Elgin, IL-IN-WI",
            ("portland",): "Portland-Vancouver-Hillsboro, OR-WA",
            ("miami", "fort lauderdale", "pompano"): "Miami-Fort Lauderdale-Pompano Beach, FL",
            ("atlanta", "sandy springs", "alpharetta"): "Atlanta-Sandy Springs-Alpharetta, GA",
            ("dallas", "fort worth", "arlington"): "Dallas-Fort Worth-Arlington, TX",
            ("phoenix", "mesa", "chandler"): "Phoenix-Mesa-Chandler, AZ",
            ("minneapolis", "st paul", "bloomington"): "Minneapolis-St. Paul-Bloomington, MN-WI",
            ("philadelphia", "camden", "wilmington"): "Philadelphia-Camden-Wilmington, PA-NJ-DE-MD",
            ("charlotte", "concord", "gastonia"): "Charlotte-Concord-Gastonia, NC-SC",
            ("raleigh", "cary"): "Raleigh-Cary, NC",
            ("nashville", "murfreesboro", "franklin"): "Nashville-Davidson--Murfreesboro--Franklin, TN",
            ("columbus",): "Columbus, OH",
            ("indianapolis", "carmel", "anderson"): "Indianapolis-Carmel-Anderson, IN",
            ("pittsburgh",): "Pittsburgh, PA",
            ("st louis", "st. louis"): "St. Louis, MO-IL",
            ("cincinnati",): "Cincinnati, OH-KY-IN",
            ("cleveland", "elyria"): "Cleveland-Elyria, OH",
            ("detroit", "warren", "dearborn"): "Detroit-Warren-Dearborn, MI",
            ("kansas city",): "Kansas City, MO-KS",
            ("memphis",): "Memphis, TN-MS-AR",
            ("oklahoma city",): "Oklahoma City, OK",
            ("birmingham", "hoover"): "Birmingham-Hoover, AL",
        }
        for keywords, msa in mapping.items():
            if any(kw in loc for kw in keywords):
                return msa
        return None

    @staticmethod
    def _looks_like_generic_apply_url(url: str) -> bool:
        """Detect if an 'Apply' link is broken or just drops the user on a homepage.

        Returns True if the URL scheme is mailto: or the path is empty / root.
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
            if parsed.scheme == "mailto":
                return True
            # Normalize path to remove trailing slash
            path = parsed.path.rstrip("/")
            if not path or path == "":
                return True
            return False
        except Exception:
            return False

    def shutdown(self) -> None:
        """Stop any background threads held by the workflow."""
        pass