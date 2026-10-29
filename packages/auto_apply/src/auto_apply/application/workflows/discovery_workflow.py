"""Discovery Workflow — finds, pre-filters, deduplicates, and enqueues job listings.

What this engine does:
    Coordinate multiple job-search providers (Google, Bing, Indeed, company pages)
    to collect raw job listings, pre-screen them against blocked vocabularies and
    locations, deduplicate by URL, classify by ATS platform, and enqueue each
    unique candidate as a VET WorkUnit for the Vetting engine to process.

10-step sequence:
    1. _initialize_sources       — filter providers by the session plan's
                                   active_providers (stage U3: a SessionRequest
                                   naming one engine runs one engine), then by
                                   runtime availability
    2. _build_search_instructions — cross-product of titles × locations × workplace types
    3. _execute_serp_discovery   — fan out to all active providers via ThreadPoolExecutor
    4. _scrape_company_pages     — optional direct-careers-page mining
    5. _prefilter_with_spacy     — drop blocked vocab/company/location matches cheaply
    6. _normalize_and_deduplicate — skip URL-duplicates, emit TASK_SKIPPED_DUPLICATE
    7. _classify_job_source      — stamp job.metadata["ats"] and ["provider"]
    8. _persist_discovered_jobs  — record unique jobs with session_id and their
                                   provenance (mode-independent)
    9. _enqueue_vet_tasks        — push WorkUnit(VET) into task queue
    10. _emit_completion_summary — publish DISCOVERY_COMPLETE with aggregate stats

All configuration comes from the frozen SessionPlan, never from a raw dict.
"""

from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from auto_apply.application.services.auditing.discovery_math_auditor import DiscoveryMathAuditor
from auto_apply.application.services.auditing.discovery_verification import DiscoveryVerifier
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.research_port import (
    NullResearchObserver,
    ResearchObserverPort,
    SearchPlanObservation,
)

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
    budget_skipped: int = 0
    off_shape_dropped: int = 0
    terminal_dropped: int = 0
    routed_to_mining: int = 0


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
        provider_order_rng: random.Random | None = None,
        search_planner=None,
        engine_hosts: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize with all dependencies injected.

        Args:
            profile: The active user profile.
            providers: list[DiscoveryProviderPort] — job-search adapters.
            task_queue: WorkQueuePort — receives VET WorkUnits. Also serves as
                the discovery persistence sink: ``record_job_discovery`` is
                called on it concretely before the execution-mode branch so
                results survive DISCOVER_ONLY sessions.
            event_bus: EventBus — receives discovery events.
            dedup: DeduplicationManager — URL fingerprinting and seen-URL tracking.
            text_matcher: TextMatcher — entity extraction for pre-filtering.
            ats_registry: ATSRegistry | None — ATS platform detection.
            company_page_miner: Deprecated and unused. The previous mining
                call passed a URL into a parameter that composition_root filled
                with a function expecting a browser, and failed on every
                ATS-matched job; mining now goes through company_page_scraper
                under the SessionPlan.enable_company_page_mining gate. The
                parameter remains accepted for one release; the automated-
                search chain removes it.
            company_page_scraper: Callable[[str], list[Job]] | None — given a
                single careers‑page URL, returns the jobs found on it.  Used by
                :meth:`discover_company_page` to service DISCOVER_COMPANY tasks.
            plan: SessionPlan — frozen runtime configuration (replaces config dict).
                When None, a minimal fallback plan is created.
            browser_lease: Optional BrowserLeaseManager for concurrency control.
            research_observer: ResearchObserverPort | None — new research signal pipeline.
            search_planner: SearchPlanner | None — plans site-restricted
                (ATS-targeted) queries when the session enables them. None
                leaves the default query path untouched.
        """
        self._profile = profile
        self._providers = providers
        # Seeded, namespaced RNG for provider-order cycling: shuffles which SERP
        # provider is tried first each search, so runs are not always Google-first
        # (a CAPTCHA magnet) and stay reproducible when a session seed is set. None
        # -> a fresh unseeded Random (non-deterministic order).
        self._provider_rng = provider_order_rng or random.Random()
        self._task_queue = task_queue
        self._event_bus = event_bus
        self._dedup = dedup
        self._text_matcher = text_matcher
        self._ats_registry = ats_registry
        self._research_observer = research_observer or NullResearchObserver()
        self._company_page_miner = company_page_miner
        self._company_page_scraper = company_page_scraper
        self._browser_lease = browser_lease
        self._search_planner = search_planner
        self._site_search_warned = False
        self._engine_hosts = engine_hosts
        # The session query budget and the engine rotation are owned HERE —
        # this workflow is the one component that spans DISCOVER tasks, and
        # the planner is deliberately stateless.
        self._queries_sent_this_session: int = 0
        self._engine_rotation_offset: int = 0

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
        # Stage U3: the fan-out honors the session plan's active_providers.
        # Empty tuple means "not declared" — the plan default stands, and an
        # empty allowed set never filters (fail-open: it cannot zero out a
        # session). A provider is only ever excluded on evidence — a real
        # string name not in the allowed set — never on a mock or an unknown
        # attribute type.
        allowed = {a.lower() for a in self._plan.active_providers}
        for provider in self._providers:
            name = getattr(provider, "name", None)
            if allowed and isinstance(name, str) and name.lower() not in allowed:
                logger.info(
                    "DiscoveryWorkflow: skipping provider %s — not in the "
                    "session plan's active providers %s",
                    name,
                    sorted(allowed),
                )
                continue
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

        Precedence: explicit overrides (user-specified, via the orchestrator)
        > plan-declared ``search_pairs`` > site-restricted planning (when
        ``use_ats_site_search`` is engaged) > the profile-derived matrix.

        Returns:
            Ordered list of SearchInstruction objects, capped at
            ``max_queries_per_session``.
        """
        # ── Override path: user‑specified instructions from the orchestrator ─
        # When ATS site search is engaged, a generic seeded override (title
        # and location only) is expanded through the planner instead of run
        # as-is; an override carrying a raw query string is a verbatim
        # power-user query and is never touched.
        if override_instructions:
            override_instructions = self._expand_overrides(override_instructions)
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

        # ── Plan-declared pairs: an explicit query set (``search_pairs``)
        #    overrides the profile-derived matrix, after user overrides. ──
        if self._plan is not None and self._plan.search_pairs:
            paired = [
                SearchInstruction(
                    title=pair.title,
                    location=pair.location,
                    workplace_type=pair.workplace_type,
                    date_range=plan_date_range,
                    max_results=self._plan.max_results_per_query,
                )
                for pair in self._plan.search_pairs
            ]
            return paired[: self._max_queries_per_session]

        # ── Site-restricted planning (ATS-targeted search) ──
        if self._site_search_engaged():
            planned = self._plan_site_restricted(
                titles, locations, workplace_types, plan_date_range
            )
            logger.info(
                "DiscoveryWorkflow: site-restricted planning produced %d instructions",
                len(planned),
            )
            return planned
        self._warn_site_search_inactive_once()

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

    # ------------------------------------------------------------------
    # Site-restricted (ATS-targeted) planning
    # ------------------------------------------------------------------

    def _site_search_engaged(self) -> bool:
        """True when ATS-targeted search is configured and a planner exists."""
        return bool(
            self._plan is not None
            and self._plan.use_ats_site_search
            and self._plan.ats_platforms
            and self._search_planner is not None
        )

    def _warn_site_search_inactive_once(self) -> None:
        """Warn once when the flag is on but no platforms can be planned."""
        if self._site_search_warned:
            return
        self._site_search_warned = True
        if self._plan is not None and self._plan.use_ats_site_search:
            logger.warning(
                "DiscoveryWorkflow: discovery.use_ats_site_search is on but "
                "no platforms are usable (ats_platforms empty or planner "
                "unavailable) — running the normal queries."
            )

    def _expand_overrides(
        self, instructions: list[SearchInstruction]
    ) -> list[SearchInstruction]:
        """Expand seeded generic overrides through the planner when engaged.

        An override carrying a raw query string is a verbatim power-user
        query and passes through untouched.
        """
        if not self._site_search_engaged():
            return list(instructions)
        expanded: list[SearchInstruction] = []
        for instruction in instructions:
            if instruction.raw_query_string:
                expanded.append(instruction)
                continue
            expanded.extend(
                self._plan_for_bases(
                    (
                        (
                            instruction.title,
                            instruction.location,
                            instruction.workplace_type,
                        ),
                    )
                )
            )
        return expanded

    def _plan_site_restricted(
        self,
        titles: list[str],
        locations: list[str],
        workplace_types: list[str],
        plan_date_range,
    ) -> list[SearchInstruction]:
        """Plan site-restricted instructions for the profile's search bases.

        Bases are titles × locations. No engine strategy reads the workplace
        type (verified in engine_strategies.build_search_url), so each base
        is planned once with the profile's first workplace type rather than
        duplicated per type the way the generic matrix multiplies identical
        queries.
        """
        bases = tuple(
            (title, location, workplace_types[0])
            for title in titles
            for location in locations
        )
        return self._plan_for_bases(bases, plan_date_range)

    def _plan_for_bases(
        self,
        bases: tuple[tuple[str, str, str], ...],
        plan_date_range=None,
    ) -> list[SearchInstruction]:
        """Run the planner over bases and convert its output to instructions.

        The session budget is owned here: the planner is told how many
        queries remain for the WHOLE session, not a fresh cap per task, and
        the engine rotation carries across task boundaries so no engine gets
        two consecutive planned queries while another enabled engine exists.
        """
        remaining = max(
            0, self._max_queries_per_session - self._queries_sent_this_session
        )
        if remaining <= 0:
            logger.warning(
                "DiscoveryWorkflow: session query budget (%d) already spent — "
                "no planning for this task",
                self._max_queries_per_session,
            )
            return []
        base_engines = tuple(self._plan.active_providers)
        engines = base_engines
        if base_engines and self._engine_rotation_offset:
            off = self._engine_rotation_offset % len(base_engines)
            engines = base_engines[off:] + base_engines[:off]
        planned = self._search_planner.plan(
            bases=bases,
            engines=engines,
            platforms=tuple(self._plan.ats_platforms),
            date_range=(
                self._plan.date_range if plan_date_range is None else plan_date_range
            ),
            max_results=self._plan.max_results_per_query,
            budget=remaining,
        )
        for note in planned.notes:
            if note.severity == "warning":
                logger.warning("SearchPlanner: %s", note.message)
            else:
                logger.info("SearchPlanner: %s", note.message)
        self._emit_search_plan_frame(
            planned, engines=engines, budget_before=remaining
        )
        if base_engines:
            bound = [q.engine for q in planned.queries if q.engine]
            if bound and bound[-1] in base_engines:
                self._engine_rotation_offset = (
                    base_engines.index(bound[-1]) + 1
                ) % len(base_engines)
        return [self._instruction_from_planned(query) for query in planned.queries]

    @staticmethod
    def _instruction_from_planned(query) -> SearchInstruction:
        """Convert a planner query into the SearchInstruction providers run."""
        return SearchInstruction(
            title=query.title,
            location=query.location,
            workplace_type=query.workplace_type,
            raw_query_string=query.raw_query_string,
            date_range=query.date_range,
            max_results=query.max_results,
            engine=query.engine,
            surface_template=query.surface_template,
            platform=query.platform,
        )

    def _order_providers(self, active_providers: list) -> list:
        """Return a seeded shuffle of the active SERP providers.

        Cycling the provider order each search spreads first-hit load across
        Google/Bing/Indeed instead of always leading with one (which invites an
        immediate CAPTCHA), and is reproducible when a session seed is set. The
        input list is not mutated. The chosen order is logged for auditability.
        """
        if len(active_providers) <= 1:
            return list(active_providers)
        ordered = list(active_providers)
        self._provider_rng.shuffle(ordered)
        logger.info(
            "Discovery provider order: %s",
            ", ".join(str(getattr(p, "name", type(p).__name__)) for p in ordered),
        )
        return ordered

    def _execute_serp_discovery(
        self,
        instructions: list[SearchInstruction],
        active_providers: list,
        stats: _DiscoveryStats | None = None,
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
        active_providers = self._order_providers(active_providers)

        # The session budget binds at the fan-out — the one place every
        # instruction (planned or generic) passes through on its way out.
        affordable: list[SearchInstruction] = []
        skipped = 0
        for instr in instructions:
            if self._queries_sent_this_session >= self._max_queries_per_session:
                skipped += 1
                continue
            self._queries_sent_this_session += 1
            affordable.append(instr)
        if skipped:
            if stats is not None:
                stats.budget_skipped += skipped
            logger.warning(
                "DiscoveryWorkflow: session query budget (%d) reached — %d "
                "instruction(s) not sent",
                self._max_queries_per_session,
                skipped,
            )
        instructions = affordable

        def _run_provider(provider, instr: SearchInstruction) -> list[Job]:
            name = getattr(provider, "name", type(provider).__name__)
            # Engine-bound instructions (from site-restricted planning) run
            # only on their engine's provider. An engine that cannot carry
            # the query gets nothing, never a degraded version of it.
            if instr.engine is not None and str(name).lower() != instr.engine:
                return []
            try:
                if self._browser_lease:
                    with self._browser_lease.acquire():
                        results = provider.run(instr)
                else:
                    results = provider.run(instr)
                # Provenance: every job states which query, platform and
                # engine form produced it. setdefault — a provider's own
                # stamp wins.
                for job in results or []:
                    try:
                        job.metadata.setdefault(
                            "search_query", instr.effective_query
                        )
                        job.metadata.setdefault(
                            "route",
                            "engine_site_search"
                            if instr.platform
                            else "provider_serp",
                        )
                        if instr.platform:
                            job.metadata.setdefault(
                                "target_platform", instr.platform
                            )
                        if instr.surface_template:
                            job.metadata.setdefault(
                                "engine_form", instr.surface_template
                            )
                    except Exception:
                        pass
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
        """Optionally mine company careers pages for ATS-matched discoveries.

        Off by default: SessionPlan.enable_company_page_mining is False
        unless a plan sets it, and no config currently sets it. The previous
        path called a composition-root helper that treated the job URL as a
        browser object — a measured AttributeError on every ATS-matched job
        that mined nothing, ever. When enabled, mining goes through the
        careers-page scraper, which actually navigates to the URL.
        """
        if not self._plan.enable_company_page_mining:
            return []
        if self._company_page_scraper is None:
            return []
        extra: list[Job] = []
        for job in discovered_jobs:
            if self._ats_registry is None:
                continue
            try:
                descriptor = self._ats_registry.match(job.url)
                if descriptor is None:
                    continue
                mined = self._company_page_scraper(job.url)
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

    def _persist_discovered_jobs(self, jobs: list[Job]) -> int:
        """Persist each unique discovered job with the current session id.

        Called before the execution-mode branch so discovery results survive
        even when the session never vets or applies (DISCOVER_ONLY) — and
        even if the process dies mid-run: the rows are on disk the moment the
        provider's results are deduplicated.

        The table is history, not a reprocessing guard (see
        DatabaseManager.record_job_discovery). INSERT OR IGNORE keeps repeat
        sightings idempotent across sessions; a URL keeps the session_id of
        the session that recorded it first.

        Returns:
            Count of newly recorded rows.
        """
        session_id = self._plan.session_id
        recorded = 0
        for job in jobs:
            try:
                if self._task_queue.record_job_discovery(job, session_id=session_id):
                    recorded += 1
            except Exception as exc:
                logger.warning(
                    "DiscoveryWorkflow: failed to persist discovered job | url=%s error=%s",
                    job.url,
                    exc,
                )
        if recorded or jobs:
            logger.info(
                "DiscoveryWorkflow: persisted %d/%d discovered jobs | session=%s",
                recorded,
                len(jobs),
                session_id,
            )
        return recorded

    def _handle_off_shape_hits(self, jobs: list[Job]) -> tuple[list[Job], dict[str, int]]:
        """Handle hits that are not postings of the platform they targeted.

        Only jobs stamped ``target_platform`` by the planner path are
        examined; everything else passes through untouched. A hit on one of
        the platform's terminal shapes (success/confirm/closed) is dropped
        and never followed. A hit that matches no posting pattern for its
        target platform is a board, a listing page or noise: when company-page
        mining is enabled it becomes a DISCOVER_COMPANY task; otherwise it is
        dropped. Each outcome is counted and reported.
        """
        counts = {"dropped": 0, "terminal": 0, "mined": 0}
        if self._ats_registry is None:
            return jobs, counts
        kept: list[Job] = []
        for job in jobs:
            try:
                platform = str(job.metadata.get("target_platform") or "")
            except Exception:
                kept.append(job)
                continue
            if not platform:
                kept.append(job)
                continue
            try:
                if self._ats_registry.is_terminal_page(job.url):
                    counts["terminal"] += 1
                    logger.info(
                        "DiscoveryWorkflow: terminal page never followed | url=%s",
                        job.url,
                    )
                    continue
                descriptor = self._ats_registry.match(job.url)
            except Exception as exc:
                logger.debug("DiscoveryWorkflow: registry match failed: %s", exc)
                kept.append(job)
                continue
            if descriptor is not None and descriptor.name == platform:
                kept.append(job)
                continue
            if (
                self._plan.enable_company_page_mining
                and self._plan.execution_mode.includes_discovery
            ):
                try:
                    self._task_queue.queue_task(
                        WorkUnit(
                            priority=4,
                            task_type=TaskType.DISCOVER_COMPANY,
                            payload={
                                "careers_url": job.url,
                                "company_name": job.company or "Unknown",
                            },
                            source="site_search_off_shape",
                            context_data={"target_platform": platform},
                        )
                    )
                    counts["mined"] += 1
                    logger.info(
                        "DiscoveryWorkflow: off-shape hit routed to company "
                        "mining | platform=%s url=%s",
                        platform,
                        job.url,
                    )
                except Exception as exc:
                    counts["dropped"] += 1
                    logger.warning(
                        "DiscoveryWorkflow: off-shape routing failed | url=%s error=%s",
                        job.url,
                        exc,
                    )
            else:
                counts["dropped"] += 1
                logger.info(
                    "DiscoveryWorkflow: off-shape hit dropped | platform=%s url=%s",
                    platform,
                    job.url,
                )
        return kept, counts

    def _emit_search_plan_frame(
        self,
        planned,
        *,
        engines: tuple[str, ...],
        budget_before: int,
    ) -> None:
        """Emit the session's sampling frame to research (consent-gated).

        The frame is names and counts only — which engines and platforms were
        searched, how many queries each received, how many targets were
        dropped. Query text, titles and locations NEVER appear in it: those
        are the user's search, and the research store does not carry them.
        """
        observer = self._research_observer
        if not getattr(observer, "is_enabled", False):
            return
        try:
            per_engine: dict[str, int] = {}
            per_platform: dict[str, int] = {}
            for query in planned.queries:
                if query.engine:
                    per_engine[query.engine] = per_engine.get(query.engine, 0) + 1
                if query.platform:
                    per_platform[query.platform] = (
                        per_platform.get(query.platform, 0) + 1
                    )
            observer.observe_search_plan(
                SearchPlanObservation(
                    engines=tuple(sorted(engines)),
                    platforms=tuple(sorted(per_platform)),
                    queries_planned=len(planned.queries),
                    per_engine=tuple(sorted(per_engine.items())),
                    per_platform=tuple(sorted(per_platform.items())),
                    dropped_count=len(planned.dropped_targets),
                    notes_info=sum(1 for n in planned.notes if n.severity == "info"),
                    notes_warning=sum(
                        1 for n in planned.notes if n.severity == "warning"
                    ),
                    budget_before=budget_before,
                    budget_after=budget_before - len(planned.queries),
                )
            )
        except Exception as exc:
            logger.debug(
                "DiscoveryWorkflow: sampling-frame observation failed (non-fatal): %s",
                exc,
            )

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
                        priority=TaskPriority.VET,
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
            "budget_skipped": stats.budget_skipped,
            "off_shape_dropped": stats.off_shape_dropped,
            "terminal_dropped": stats.terminal_dropped,
            "routed_to_mining": stats.routed_to_mining,
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
        self._persist_discovered_jobs(jobs)
        self._classify_job_source(jobs)
        # JOBS_DISCOVERED carries the unique found count in every mode.
        try:
            self._event_bus.publish(
                Event.JOBS_DISCOVERED, {"count": len(jobs), "source": "discovery"}
            )
        except Exception:
            pass
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
        all_jobs.extend(
            self._execute_serp_discovery(search_instructions, active_providers, stats)
        )
        all_jobs.extend(self._scrape_company_pages(all_jobs))
        stats.raw_found = len(all_jobs)

        all_jobs = self._prefilter_with_spacy(all_jobs)
        stats.prefiltered_dropped = stats.raw_found - len(all_jobs)

        all_jobs = self._normalize_and_deduplicate(all_jobs)
        stats.deduped_dropped = (stats.raw_found - stats.prefiltered_dropped) - len(all_jobs)

        all_jobs, off_shape = self._handle_off_shape_hits(all_jobs)
        stats.off_shape_dropped = off_shape["dropped"]
        stats.terminal_dropped = off_shape["terminal"]
        stats.routed_to_mining = off_shape["mined"]

        # ── Persist before the mode branch (C1) ─────────────────────────────
        # A job is persisted the moment it is known, so results survive
        # DISCOVER_ONLY sessions and process death alike. This is history,
        # not a skip list.
        # Stamp provider and platform first, so the stored row carries them.
        self._classify_job_source(all_jobs)
        self._persist_discovered_jobs(all_jobs)

        # Verify the output is real before enqueueing: valid fields, no
        # duplicates, and within the resolved per-query ceiling. "Know, not
        # hope." The report is logged (loud on failure) but never raised — bad
        # discovery output should be visible on every run, not fatal.
        ceiling = (
            len(active_providers)
            * sum(instr.max_results for instr in search_instructions)
        ) or None
        report = DiscoveryVerifier(
            max_results=ceiling, engine_hosts=self._engine_hosts
        ).verify(all_jobs)
        if report.passed:
            logger.info(report.summary())
        else:
            logger.warning("%s\n%s", report.summary(), report.details())

        # JOBS_DISCOVERED carries the unique found count in EVERY mode. It
        # used to be published from _enqueue_vet_tasks with the vet enqueue
        # count, which is 0 when vetting is skipped — both the controller's
        # report and the live dashboard recorded zero for DISCOVER_ONLY.
        try:
            self._event_bus.publish(
                Event.JOBS_DISCOVERED, {"count": len(all_jobs), "source": "discovery"}
            )
        except Exception:
            pass

        stats.enqueued = self._enqueue_vet_tasks(all_jobs, mode)
        self._emit_completion_summary(stats)

        return stats.enqueued

    def shutdown(self) -> None:
        """Stop any background threads held by the workflow."""
        pass
