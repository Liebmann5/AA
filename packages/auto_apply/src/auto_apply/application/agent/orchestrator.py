"""The master controller for the autonomous agent execution workflow.

This module provides the AgentOrchestrator class, which operates as an
event-driven dispatcher processing WorkUnits from a persistent priority queue.
It coordinates all three domain engines (Discovery, Vetting, Application),
manages browser and network health, and guarantees resilience through
checkpointing and graceful failure recovery.

Design Philosophy:
    The orchestrator is a "Platform," not a "Script." It does not follow a
    hardcoded linear sequence. Instead, it maintains a priority queue of
    WorkUnits, routes each to the correct engine, and reacts to the results
    by generating new work. This design makes it trivially extensible: adding
    a new domain is adding a new TaskType and a new handler method.

Threading Model:
    The main event loop runs synchronously in whatever thread calls run().
    Background health monitors (browser, network) run in separate daemon
    threads and communicate exclusively via the EventBus. This avoids all
    async/sync mixing complexity and works reliably on the lowest-spec
    hardware (worst-case users).

    DO NOT introduce asyncio.create_task() or asyncio.run() into this module.
    The threading model is intentional and correct for this use case.

Example:
    >>> from auto_apply.infrastructure.composition_root import build_orchestrator, CapabilitiesRegistry
    >>>
    >>> registry = CapabilitiesRegistry.build()
    >>> orchestrator = build_orchestrator(registry)
    >>> orchestrator.run()  # Blocks until stop() is called
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.state_machine import AgentState, StateMachine
from auto_apply.application.services.data_processing.checkpoint_manager import (
    CheckpointManager,
)
from auto_apply.application.services.data_processing.deduplication_manager import (
    DeduplicationManager,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.resources import RuntimeProfile
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.repository_port import JobRepositoryPort
from auto_apply.domain.ports.work_queue_port import WorkQueuePort

if TYPE_CHECKING:
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """The master controller for the autonomous job application workflow.

    Routes WorkUnits from a persistent priority queue to the correct domain
    engine. All domain engines are lazy-loaded on first use to minimize
    startup memory cost for low-resource users.

    Resilience guarantees:
        - Crash recovery: State is checkpointed every N completed tasks.
          On next startup, SessionController will call recover_from_checkpoint()
          before calling run(), transparently resuming the prior session.
        - Browser failure: Detected by BrowserHealthMonitor via the EventBus.
          The orchestrator subscribes to BROWSER_UNHEALTHY and triggers a
          safe driver teardown + restart.
        - Network failure: Detected by NetworkHealthMonitor. The orchestrator
          pauses the event loop and waits for reconnection before resuming.
        - Task failure: Failed tasks are re-queued with incremented retry
          count up to MAX_TASK_RETRIES. After exhaustion they are marked
          permanently failed and logged for telemetry analysis.
        - Provider watchdog (Phase 5): A ProviderWatchdog thread monitors
          heartbeat of provider workers and publishes PROVIDER_TIMED_OUT when
          a worker appears stuck.

    Company batching optimization:
        Application tasks are buffered by company domain. Once a company
        bucket reaches BATCH_THRESHOLD, all its jobs are submitted in one
        sequential run, reducing browser navigation overhead. At queue
        exhaustion, remaining buffers are flushed regardless of size.

    Args:
        profile: Loaded user profile containing settings and credentials.
        resources: Negotiated runtime profile (browser choice, concurrency).
        registry: The CapabilitiesRegistry for this environment. This is the
            single source of truth for tool availability and effective config.
        task_queue: Port for the persistent priority work queue.
        db: Port for job application history (deduplication and recording).
        event_bus: The shared EventBus for inter-component communication.
        driver: Optional pre-initialized browser driver. If None, tasks that
            require browser access will raise RuntimeError until a driver is
            provided via the composition root.
        captcha_resolver: Optional resolver for automated CAPTCHA handling.
            Must expose ``resolve(payload, driver) -> bool``. If None, CAPTCHA
            tasks are immediately escalated to manual intervention.

    Attributes:
        running: True while the event loop is active.
        paused: True when execution is temporarily suspended.
        state: The current AgentState as tracked by the StateMachine.
    """

    # Maximum times a task is retried before permanent failure.
    MAX_TASK_RETRIES: int = 3

    # Checkpoint is saved after this many successfully completed tasks.
    CHECKPOINT_INTERVAL: int = 5

    # Number of jobs for one company that triggers a batch application run.
    BATCH_THRESHOLD: int = 3

    # Seconds to sleep when the work queue is empty before checking again.
    IDLE_SLEEP_SECONDS: float = 2.0

    def __init__(  # noqa: PLR0913
        self,
        profile: UserProfile,
        resources: RuntimeProfile,
        registry: CapabilitiesRegistry,
        task_queue: WorkQueuePort,
        db: JobRepositoryPort,
        event_bus: EventBus,
        driver: BrowserInterface | None = None,
        captcha_resolver: Any | None = None,
        browser_monitor: Any | None = None,
        network_monitor: Any | None = None,
        watchdog: Any | None = None,              # ← Phase 5: ProviderWatchdog
    ) -> None:
        """Initializes all orchestrator components.

        Direct construction is for use by infrastructure/composition_root.py only.
        Call ``build_orchestrator(registry)`` to wire all dependencies correctly.

        Args:
            profile: The loaded user profile.
            resources: The negotiated runtime resource profile.
            registry: The central capability and config authority.
            task_queue: Port for work-unit persistence and priority dequeuing.
            db: Port for job application history — deduplication and recording.
            event_bus: The pub/sub event system shared across all components.
            driver: Optional active browser session. Tasks that require browser
                access will fail until a driver is available.
            captcha_resolver: Optional CAPTCHA resolution service. Injected by
                composition_root. If None, CAPTCHAs escalate to manual solving.
        """
        # ── Core dependencies ─────────────────────────────────────────────
        self.profile = profile
        self.resources = resources
        self.registry = registry
        self.task_queue = task_queue
        self.db = db
        self.event_bus = event_bus

        # ── Session state ─────────────────────────────────────────────────
        self.context = ExecutionContext(
            profile=profile,
            session_id=f"session_{int(time.time())}",
        )
        self.context.resources = resources

        self.state_machine = StateMachine(initial_state=AgentState.IDLE)
        self.running: bool = False
        self.paused: bool = False

        # ── Browser management ────────────────────────────────────────────
        # Browser lifecycle is managed by the composition root and injected
        # here. The orchestrator never creates or selects a browser driver.
        self._driver: BrowserInterface | None = driver
        self._captcha_resolver = captcha_resolver

        # ── Resilience services ───────────────────────────────────────────
        self.dedup_manager = DeduplicationManager()
        self.checkpoint_manager = CheckpointManager(
            storage_path=profile.get_checkpoint_path(),
            checkpoint_interval=self.CHECKPOINT_INTERVAL,
        )

        # ── Health monitors — injected, started as daemon threads in run() ─
        self._browser_monitor: Any | None = browser_monitor
        self._network_monitor: Any | None = network_monitor
        self._monitor_threads: list[threading.Thread] = []

        # ── Provider watchdog (Phase 5) ────────────────────────────────────
        self._watchdog: Any | None = watchdog

        # ── Application batching buffer: {company_key: [Job, ...]} ────────
        self._application_buffer: dict[str, list[Job]] = defaultdict(list)

        # ── Workflow orchestrators (the live execution path) ──────────────
        # Populated by build_orchestrator(). Each TaskType is dispatched to the
        # corresponding *Workflow.run(); see _dispatch_task / _get_workflow.
        self._workflows: dict[str, Any] = {}

        # Retained for backward compatibility with any external inspectors;
        # no longer the dispatch path (the workflows superseded the engines).
        self._engines: dict[str, Any] = {}

        # ── Wire EventBus subscriptions ───────────────────────────────────
        self._register_event_handlers()

        logger.info(
            "AgentOrchestrator initialized | session=%s",
            self.context.session_id,
        )

    # =========================================================================
    # MAIN EVENT LOOP
    # =========================================================================

    def run(self) -> None:
        """Starts the main event loop. Blocks until stop() is called.

        Call this from SessionController, which runs it in a background thread
        so the GUI/CLI remain responsive.

        Sequence on every iteration:
            1. Pause check — if paused, sleep and retry.
            2. Batch readiness — if a company bucket is full, flush it now.
            3. Dequeue next WorkUnit — highest priority first.
            4. Queue-empty handling — flush remaining buffers, then idle.
            5. Deduplication check — skip if URL already seen or applied.
            6. Browser readiness — initialize or restart driver if needed.
            7. Network readiness — pause if offline, wait for reconnection.
            8. Dispatch — route WorkUnit to the correct handler.
            9. Mark complete in the database.
            10. Checkpoint — auto-save if interval threshold is met.

        Raises:
            Nothing. All exceptions are caught, logged, and handled per-task.
            The loop itself never propagates an exception to the caller.
        """
        logger.info("AgentOrchestrator starting | session=%s", self.context.session_id)
        self.running = True
        self.state_machine.transition_to(AgentState.INITIALIZING)

        # Start background health monitors in daemon threads.
        # Daemon threads are automatically killed when the main thread exits,
        # so no explicit cleanup is required if the process terminates hard.
        self._start_health_monitors()

        # Attempt to restore state from a previous session's checkpoint.
        self._attempt_checkpoint_recovery()
        self.task_queue.recover_interrupted_tasks()

        self.state_machine.transition_to(AgentState.RUNNING)

        while self.running:
            task: WorkUnit | None = None

            # ── 1. Pause handling ─────────────────────────────────────────
            if self.paused:
                time.sleep(1.0)
                continue

            try:
                # ── 2. Batch readiness check ──────────────────────────────
                # Process a full company bucket before pulling new tasks.
                # This keeps company-grouped applications contiguous.
                if self._check_batch_ready():
                    self._process_ready_batch()
                    continue

                # ── 3. Dequeue next task ──────────────────────────────────
                task = self.task_queue.get_next_task()

                if not task:
                    # ── 4. Queue empty handling ───────────────────────────
                    if self._application_buffer:
                        # Flush all remaining buffers regardless of size.
                        self._flush_all_batches()
                        continue

                    # Truly idle — nothing pending anywhere.
                    logger.debug("Work queue empty, idling...")
                    self.state_machine.transition_to(AgentState.IDLE)
                    time.sleep(self.IDLE_SLEEP_SECONDS)
                    continue

                # ── 5. Deduplication check ────────────────────────────────
                if self._is_duplicate_task(task):
                    logger.debug(
                        "Skipping duplicate task | type=%s id=%s",
                        task.task_type.name,
                        task.id,
                    )
                    self.task_queue.mark_task_complete(task.id, skipped=True)
                    continue

                # ── 6. Browser readiness ──────────────────────────────────
                # APPLY and VET tasks require a live browser.
                # DISCOVER may use a live browser or static fetch depending
                # on the PageAccessStrategy selected by CapabilitiesRegistry.
                if self._requires_browser(task):
                    self._ensure_browser_active()

                # ── 7. Network readiness ──────────────────────────────────
                if self._network_monitor and not self._network_monitor.is_healthy():
                    logger.warning(
                        "Network unavailable — pausing until reconnected"
                    )
                    self._pause_until_network_restored()

                # ── 8. Update context and dispatch ────────────────────────
                self.context.current_work_unit = task
                self._dispatch_task(task)

                # ── 9. Mark complete ──────────────────────────────────────
                self.task_queue.mark_task_complete(task.id)

                # ── 10. Auto-checkpoint ───────────────────────────────────
                self.checkpoint_manager.record_action_and_maybe_save(self.context)

            except Exception as exc:
                self._handle_task_error(task, exc)

        # ── Cleanup on graceful exit ──────────────────────────────────────
        self._teardown()
        logger.info(
            "AgentOrchestrator stopped gracefully | session=%s",
            self.context.session_id,
        )

    # =========================================================================
    # EXECUTION CONTROL (called from GUI/CLI/SessionController)
    # =========================================================================

    def stop(self) -> None:
        """Signals the event loop to exit after completing the current task.

        Does not kill the loop mid-task. The loop checks self.running at the
        top of each iteration and exits cleanly.

        Example:
            >>> orchestrator.stop()  # Triggers graceful shutdown
        """
        logger.info("Stop signal received")
        self.running = False
        self.state_machine.transition_to(AgentState.STOPPING)

    def pause(self) -> None:
        """Suspends task dispatching without destroying browser state.

        The browser session remains alive during a pause. Used by the network
        monitor, the user pause button, and CAPTCHA handlers.

        Example:
            >>> orchestrator.pause()
            >>> # Perform out-of-band action...
            >>> orchestrator.resume()
        """
        self.paused = True
        self.state_machine.transition_to(AgentState.PAUSED)
        logger.info("Execution paused")

    def resume(self) -> None:
        """Resumes task dispatching after a pause.

        Example:
            >>> orchestrator.resume()
        """
        self.paused = False
        self.state_machine.transition_to(AgentState.RUNNING)
        logger.info("Execution resumed")

    def seed_work_queue(self, work_units: list[WorkUnit]) -> None:
        """Populates the work queue with initial tasks before run() is called.

        Called by SessionController after the user completes the wizard or
        provides manual links. Must be called before run(); calling it after
        the loop is already running is safe but tasks will interleave with
        ongoing work.

        Args:
            work_units: The initial list of WorkUnits to enqueue.

        Example:
            >>> from auto_apply.domain.models.work_unit import WorkUnit, TaskType
            >>> tasks = [WorkUnit(priority=5, task_type=TaskType.DISCOVER,
            ...                  payload=criteria, source="wizard")]
            >>> orchestrator.seed_work_queue(tasks)
            >>> orchestrator.run()
        """
        for unit in work_units:
            self.task_queue.queue_task(unit)
        logger.info("Seeded work queue with %d initial tasks", len(work_units))

    # =========================================================================
    # TASK DISPATCHING
    # =========================================================================

    def _dispatch_task(self, task: WorkUnit) -> None:
        """Routes a WorkUnit to the correct domain engine handler.

        This is the central routing table. Adding a new task type requires
        only adding a new branch here and a new _handle_* method below.

        Args:
            task: The WorkUnit to process.

        Raises:
            RuntimeError: If the TaskType is not recognized. This is a
                programming error, not a runtime error, and should surface
                during development, not in production.
        """
        logger.info(
            "Dispatching | type=%-18s priority=%d id=%s",
            task.task_type.name,
            task.priority,
            task.id,
        )

        dispatch_table = {
            TaskType.DISCOVER:         self._handle_discovery,
            TaskType.DISCOVER_COMPANY: self._handle_company_discovery,
            TaskType.VET:              self._handle_vetting,
            TaskType.APPLY:            self._buffer_application,
            TaskType.HANDLE_CAPTCHA:   self._handle_captcha,
        }

        handler = dispatch_table.get(task.task_type)
        if handler is None:
            raise RuntimeError(
                f"Unknown TaskType '{task.task_type}' — add a handler in "
                f"_dispatch_task() and a _handle_* method."
            )

        handler(task)

    # =========================================================================
    # DOMAIN ENGINE HANDLERS
    # =========================================================================

    def _handle_discovery(self, task: WorkUnit) -> None:
        """Runs job discovery for a search query and enqueues results.

        Delegates to DiscoveryWorkflow.run(), which fans out to all active
        providers, pre-filters, deduplicates, and enqueues a VET WorkUnit per
        unique job — so this handler only translates the task payload into the
        workflow's override-criteria shape and records the resulting count.

        Args:
            task: WorkUnit whose payload is a search-criteria dict, e.g.
                  ``{"query": "...", "location": "..."}``.
        """
        self.state_machine.transition_to(AgentState.DISCOVERING)
        workflow = self._get_workflow("DiscoveryWorkflow")

        # Translate the seeded payload ({"query", "location"}) into the
        # workflow's override-criteria shape ({"title", "location", ...}).
        payload = task.payload if isinstance(task.payload, dict) else {}
        override_criteria = {
            "title": payload.get("title") or payload.get("query", ""),
            "location": payload.get("location", ""),
            "workplace_type": payload.get("workplace_type", "remote"),
        }

        enqueued: int = workflow.run(override_criteria=override_criteria)

        logger.info("Discovery complete | enqueued=%d", enqueued)
        self.context.update_stats("discovered", enqueued)

        self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_handle_discovery")

    def _handle_company_discovery(self, task: WorkUnit) -> None:
        """Scrapes a company careers page and enqueues all found jobs.

        Used when the user provides a company careers URL directly, or when
        a SERP result redirects to a company's own job board. All discovered
        jobs are routed through vetting before application.

        Args:
            task: WorkUnit whose payload is:
                  {'company_name': str, 'careers_url': str}
        """
        self.state_machine.transition_to(AgentState.DISCOVERING)
        workflow = self._get_workflow("DiscoveryWorkflow")

        company_name: str = task.payload.get("company_name", "Unknown")
        careers_url: str = task.payload.get("careers_url", "")

        logger.info("Deep-scanning company careers page | company=%s", company_name)

        # DiscoveryWorkflow scrapes the single URL, then runs the same
        # pre-filter → dedup → classify → enqueue-VET tail as the SERP path.
        enqueued: int = workflow.discover_company_page(careers_url, company_name)

        logger.info(
            "Company discovery complete | company=%s enqueued=%d",
            company_name,
            enqueued,
        )
        self.context.update_stats("discovered", enqueued)

        self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_handle_company_discovery")

    def _handle_vetting(self, task: WorkUnit) -> None:
        """Runs the vetting filter pipeline against a single job.

        If the job passes all filters it becomes an APPLY task. If it fails,
        the rejection reason is logged for telemetry.

        Note on page co-location: If VettingEngine detects that the job
        description page also contains an application form (same-page or
        iframe), it records the form location in the Job object's metadata.
        The resulting APPLY WorkUnit carries this metadata in context_data
        so ApplicationEngine can navigate directly without re-scanning.

        Args:
            task: WorkUnit whose payload is a Job object.
        """
        self.state_machine.transition_to(AgentState.VETTING)
        workflow = self._get_workflow("VettingWorkflow")
        job: Job = task.payload

        # VettingWorkflow runs the filter chain, computes the weighted fit
        # score, persists the outcome, publishes JOB_VETTED_PASS/FAIL, and
        # enqueues the APPLY WorkUnit itself when the job passes.
        passed: bool = workflow.run(job)

        if passed:
            logger.info("Vetting PASSED | title=%s company=%s", job.title, job.company)
            self.context.update_stats("vetted", 1)

        self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_handle_vetting")

    def _buffer_application(self, task: WorkUnit) -> None:
        """Adds an APPLY task to the company batch buffer.

        Rather than applying immediately, jobs are grouped by company so
        AA can navigate a company's ATS domain once and submit multiple
        applications in sequence, reducing context-switching overhead and
        making the session look more human (a person would review multiple
        roles at one company before leaving).

        Args:
            task: WorkUnit whose payload is a Job object.
        """
        job: Job = task.payload

        # Normalize company key for consistent bucketing.
        company_key = job.company.lower().strip()
        self._application_buffer[company_key].append(job)

        logger.info(
            "Buffered application | company=%s buffer_size=%d",
            job.company,
            len(self._application_buffer[company_key]),
        )

    def _handle_captcha(self, task: WorkUnit) -> None:
        """Handles a CAPTCHA interruption by pausing for resolution.

        If a captcha_resolver was injected at construction, attempts automatic
        resolution. On failure or when no resolver is configured, emits an
        event so the GUI can prompt the user for manual solving.

        Args:
            task: WorkUnit whose payload contains CAPTCHA challenge details.
        """
        logger.warning("CAPTCHA encountered")

        if self._captcha_resolver is None:
            logger.info("No captcha resolver configured — escalating to manual solve")
            self.event_bus.publish(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE, task.payload)
            self.pause()
            return

        self.state_machine.transition_to(AgentState.RESOLVING_CAPTCHA)
        resolved: bool = self._captcha_resolver.resolve(task.payload, driver=self._driver)

        if resolved:
            logger.info("CAPTCHA resolved automatically")
            self.state_machine.transition_to(AgentState.RUNNING)
        else:
            logger.warning("Auto-resolution failed — pausing for manual intervention")
            self.event_bus.publish(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE, task.payload)
            self.pause()

    # =========================================================================
    # BATCH PROCESSING
    # =========================================================================

    def _check_batch_ready(self) -> bool:
        """Returns True if any company bucket has reached BATCH_THRESHOLD.

        Returns:
            True if at least one company has enough buffered jobs to warrant
            a batch application run.
        """
        return any(
            len(jobs) >= self.BATCH_THRESHOLD
            for jobs in self._application_buffer.values()
        )

    def _process_ready_batch(self) -> None:
        """Applies to all jobs in the first company bucket that is full.

        Selects the largest ready bucket to maximize the benefit of the
        batching optimization.
        """
        # Select the company with the most buffered jobs.
        target_company = max(
            (
                company for company, jobs in self._application_buffer.items()
                if len(jobs) >= self.BATCH_THRESHOLD
            ),
            key=lambda c: len(self._application_buffer[c]),
        )
        self._apply_batch(target_company, self._application_buffer.pop(target_company))

    def _flush_all_batches(self) -> None:
        """Applies to all remaining buffered jobs regardless of bucket size.

        Called when the work queue is empty. Ensures no jobs are left
        unapplied simply because their company bucket never hit the threshold.
        """
        logger.info("Flushing %d company batches", len(self._application_buffer))

        # Copy keys to avoid mutation during iteration.
        for company_key in list(self._application_buffer.keys()):
            jobs = self._application_buffer.pop(company_key)
            if jobs:
                self._apply_batch(company_key, jobs)

    def _apply_batch(self, company_key: str, jobs: list[Job]) -> None:
        """Executes all applications for a single company batch.

        Args:
            company_key: Normalized company name used as the buffer key.
            jobs: The list of Job objects to apply to.
        """
        self.state_machine.transition_to(AgentState.APPLYING)
        workflow = self._get_workflow("ApplicationsWorkflow")

        logger.info(
            "Applying batch | company=%s count=%d", company_key, len(jobs)
        )

        for job in jobs:
            # Abort remaining jobs if the session was stopped mid-batch.
            if not self.running:
                logger.info("Session stopped mid-batch, aborting remaining jobs")
                break

            # Skip any job that was already applied to in a prior session.
            if self.db.was_applied(job.url):
                logger.debug(
                    "Already applied in prior session, skipping | url=%s",
                    job.url,
                )
                continue

            try:
                # ApplicationsWorkflow persists the outcome (mark_applied) and
                # publishes APPLICATION_SUBMITTED / APPLICATION_FAILED itself;
                # the orchestrator only tracks aggregate session stats here.
                success = workflow.run(job=job, session_id=self.context.session_id)

                if success:
                    self.context.update_stats("applied", 1)
                    logger.info(
                        "\u2713 Applied | title=%s company=%s",
                        job.title,
                        job.company,
                    )
                else:
                    self.context.update_stats("failed", 1)
                    logger.warning(
                        "\u2717 Application failed | title=%s company=%s",
                        job.title,
                        job.company,
                    )

            except Exception as exc:
                self.context.update_stats("failed", 1)
                logger.error(
                    "Application exception | title=%s error=%s",
                    job.title,
                    exc,
                    exc_info=True,
                )

        if self.running:
            self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_apply_batch")

    # =========================================================================
    # BROWSER MANAGEMENT
    # =========================================================================

    def _requires_browser(self, task: WorkUnit) -> bool:
        """Returns True if this task type requires a live browser session.

        DISCOVER tasks may use static fetch depending on the provider.
        VET and APPLY tasks always require a live browser.

        Args:
            task: The WorkUnit being evaluated.

        Returns:
            True if a browser must be active before dispatching this task.
        """
        always_browser = {TaskType.VET, TaskType.APPLY, TaskType.HANDLE_CAPTCHA}
        if task.task_type in always_browser:
            return True

        # Discovery and company discovery may or may not need a browser.
        # Defer to the CapabilitiesRegistry to check the active page access
        # strategy for the current session.
        return self.registry.discovery_requires_live_browser()

    def _ensure_browser_active(self) -> None:
        """Raises RuntimeError if no browser driver was injected.

        Browser lifecycle is managed by the composition root. Inject an
        active BrowserInterface via the ``driver`` constructor parameter
        before processing tasks that require browser access.

        Raises:
            RuntimeError: If ``self._driver`` is None.
        """
        if self._driver is not None:
            return  # Already active.

        raise RuntimeError(
            "No browser driver is available. Provide an active BrowserInterface "
            "via the 'driver' constructor parameter before processing tasks that "
            "require browser access."
        )
 
    # =========================================================================
    # ENGINE CACHE
    # =========================================================================
 
    def _get_workflow(self, name: str) -> Any:
        """Returns the pre-built workflow instance registered under ``name``.

        Workflows are constructed and injected by ``build_orchestrator()`` in
        ``infrastructure/composition_root.py``, then stored here by name.
        Construction inside the orchestrator is intentionally prohibited — the
        orchestrator must never instantiate concrete adapters itself.

        Args:
            name: The workflow key (e.g. ``"DiscoveryWorkflow"``).

        Returns:
            The registered workflow instance.

        Raises:
            RuntimeError: If no workflow was registered under ``name``. This is a
                programming error — always call ``build_orchestrator()`` which
                pre-populates all workflows before ``run()`` is called.
        """
        workflow = self._workflows.get(name)
        if workflow is None:
            raise RuntimeError(
                f"Workflow '{name}' not found. Ensure build_orchestrator() "
                f"pre-populated orchestrator._workflows['{name}'] before run()."
            )
        return workflow
 
    # =========================================================================
    # EVENT BUS WIRING
    # =========================================================================
 
    def _register_event_handlers(self) -> None:
        """Subscribes orchestrator handlers to all events it cares about.
 
        Called once during ``__init__``. Handlers must be thread-safe — they
        may be invoked from the browser or network monitor daemon threads, not
        just the main orchestrator loop. All handlers here only set flags or
        publish follow-up events; they never mutate shared state directly.
        """
        self.event_bus.subscribe(Event.BROWSER_UNHEALTHY, self._on_browser_unhealthy)
        self.event_bus.subscribe(Event.BROWSER_DEGRADED,  self._on_browser_degraded)
        self.event_bus.subscribe(Event.BROWSER_DEAD,      self._on_browser_dead)
        self.event_bus.subscribe(Event.NETWORK_UNHEALTHY, self._on_network_unhealthy)
        self.event_bus.subscribe(Event.NETWORK_RESTORED,  self._on_network_restored)
        self.event_bus.subscribe(Event.HUMAN_APPROVAL_REQUESTED, self._on_human_approval_requested)
        self.event_bus.subscribe(Event.HUMAN_APPROVAL_GRANTED,   self._on_human_approval_granted)

        logger.debug("Orchestrator event handlers registered")
 
    # ── Event Handlers ────────────────────────────────────────────────────────
 
    def _on_browser_unhealthy(self, payload: Any) -> None:
        """Handles BROWSER_UNHEALTHY: pauses the loop for driver recovery.
 
        Called from the BrowserHealthMonitor daemon thread. Only sets the
        ``paused`` flag so the main loop can handle recovery at a safe point
        rather than mid-task.
 
        Args:
            payload: Dict from BrowserHealthMonitor (consecutive_failures, etc.)
        """
        logger.warning(
            "Browser unhealthy signal received | payload=%s — pausing loop",
            payload,
        )
        self.paused = True
        self.state_machine.transition_to(AgentState.ERROR_RECOVERY)
 
    def _on_browser_dead(self, payload: Any) -> None:
        """Handles BROWSER_DEAD: the browser is unrecoverable — shut down cleanly.

        Distinct from BROWSER_UNHEALTHY (which only pauses the loop for restart).
        BROWSER_DEAD means the monitor has already given up and stopped its own
        polling thread; the orchestrator must move to clean shutdown rather
        than waiting for a recovery that will never come.

        Called from the BrowserHealthMonitor daemon thread immediately before
        it exits. Triggers the same graceful-stop path as ``stop()``.

        Args:
            payload: Dict from BrowserHealthMonitor (consecutive_failures,
                ceiling, metrics).
        """
        logger.error(
            "Browser dead signal received | payload=%s — initiating shutdown",
            payload,
        )
        # Clear pause flag so the main loop wakes and observes self.running=False
        # on its next iteration rather than waiting indefinitely in PAUSED.
        self.paused = False
        # ERROR_RECOVERY → STOPPING is a valid transition, so route through it
        # to signal the failure mode before reaching STOPPING.
        self.state_machine.transition_to(
            AgentState.ERROR_RECOVERY, triggered_by="browser_dead"
        )
        self.stop()

    def _on_browser_degraded(self, payload: Any) -> None:
        """Handles BROWSER_DEGRADED: logs but does not interrupt the loop.
 
        Degraded means the browser is slow or unstable but still responsive.
        We log the warning and let the loop continue. If it progresses to
        BROWSER_UNHEALTHY, ``_on_browser_unhealthy`` will pause.
 
        Args:
            payload: Dict from BrowserHealthMonitor (response_time_ms, etc.)
        """
        logger.warning(
            "Browser degraded signal received | payload=%s — monitoring",
            payload,
        )
 
    def _on_network_unhealthy(self, payload: Any) -> None:
        """Handles NETWORK_UNHEALTHY: pauses the loop until reconnection.
 
        Called from the NetworkHealthMonitor daemon thread. Sets ``paused``
        so the main loop calls ``_pause_until_network_restored()`` on its
        next iteration rather than dispatching tasks while offline.
 
        Args:
            payload: Dict from NetworkHealthMonitor (last_check_time, etc.)
        """
        logger.warning(
            "Network unhealthy signal received | payload=%s — pausing loop",
            payload,
        )
        self.paused = True
 
    def _on_network_restored(self, payload: Any) -> None:
        """Handles NETWORK_RESTORED: resumes the loop after a network outage.
 
        Args:
            payload: Dict from NetworkHealthMonitor (downtime_seconds, etc.)
        """
        logger.info(
            "Network restored signal received | payload=%s — resuming",
            payload,
        )
        if self.paused:
            self.paused = False
            self.state_machine.transition_to(AgentState.RUNNING)

    def _on_human_approval_requested(self, payload: Any) -> None:
        """Handles HUMAN_APPROVAL_REQUESTED: transitions to AWAITING_HUMAN.

        Called on the agent worker thread (synchronously inside
        SessionController.request_approval, before gate.wait() blocks).
        Transitions the state machine so the UI immediately reflects the pause.

        The state machine lock is re-entrant on the same thread in CPython's
        GIL, but because StateMachine._lock is a plain threading.Lock (not
        RLock), this handler must NOT be called while the lock is held. It is
        safe here because EventBus.publish() is called before gate.wait().

        Args:
            payload: HUMAN_APPROVAL_REQUESTED payload dict.
        """
        checkpoint = payload.get("checkpoint", "")
        logger.info(
            "HITL pause | checkpoint=%s — transitioning to AWAITING_HUMAN",
            checkpoint,
        )
        self.state_machine.transition_to(
            AgentState.AWAITING_HUMAN,
            triggered_by=f"hitl:{checkpoint}",
        )

    def _on_human_approval_granted(self, payload: Any) -> None:
        """Handles HUMAN_APPROVAL_GRANTED: resumes or stops the agent.

        Called on the GUI/CLI main thread (by provide_approval), after the
        user has responded. Transitions the state machine BEFORE gate.set()
        unblocks the agent worker thread, so the agent sees the correct state
        immediately on resume.

        Decision logic:
            - choice == "stop"  → call self.stop() (sets running=False, STOPPING)
            - choice == "skip"  → restore the pre-HITL state; the engine already
              returned SKIPPED_BY_USER so the current job is abandoned cleanly
            - anything else     → restore pre-HITL state and continue

        Args:
            payload: HUMAN_APPROVAL_GRANTED payload dict
                     with keys context_id and choice.
        """
        choice = payload.get("choice", "approve")
        logger.info("HITL resumed | choice=%r", choice)

        if choice == "stop":
            self.stop()
            return

        # Restore the state that was active before the HITL pause.
        # Prefer APPLYING if that was the pre-pause state (mid-apply resume),
        # otherwise fall back to RUNNING.
        pre_hitl = self._pre_hitl_state()
        target = pre_hitl if pre_hitl is not None else AgentState.RUNNING
        self.state_machine.transition_to(target, triggered_by="hitl:granted")

    def _pre_hitl_state(self) -> "AgentState | None":
        """Returns the state the machine was in immediately before AWAITING_HUMAN.

        Walks the transition history in reverse to find the most recent record
        whose to_state is AWAITING_HUMAN and returns its from_state.

        Returns:
            The AgentState that preceded the HITL pause, or None if history
            is empty or AWAITING_HUMAN was never entered.
        """
        for record in reversed(self.state_machine.history):
            if record.to_state == AgentState.AWAITING_HUMAN:
                return record.from_state
        return None

    # =========================================================================
    # HEALTH MONITORS & WATCHDOG
    # =========================================================================
 
    def _start_health_monitors(self) -> None:
        """Starts injected health monitors and watchdog as daemon threads.

        Monitors are pre-constructed and injected by composition_root.
        This method simply starts their run() / start() loops in daemon
        threads.  If no monitors were injected, the orchestrator runs
        without health monitoring (graceful degradation for low‑resource /
        minimal environments).
        """
        for monitor, name in (
            (self._browser_monitor, "BrowserHealthMonitor"),
            (self._network_monitor, "NetworkHealthMonitor"),
        ):
            if monitor is None:
                continue
            try:
                t = threading.Thread(target=monitor.run, name=name, daemon=True)
                t.start()
                self._monitor_threads.append(t)
                logger.debug("%s started", name)
            except Exception as exc:
                logger.warning("Failed to start %s | error=%s", name, exc)

        # ── Phase 5: Provider watchdog ───────────────────────────────────
        if self._watchdog is not None:
            try:
                self._watchdog.start()
                logger.debug("ProviderWatchdog started")
            except Exception as exc:
                logger.warning("Failed to start ProviderWatchdog | error=%s", exc)
 
    # =========================================================================
    # DEDUPLICATION
    # =========================================================================
 
    def _is_duplicate_task(self, task: WorkUnit) -> bool:
        """Returns True if this task's job URL was already seen or applied.
 
        Deduplication runs at two levels:
            1. In-session: ``DeduplicationManager`` tracks URLs seen since
               this orchestrator instance started. Prevents double-processing
               when discovery results overlap across providers.
            2. Cross-session: ``JobRepositoryPort.was_applied()`` checks the
               persistent application history. Prevents re-applying to jobs
               from prior sessions after a restart.
 
        Non-job tasks (DISCOVER, HANDLE_CAPTCHA) always return False —
        deduplication only applies to tasks whose payload is a ``Job``.
 
        Args:
            task: The WorkUnit to evaluate.
 
        Returns:
            True if the task should be skipped, False if it should proceed.
        """
        job: Job | None = task.payload if isinstance(task.payload, Job) else None
        if job is None:
            return False  # Non-job task — no URL to deduplicate.
 
        url: str | None = getattr(job, "url", None)
        if not url:
            return False
 
        # 1. In-session deduplication.
        if self.dedup_manager.is_duplicate(url):
            return True
 
        # 2. Cross-session persistence check.
        try:
            if self.db.was_applied(url):
                return True
        except Exception as exc:
            # Treat DB errors as non-duplicate — better to process twice
            # than silently drop a task due to a persistence glitch.
            logger.warning(
                "Dedup DB check failed | url=%s error=%s — treating as new",
                url, exc,
            )
 
        return False
 
    # =========================================================================
    # ERROR HANDLING & RETRY
    # =========================================================================
 
    def _handle_task_error(
        self, task: WorkUnit | None, exc: Exception
    ) -> None:
        """Handles a task-level exception with retry logic.
 
        On each failure the retry counter (stored in ``task.context_data``)
        is incremented. Tasks below ``MAX_TASK_RETRIES`` are re-queued at
        reduced priority. Tasks that exhaust their retries are marked
        permanently failed and logged for telemetry.
 
        Args:
            task: The WorkUnit that failed, or None if the error occurred
                before a task was dequeued (e.g., in a health check).
            exc: The exception that was raised.
        """
        if task is None:
            logger.error(
                "Orchestrator loop error (no active task) | error=%s",
                exc,
                exc_info=True,
            )
            return
 
        context_data: dict = dict(task.context_data or {})
        retry_count: int = int(context_data.get("retry_count", 0)) + 1
 
        logger.error(
            "Task error | type=%s id=%s retry=%d/%d error=%s",
            task.task_type.name,
            task.id,
            retry_count,
            self.MAX_TASK_RETRIES,
            exc,
            exc_info=True,
        )
 
        # Mark the current task record complete so it doesn't stay stuck.
        try:
            self.task_queue.mark_task_complete(task.id, skipped=True)
        except Exception as mark_exc:
            logger.warning(
                "Could not mark failed task complete | id=%s error=%s",
                task.id, mark_exc,
            )
 
        if retry_count <= self.MAX_TASK_RETRIES:
            # Re-queue with incremented retry count and slightly lower priority
            # so healthy tasks process first.
            context_data["retry_count"] = retry_count
            retry_task = WorkUnit(
                priority=max(task.priority - 1, 0),
                task_type=task.task_type,
                payload=task.payload,
                source=f"retry:{task.source}",
                context_data=context_data,
            )
            try:
                self.task_queue.queue_task(retry_task)
                logger.info(
                    "Task re-queued | id=%s type=%s retry=%d",
                    task.id, task.task_type.name, retry_count,
                )
            except Exception as queue_exc:
                logger.error(
                    "Could not re-queue failed task | id=%s error=%s",
                    task.id, queue_exc,
                )
        else:
            logger.error(
                "Task permanently failed (retries exhausted) | id=%s type=%s",
                task.id,
                task.task_type.name,
            )
            self.context.update_stats("failed", 1)
            self.event_bus.publish(
                Event.TASK_PERMANENTLY_FAILED,
                {"task_id": task.id, "task_type": task.task_type.name, "error": str(exc)},
            )
 
    # =========================================================================
    # NETWORK PAUSE
    # =========================================================================
 
    def _pause_until_network_restored(self) -> None:
        """Blocks the orchestrator loop until network connectivity is restored.
 
        Called from the main event loop when the NetworkHealthMonitor signals
        NETWORK_UNHEALTHY. Polls ``_network_monitor.is_healthy()`` every
        five seconds up to the configured reconnect timeout, then stops the
        session if connectivity cannot be restored.
 
        If no NetworkHealthMonitor is available, returns immediately so the
        loop can attempt the task optimistically (graceful degradation for
        low-resource environments where the monitor wasn't started).
        """
        if self._network_monitor is None:
            return  # No monitor — optimistically continue.
 
        timeout_seconds: int = self.registry.get_effective_config(
            "network_reconnect_timeout_seconds", 300
        )
        poll_interval: float = 5.0
        elapsed: float = 0.0
 
        logger.warning(
            "Network unavailable — waiting for reconnect | timeout=%ds", timeout_seconds
        )
 
        while elapsed < timeout_seconds:
            time.sleep(poll_interval)
            elapsed += poll_interval
 
            if self._network_monitor.is_healthy():
                logger.info(
                    "Network reconnected after %.0f seconds — resuming", elapsed
                )
                self.state_machine.transition_to(AgentState.RUNNING)
                self.paused = False
                return
 
        # Timeout reached without reconnection.
        logger.error(
            "Network reconnect timeout reached (%ds) — stopping session", timeout_seconds
        )
        self.stop()
 
    # =========================================================================
    # CHECKPOINT RECOVERY
    # =========================================================================
 
    def _attempt_checkpoint_recovery(self) -> None:
        """Restores session progress from a prior checkpoint if one exists.
 
        Called once at the start of ``run()`` before any tasks are dispatched.
        If the previous session was interrupted (crash, power loss), this
        restores discovered/applied counts so progress reporting is accurate
        across sessions.
 
        Failure is non-fatal — if the checkpoint is corrupt or missing, the
        session starts fresh with zeroed statistics.
        """
        try:
            checkpoint = self.checkpoint_manager.load()
            if checkpoint:
                self.context.restore_from_checkpoint(checkpoint)
                logger.info(
                    "Session restored from checkpoint | "
                    "discovered=%d vetted=%d applied=%d",
                    self.context.stats.jobs_discovered,
                    self.context.stats.jobs_vetted,
                    self.context.stats.applications_submitted,
                )
            else:
                logger.debug("No prior checkpoint found — starting fresh")
        except Exception as exc:
            logger.warning(
                "Checkpoint recovery failed (starting fresh) | error=%s", exc
            )
 
    # =========================================================================
    # TEARDOWN
    # =========================================================================
 
    def _teardown(self) -> None:
        """Cleans up all resources after the event loop exits.

        Called exactly once at the end of ``run()``, whether the loop exited
        cleanly (``stop()`` called) or due to an unhandled exception. Ordering
        matters:
            0. Shutdown workflows that may still hold background threads.
            1. Transition to STOPPED state (signals all observers that the
               session has ended). Routes through STOPPING first in case an
               engine state is current.
            2. Stop health monitors and watchdog (they hold daemon thread references).
            3. Final checkpoint save (preserves progress for next session).
            4. Clear EventBus subscriptions (releases handler references).
            5. Close browser (always last — monitors need it until now).

        Errors during teardown are logged but never propagated — teardown
        must always complete.
        """
        logger.info("Beginning orchestrator teardown...")

        # ── 0. Shutdown workflow threads ─────────────────────────────────
        for wf_name in ("DiscoveryWorkflow", "ApplicationsWorkflow"):
            wf = self._workflows.get(wf_name)
            if wf is not None and hasattr(wf, "shutdown"):
                try:
                    wf.shutdown()
                except Exception as exc:
                    logger.warning("Workflow %s shutdown error: %s", wf_name, exc)

        # Attempt STOPPING first (no-op if already there or invalid), then
        # STOPPED. Both return False on invalid transitions rather than raising.
        self.state_machine.transition_to(AgentState.STOPPING, triggered_by="_teardown")
        self.state_machine.transition_to(AgentState.STOPPED, triggered_by="_teardown")
 
        # ── 1. Signal health monitors to stop ────────────────────────────
        for monitor in (self._browser_monitor, self._network_monitor):
            if monitor is not None:
                try:
                    monitor.stop()
                except Exception as exc:
                    logger.debug("Monitor stop error (non-fatal) | error=%s", exc)

        # ── 1a. Stop provider watchdog (Phase 5) ─────────────────────────
        if self._watchdog is not None:
            try:
                self._watchdog.stop()
            except Exception as exc:
                logger.debug("Watchdog stop error (non-fatal) | error=%s", exc)
 
        # ── 2. Save final checkpoint ──────────────────────────────────────
        try:
            self.checkpoint_manager.save(self.context)
            logger.debug("Final checkpoint saved")
        except Exception as exc:
            logger.warning("Final checkpoint save failed | error=%s", exc)
 
        # ── 3. Clear EventBus subscriptions ──────────────────────────────
        try:
            self.event_bus.unsubscribe_all()
        except Exception as exc:
            logger.debug("EventBus teardown error (non-fatal) | error=%s", exc)
 
        # ── 4. Close browser ──────────────────────────────────────────────
        if self._driver is not None:
            try:
                self._driver.close()
                logger.debug("Browser closed during teardown")
            except Exception as exc:
                logger.warning("Browser close error during teardown | error=%s", exc)
            self._driver = None
 
        logger.info(
            "Teardown complete | %s", self.context.stats.summary_line()
        )