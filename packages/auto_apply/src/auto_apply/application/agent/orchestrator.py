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
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from auto_apply.application.agent.context import ExecutionContext
from auto_apply.application.agent.event_bus import EventBus
from auto_apply.application.agent.state_machine import AgentState, StateMachine
from auto_apply.application.services.data_processing.checkpoint_manager import (
    CheckpointManager,
)
from auto_apply.application.services.data_processing.deduplication_manager import (
    DeduplicationManager,
)
from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.events import Event
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.resources import RuntimeProfile
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.models.timing import BehaviorParameters
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.domain.ports.repository_port import JobRepositoryPort
from auto_apply.domain.ports.work_queue_port import WorkQueuePort

from auto_apply.domain.ports.registry_port import RegistryPort

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
        - Cross-session dedup: APPLY tasks check applied_jobs before
          submitting — AA never applies to the same URL twice.
        - Provider watchdog (Phase 5): A ProviderWatchdog thread monitors
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

    # Seconds to sleep when the work queue is empty before checking again.
    IDLE_SLEEP_SECONDS: float = 2.0

    def __init__(  # noqa: PLR0913
        self,
        profile: UserProfile,
        resources: RuntimeProfile,
        registry: RegistryPort,
        task_queue: WorkQueuePort,
        db: JobRepositoryPort,
        event_bus: EventBus,
        session_plan: SessionPlan,
        driver: BrowserInterface | None = None,
        captcha_resolver: Any | None = None,
        browser_monitor: Any | None = None,
        network_monitor: Any | None = None,
        watchdog: Any | None = None,              # ← Phase 5: ProviderWatchdog
        job_posting_resolver: Any | None = None,  # ← JobPostingResolver service
        progress: Any | None = None,  # ← optional SessionProgressDisplay (CLI adapter)
        workflows: dict[str, Any] | None = None,
        behavior_parameters: BehaviorParameters | None = None,
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
            session_plan: The frozen SessionPlan assembled by the registry at
                startup. Required: execution mode and application caps are read
                from it. Promoted from a post-construction monkey-patch (P1);
                a missing plan is now a TypeError at construction, not a silent
                fail-closed at apply time.
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
        # Session identity has exactly one source: the frozen SessionPlan the
        # registry assembled at startup. Minting one here would create a second
        # identity that silently diverges from every plan-scoped record.
        self.context = ExecutionContext(
            profile=profile,
            session_id=registry.get_session_plan().session_id,
        )
        self.context.resources = resources

        self.state_machine = StateMachine(initial_state=AgentState.IDLE)
        self.running: bool = False
        self.paused: bool = False

        # ── Session report (accumulates application outcomes incrementally)
        self._session_report = SessionReport(
            session_id=self.context.session_id,
            profile_name=getattr(profile, "profile_name", "unknown"),
        )

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

        # ── Provider watchdog (Phase 5) ────────────────────────────────────
        self._watchdog: Any | None = watchdog

        # Company batching is now delegated to ApplicationsWorkflow's
        # CompanyBatchScheduler. The buffer lives there; the orchestrator
        # only calls into it via the workflow reference.

        # ── Workflow orchestrators (the live execution path) ──────────────
        # Injected by build_orchestrator() via the constructor (P1 — formerly
        # monkey-patched after construction). Each TaskType is dispatched to
        # the corresponding *Workflow.run(); see _dispatch_task / _get_workflow.
        self._workflows: dict[str, Any] = dict(workflows) if workflows else {}

        # Retained for backward compatibility with any external inspectors;
        # no longer the dispatch path (the workflows superseded the engines).
        self._engines: dict[str, Any] = {}

        # ── CLI progress display (Wave M — Session Observability) ──────────
        # Injected from composition_root.py, which is the only layer allowed
        # to import the concrete CLI adapter; the orchestrator never imports
        # adapters.primary.cli directly.
        self._progress: Any | None = progress

        # ── Job posting resolver (RESOLVE_JOB_URL) ────────────────────────
        self._job_posting_resolver: Any | None = job_posting_resolver

        # Promoted from post-construction monkey-patching (P1). session_plan
        # is required; behavior_parameters stays optional because nothing in
        # the orchestrator reads it yet (attached for future consumers).
        self.session_plan: SessionPlan = session_plan
        self.behavior_parameters: BehaviorParameters | None = behavior_parameters

        # ── HITL approval gate ────────────────────────────────────────────
        # Wired post-construction by SessionController._wire_approval_gate() —
        # the controller is built around the orchestrator, so the gate cannot
        # be a constructor dependency. When None, CAPTCHA escalation degrades
        # to record-and-continue rather than hanging (see _handle_captcha).
        self._approval_gate: Any | None = None

        # ── Redirect dedupe for the REDIRECT_TO_LIST_DETECTED handler ─────
        self._seen_redirect_urls: set = set()

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

        # ── Start the CLI progress display (Wave M), if one was injected ───
        if self._progress is not None:
            self._progress.start()

        # Obtain a reference to the batch scheduler owned by ApplicationsWorkflow.
        app_wf = self._workflows.get("ApplicationsWorkflow")
        batch_scheduler = app_wf.batch_scheduler if app_wf is not None else None

        try:
            while self.running:
                task: WorkUnit | None = None

                # ── 1. Pause handling ─────────────────────────────────────────
                if self.paused:
                    if self._progress is not None:
                        self._progress.update("PAUSED", "")
                    time.sleep(1.0)
                    continue

                try:
                    # ── 2. Batch readiness check ──────────────────────────────
                    if batch_scheduler is not None and batch_scheduler.check_batch_ready():
                        self._process_ready_batch(batch_scheduler)
                        continue

                    # ── 3. Dequeue next task ──────────────────────────────────
                    task = self.task_queue.get_next_task()

                    if not task:
                        # ── 4. Queue empty handling ───────────────────────────
                        if batch_scheduler is not None and batch_scheduler.has_any_buffered():
                            # Flush all remaining buffers regardless of size.
                            remaining = batch_scheduler.flush_all_batches()
                            for company_key, jobs in remaining.items():
                                self._process_batch(company_key, jobs, batch_scheduler)
                            continue

                        # Truly idle — nothing pending anywhere.
                        logger.debug("Work queue empty, idling...")
                        self.state_machine.transition_to(AgentState.IDLE)
                        if self._progress is not None:
                            self._progress.update("IDLE", "waiting for tasks...")
                        time.sleep(self.IDLE_SLEEP_SECONDS)
                        continue

                    # ── 4b. Round-completion batch flush (R-2) ────────────────
                    # A DISCOVER/DISCOVER_COMPANY task being dequeued means the
                    # previous round's VET and APPLY tasks have all drained —
                    # TaskPriority banding (APPLY 10-19 < VET 50 < DISCOVER 100)
                    # guarantees it. Flush the previous round's buffered
                    # applications before dispatching the next round's search.
                    if (
                        batch_scheduler is not None
                        and task.task_type in (TaskType.DISCOVER, TaskType.DISCOVER_COMPANY)
                        and batch_scheduler.has_any_buffered()
                    ):
                        self._flush_round_boundary_batches(batch_scheduler)
                    # Fall through: the dequeued task is dispatched below.

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

                    # ── Update progress display before dispatch ───────────────
                    if self._progress is not None:
                        detail = _task_detail(task)
                        self._progress.update(task.task_type.name, detail)

                    self._dispatch_task(task)

                    # ── 9. Mark complete ──────────────────────────────────────
                    self.task_queue.mark_task_complete(task.id)

                    # ── 10. Auto-checkpoint ───────────────────────────────────
                    self.checkpoint_manager.record_action_and_maybe_save(self.context)

                except Exception as exc:
                    self._handle_task_error(task, exc)

        finally:
            # ── Stop progress display ────────────────────────────────────
            if self._progress is not None:
                self._progress.stop()

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

        On failure, retryable task types (APPLY, RESOLVE_JOB_URL) are
        automatically rescheduled with exponential backoff via
        task_queue.reschedule_for_retry(). Non-retryable types are marked
        failed permanently.

        Per-task duration is logged and tracked for session observability
        (Wave M).

        Args:
            task: The WorkUnit to process.

        Raises:
            RuntimeError: If the TaskType is not recognized. This is a
                programming error, not a runtime error, and should surface
                during development, not in production.
        """
        start_time = time.monotonic()

        logger.info(
            "Dispatching | type=%-18s priority=%d id=%s",
            task.task_type.name,
            task.priority,
            task.id,
        )

        # ── Design note: why per‑TaskType handler classes are NOT warranted ──
        # Each handler below is a thin coordination method: it extracts parameters
        # from the WorkUnit, delegates to injected workflows/services (DiscoveryWorkflow,
        # VettingWorkflow, CompanyBatchScheduler, JobPostingResolver, etc.), updates
        # context stats/state, and returns. All business logic lives in those workflows/
        # services — the orchestrator's handlers contain no domain rules, no I/O, and
        # no branching logic beyond parameter extraction and basic state transitions.
        #
        # Extracting these into per‑TaskType handler classes with a shared Protocol
        # would add:
        #   - 6 new classes and a Protocol definition
        #   - Additional wiring in the composition root (or a registry)
        #   - Indirection that makes it harder to trace the execution flow from
        #     _dispatch_task to the actual work
        #   - No net gain in testability: the existing dispatch logic is already
        #     testable via the pattern demonstrated in tests/application/
        #     test_orchestrator_dispatch.py, which uses partial orchestrator instances
        #     with only the relevant attributes injected. The workflows/services
        #     themselves are testable independently.
        #
        # With 6 TaskType values and thin handlers, the current dispatch‑table‑of‑
        # private‑methods pattern is simpler, easier to maintain, and fully aligned
        # with AA's "no over‑engineering that harms reliability" principle.
        # A handler‑class split would be premature and would scatter coordination
        # logic across multiple files that are inherently coupled to the orchestrator's
        # internal state anyway.
        # ──────────────────────────────────────────────────────────────────────────

        dispatch_table = {
            TaskType.DISCOVER:         self._handle_discovery,
            TaskType.DISCOVER_COMPANY: self._handle_company_discovery,
            TaskType.RESOLVE_JOB_URL:  self._handle_url_resolution,
            TaskType.VET:              self._handle_vetting,
            TaskType.APPLY:            self._buffer_application,
            TaskType.HANDLE_CAPTCHA:   self._handle_captcha,
        }

        handler = dispatch_table.get(task.task_type)
        if handler is None:
            duration = time.monotonic() - start_time
            raise RuntimeError(
                f"Unknown TaskType '{task.task_type}' — add a handler in "
                f"_dispatch_task() and a _handle_* method."
            )

        try:
            handler(task)
            duration = time.monotonic() - start_time
            logger.debug(
                "Task complete | type=%s duration=%.1fs id=%s",
                task.task_type.name, duration, task.id[:8],
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Task failed | type=%s id=%s duration=%.1fs | %s",
                task.task_type.name, task.id[:8], duration, error_msg,
                exc_info=True,
            )

            # ── Retry logic: only certain task types are retryable ─────────
            retryable = task.task_type in {
                TaskType.APPLY,
                TaskType.RESOLVE_JOB_URL,
            }
            if retryable:
                rescheduled = self.task_queue.reschedule_for_retry(
                    task.id, error_msg,
                )
                if not rescheduled:
                    logger.warning(
                        "Task permanently failed after max retries | type=%s id=%s",
                        task.task_type.name, task.id[:8],
                    )
            else:
                # Non-retryable types: mark as permanently failed immediately
                self.task_queue.mark_task_failed(task.id, error_msg)
                logger.debug(
                    "Non-retryable task %s marked failed | id=%s",
                    task.task_type.name, task.id[:8],
                )

    # =========================================================================
    # DOMAIN ENGINE HANDLERS
    # =========================================================================

    def _get_execution_mode(self) -> SessionExecutionMode:
        """Return the active execution mode from the session plan."""
        return self.session_plan.execution_mode

    def _session_cap_reached(self) -> bool:
        """True when the per-session application cap is reached and applying must stop.

        Applications are irreversible, so this cap is a promise, not a
        preference: once the running count reaches the effective
        ``max_applications_per_session`` the orchestrator stops dispatching
        applications, even mid-batch.

        RESEARCH_AUDIT sessions are exempt. Uncapped application volume is their
        explicit, granted purpose — and the exemption is an execution *mode*
        granted by policy, never a sentinel value of the cap. A cap of 0 means
        zero applications; "unlimited" is never expressed as a magic number.
        """
        if self._get_execution_mode() == SessionExecutionMode.RESEARCH_AUDIT:
            return False
        return (
            self.context.stats.applications_submitted
            >= self.session_plan.max_applications_per_session
        )

    def _handle_discovery(self, task: WorkUnit) -> None:
        """Runs job discovery for a search query and enqueues results.

        Delegates to DiscoveryWorkflow.run(), which fans out to all active
        providers, pre-filters, deduplicates, and enqueues a VET WorkUnit per
        unique job — so this handler only builds SearchInstruction objects
        from the task payload and records the resulting count.

        Args:
            task: WorkUnit whose payload is a dict with optional keys:
                  ``title``/``query``, ``location``, ``workplace_type``,
                  ``raw_query_string``, ``date_range``.
        """
        self.state_machine.transition_to(AgentState.DISCOVERING)
        workflow = self._get_workflow("DiscoveryWorkflow")

        # Build SearchInstruction(s) from the task payload.
        payload = task.payload if isinstance(task.payload, dict) else {}
        title = payload.get("title") or payload.get("query", "")
        location = payload.get("location", "")
        workplace_type = payload.get("workplace_type", "remote")
        raw_query_string = payload.get("raw_query_string")
        date_range = payload.get("date_range")

        instructions: list[SearchInstruction] | None = None
        if title or raw_query_string:
            instructions = [SearchInstruction(
                title=title or "Custom Search",
                location=location,
                workplace_type=workplace_type,
                raw_query_string=raw_query_string,
                date_range=date_range,
            )]
        # If no title AND no raw_query_string, instructions is None →
        # workflow builds from profile (backward‑compatible with seeded
        # tasks that carry no explicit query).

        mode = self._get_execution_mode()
        enqueued: int = workflow.run(
            instructions=instructions,
            execution_mode=mode,
        )

        logger.info("Discovery complete | enqueued=%d", enqueued)
        self.context.update_stats("discovered", enqueued)
        self._session_report.raw_results_found += enqueued

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
        enqueued: int = workflow.discover_company_page(
            careers_url,
            company_name,
        )
        # (discover_company_page uses self._plan.execution_mode internally)

        logger.info(
            "Company discovery complete | company=%s enqueued=%d",
            company_name,
            enqueued,
        )
        self.context.update_stats("discovered", enqueued)
        self._session_report.raw_results_found += enqueued

        self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_handle_company_discovery")

    # ── URL Resolution (RESOLVE_JOB_URL) ─────────────────────────────────

    def _handle_url_resolution(self, task: WorkUnit) -> None:
        """Resolves a raw URL to a typed Job object, then queues VET or APPLY.

        This is the bridge between manual URL input (which produces strings)
        and the typed Job payload that VET and APPLY handlers require.
        Without this handler, direct-URL modes crash with AttributeError because
        handlers do ``job: Job = task.payload`` and call ``job.title`` on a string.

        Args:
            task: WorkUnit whose payload is a dict with keys:
                  - url (str): The job posting URL
                  - next_task (str): "VET" or "APPLY"
                  - skip_vetting (bool): Route directly to APPLY if True
        """
        # ── 1. Unpack payload ────────────────────────────────────────────────
        payload = task.payload
        if isinstance(payload, str):
            # Backward compat: if somehow a raw string arrived, treat as URL
            url = payload
            next_task_str = task.context_data.get("next_task", "APPLY")
            skip_vetting = task.context_data.get("skip_vetting", True)
        elif isinstance(payload, dict):
            url = payload.get("url", "")
            next_task_str = payload.get("next_task", "VET")
            skip_vetting = payload.get("skip_vetting", False)
        else:
            logger.warning("RESOLVE_JOB_URL task has unexpected payload type: %s", type(payload))
            return

        if not url:
            logger.warning("RESOLVE_JOB_URL task has no URL — skipping")
            return

        logger.info("Resolving URL to Job | url=%.80s", url)

        # ── 2. Build a Job object from the URL ───────────────────────────────
        if self._job_posting_resolver is not None:
            job = self._job_posting_resolver.resolve(url, driver=self._driver)
        else:
            # Graceful fallback: if resolver is not injected (should only happen
            # in legacy tests), replicate the old inline stub logic.
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "").split(".")[0].title()
            path_parts = [p.replace("-", " ").replace("_", " ")
                          for p in parsed.path.strip("/").split("/")
                          if p and not p.isdigit() and len(p) > 3]
            title_hint = path_parts[-1].title() if path_parts else "Job Opening"
            job = Job(
                title=title_hint[:200],
                company=domain[:200] or "Unknown Company",
                url=url,
                location=None,
                source="user_direct_input",
            )

        # ── 3. Determine next task and queue ─────────────────────────────────
        mode = self._get_execution_mode()
        if skip_vetting or mode == SessionExecutionMode.APPLY_ONLY:
            next_type = TaskType.APPLY
        elif not mode.includes_vetting and mode.includes_application:
            next_type = TaskType.APPLY
        elif mode.includes_vetting:
            next_type = TaskType.VET
        else:
            # fallback safest
            next_type = TaskType.VET

        self.task_queue.queue_task(
            WorkUnit(
                priority=2 if next_type == TaskType.APPLY else 3,
                task_type=next_type,
                payload=job,
                source="url_resolution",
                context_data={
                    "skip_vetting": skip_vetting,
                    "resolved_from_url": url,
                },
            )
        )

        logger.info(
            "URL resolved | queued %s task | title=%s company=%s",
            next_type.name, job.title, job.company,
        )

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

        mode = self._get_execution_mode()
        # VettingWorkflow.run() respects execution_mode internally,
        # only enqueuing APPLY tasks when mode.includes_application.
        passed: bool = workflow.run(job, execution_mode=mode)

        if passed:
            logger.info("Vetting PASSED | title=%s company=%s", job.title, job.company)
            self.context.update_stats("vetted", 1)
            self._session_report.pending_jobs_to_apply_for += 1
        else:
            logger.info("Vetting FAILED | title=%s company=%s", job.title, job.company)

        self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_handle_vetting")

    def _buffer_application(self, task: WorkUnit) -> None:
        """Adds an APPLY task to the company batch buffer via the
        CompanyBatchScheduler owned by ApplicationsWorkflow.

        Cross‑session dedup is performed by the scheduler.  If the job is a
        duplicate the scheduler rejects it; the orchestrator records a skipped
        outcome in the session report for transparency.

        Args:
            task: WorkUnit whose payload is a Job object.
        """
        job: Job = task.payload
        app_wf = self._get_workflow("ApplicationsWorkflow")
        batch_scheduler = app_wf.batch_scheduler

        if batch_scheduler.buffer_job(job):
            # Job accepted into the buffer; nothing more to record here.
            return

        # ── Scheduler rejected the job (cross‑session duplicate) ──────────
        logger.info(
            "Skipping duplicate | %s @ %s (already applied in a previous session)",
            job.title, job.company,
        )
        from auto_apply.domain.models.application_evidence import ApplicationEvidence  # noqa: PLC0415
        evidence = ApplicationEvidence(
            pre_submit_url=job.url,
            page_title_before=job.title,
            outcome="USER_SKIPPED",
            confidence=1.0,
            error_message="Duplicate — applied in a previous session",
        )
        self._session_report.record_application(job, evidence)

    def _handle_captcha(self, task: WorkUnit) -> None:
        """Handles a CAPTCHA interruption with a resolvable outcome.

        If a captcha_resolver was injected at construction, attempts automatic
        resolution first. On failure — or when no resolver is configured — the
        challenge is escalated to the human through the shared HITL approval
        channel (see _escalate_captcha_to_human). The escalation always has a
        release path: the HITL gate resumes the session on an answer, skips on
        timeout, and degrades to continue-without-pausing when no gate is
        wired. It must never leave the session in an unrecoverable pause.

        Args:
            task: WorkUnit whose payload contains CAPTCHA challenge details.
        """
        logger.warning("CAPTCHA encountered")

        if self._captcha_resolver is not None:
            self.state_machine.transition_to(AgentState.RESOLVING_CAPTCHA)
            resolved: bool = self._captcha_resolver.resolve(task.payload, driver=self._driver)

            if resolved:
                logger.info("CAPTCHA resolved automatically")
                self.state_machine.transition_to(AgentState.RUNNING)
                return

            logger.warning("Auto-resolution failed — escalating to manual solve")
            # Return the machine to RUNNING before entering the HITL gate:
            # RESOLVING_CAPTCHA → AWAITING_HUMAN is not a valid transition,
            # and RESOLVING_CAPTCHA must not be left dangling afterward.
            self.state_machine.transition_to(AgentState.RUNNING)

        self._escalate_captcha_to_human(task)

    def _escalate_captcha_to_human(self, task: WorkUnit) -> None:
        """Escalates a CAPTCHA to the human through the shared HITL channel.

        Publishes CAPTCHA_REQUIRES_MANUAL_SOLVE as the distinct evidence record
        (consumed by the orchestrator's own recorder handler, so CAPTCHA
        encounter/escalation stays distinguishable from generic approvals in
        the research record), then blocks on the HITL approval gate until the
        user answers or the gate times out.

        The pause and its release are owned by ONE channel — HITL — rather
        than by an unrecoverable pause(). If no gate is wired (no
        SessionController), the escalation is recorded and the session
        continues without pausing: a pause nothing can release is always wrong.

        Args:
            task: The HANDLE_CAPTCHA WorkUnit being escalated.
        """
        payload = task.payload if isinstance(task.payload, dict) else {}
        url = payload.get("challenge_url") or payload.get("url") or ""
        challenge_type = payload.get("challenge_type") or payload.get("type") or "unknown"

        self.event_bus.publish(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE, {
            "url": url,
            "captcha_type": challenge_type,
            "task_id": task.id,
        })

        if self._approval_gate is None:
            logger.warning(
                "No HITL gate is wired — cannot prompt for a manual solve. "
                "CAPTCHA recorded; session continues without pausing."
            )
            return

        logger.info(
            "Escalating CAPTCHA to the human | type=%s url=%s",
            challenge_type,
            url[:80],
        )
        try:
            choice = self._approval_gate(
                "A CAPTCHA is blocking the current page. Solve it in the "
                "browser window, then choose how to continue.",
                ["solved", "skip", "stop"],
                checkpoint="CAPTCHA_REQUIRES_MANUAL_SOLVE",
            )
        except Exception as exc:
            logger.error(
                "HITL gate raised during CAPTCHA escalation | %s — "
                "recording and continuing without an answer",
                exc,
                exc_info=True,
            )
            return

        # The HITL release path (HUMAN_APPROVAL_GRANTED via provide_approval)
        # has already restored the pre-HITL state and called stop() on "stop".
        if self.state_machine.current_state == AgentState.AWAITING_HUMAN:
            # Timeout path: the gate returned without a grant, so nothing has
            # transitioned the state machine back. Resume explicitly — a stall
            # in AWAITING_HUMAN would be the same defect as the old hang.
            self.state_machine.transition_to(
                AgentState.RUNNING, triggered_by="captcha_gate_timeout"
            )

        if choice == "solved":
            logger.info("User reports CAPTCHA solved — session resumed")
        elif choice == "skip":
            logger.info("CAPTCHA task skipped (user choice or gate timeout)")
        # choice == "stop": stop() was already invoked by
        # _on_human_approval_granted; the loop will exit on the next iteration.

    # =========================================================================
    # BATCH PROCESSING (orchestrator loop helpers)
    # =========================================================================

    def _process_ready_batch(self, batch_scheduler) -> None:
        """Pops and processes the largest ready company batch."""
        company_key, jobs = batch_scheduler.pop_best_ready_batch()
        self._process_batch(company_key, jobs, batch_scheduler)

    def _flush_round_boundary_batches(self, batch_scheduler) -> None:
        """Drain every buffered application batch at a Discovery round boundary.

        This is the R-2 ruling's flush: applications drain once per completed
        Discovery round instead of only when the work queue empties. Called
        from run() when a DISCOVER or DISCOVER_COMPANY task is dequeued with
        a non-empty buffer. The final round is still drained by the existing
        queue-empty flush, so every round is covered exactly once.

        Design notes (recorded per the ruling, so the next reader does not
        "clean this up"):

        - The >=3 per-company threshold (check_batch_ready) essentially never
          fires on SERP discovery, which yields ~1 job per company. The
          scheduler is retained deliberately for DISCOVER_COMPANY: a careers
          page yields many openings for ONE company, where per-company caps
          and batching pay off. On SERP rounds, this flush is the only drain.
        - A timer-based flush was rejected: it tunes to average run length
          and is non-deterministic. Round completion is an event AA already
          knows with certainty via the task-priority banding.
        - Static (no-browser) mode is safe by construction: the capability
          profile blocks APPLY tasks from being queued without a driver, so
          the buffer is provably empty and the flush never runs there.
        - Recorded, not fixed here: the scheduler's threshold reads
          ``applications.batch_threshold`` via _cfg, which never resolves —
          the YAML knob is top-level ``company_batch_threshold``. That config
          drift belongs to the red-pin/config stage, not this one.
        """
        remaining = batch_scheduler.flush_all_batches()
        logger.info(
            "Discovery round boundary — flushing %d buffered application "
            "batch(es) from the previous round",
            len(remaining),
        )
        for company_key, jobs in remaining.items():
            self._process_batch(company_key, jobs, batch_scheduler)

    def _process_batch(self, company_key: str, jobs: list[Job], batch_scheduler) -> None:
        """Executes all applications for a single company batch.

        Tracks per-job timing for session observability (Wave M).

        Args:
            company_key: Normalized company name used as the buffer key.
            jobs: The list of Job objects to apply to.
            batch_scheduler: The CompanyBatchScheduler (for cross‑session dedup).
        """
        self.state_machine.transition_to(AgentState.APPLYING)
        workflow = self._get_workflow("ApplicationsWorkflow")

        # ── Session application cap (batch level) ────────────────────────────
        # Once the session cap is reached, no further batches are applied.
        if self._session_cap_reached():
            logger.info(
                "Session application cap reached (%d/%d) — skipping batch | company=%s",
                self.context.stats.applications_submitted,
                self.session_plan.max_applications_per_session,
                company_key,
            )
            return

        logger.info(
            "Applying batch | company=%s count=%d", company_key, len(jobs)
        )

        for job in jobs:
            # Abort remaining jobs if the session was stopped mid-batch.
            if not self.running:
                logger.info("Session stopped mid-batch, aborting remaining jobs")
                break

            # ── Session application cap (per-job) ────────────────────────────
            # Applications are irreversible; stop the moment the cap is hit,
            # even in the middle of a company batch.
            if self._session_cap_reached():
                logger.info(
                    "Session application cap reached (%d/%d) — stopping applications",
                    self.context.stats.applications_submitted,
                    self.session_plan.max_applications_per_session,
                )
                break

            # ── Cross-session deduplication: never re-apply to a known URL ────
            if batch_scheduler.is_duplicate(job.url):
                logger.debug(
                    "Already applied in prior session, skipping | url=%s",
                    job.url,
                )
                continue

            # ── Track per-application timing (Wave M) ────────────────────────
            app_start = time.monotonic()
            app_started_at = datetime.now(timezone.utc).isoformat()

            # ── Update progress display ─────────────────────────────────────
            if self._progress is not None:
                self._progress.update(
                    "APPLY",
                    f"{job.title[:25]} @ {job.company[:20]}",
                )

            try:
                # ApplicationsWorkflow returns ApplicationEvidence (truthiness
                # delegates to is_likely_success, so `if evidence:` still works).
                evidence = workflow.run(job=job, session_id=self.context.session_id)

                # ── Persist to permanent application log ──────────────────
                try:
                    self.task_queue.record_application_permanently(
                        job_url=job.url,
                        company=job.company,
                        outcome=evidence.outcome,
                        session_id=self.context.session_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to persist application to permanent log | url=%s error=%s",
                        job.url, exc,
                    )

                # ── Record the structured evidence with timing ─────────────
                app_duration = time.monotonic() - app_start
                self._session_report.record_application(
                    job,
                    evidence,
                    started_at=app_started_at,
                    duration_seconds=app_duration,
                )

                if evidence.is_likely_success:
                    self.context.update_stats("applied", 1)
                    logger.debug(
                        "Application timing | job=%s duration=%.1fs",
                        job.title, app_duration,
                    )
                else:
                    self.context.update_stats("failed", 1)

                # ── Rich emoji log (A2) — single INFO-level line per application
                status_emoji = (
                    "\u2705" if evidence.is_likely_success
                    else "\u26a0\ufe0f" if evidence.is_blocked
                    else "\u274c"
                )
                logger.info(
                    "%s Application | %s @ %s | %s (%.1fs)",
                    status_emoji,
                    job.title,
                    job.company,
                    evidence.to_log_string(),
                    app_duration,
                )

            except Exception as exc:
                app_duration = time.monotonic() - app_start
                self.context.update_stats("failed", 1)
                logger.error(
                    "Application exception | title=%s duration=%.1fs error=%s",
                    job.title, app_duration, exc,
                    exc_info=True,
                )

        if self.running:
            self.state_machine.transition_to(AgentState.RUNNING, triggered_by="_process_batch")

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

    def set_approval_gate(self, gate) -> None:
        """Late-binds the HITL approval gate.

        The gate is owned by SessionController and cannot be injected at
        construction time (the controller is built around the orchestrator).
        SessionController calls this during _wire_approval_gate() to give the
        orchestrator the same release channel the ApplicationsWorkflow uses.

        Args:
            gate: An approval callable with signature
                (question: str, options: list[str], checkpoint: str,
                timeout: float) -> str.
        """
        self._approval_gate = gate

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
        self.event_bus.subscribe(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE, self._on_captcha_manual_solve_requested)
        self.event_bus.subscribe(Event.PROVIDER_TIMED_OUT, self._on_provider_timed_out)
        self.event_bus.subscribe(Event.REDIRECT_TO_LIST_DETECTED, self._on_redirect_to_list_detected)

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

    def _on_captcha_manual_solve_requested(self, payload: Any) -> None:
        """Records a manual-solve escalation as session evidence.

        Consumer for CAPTCHA_REQUIRES_MANUAL_SOLVE. It deliberately does NOT
        pause or prompt: the pause is owned by the HITL gate so there is
        exactly one release path. This handler keeps CAPTCHA escalations a
        distinct record from generic approvals — encounter/escalation rate is
        a detection signal, not an approval metric.

        Args:
            payload: Dict from _escalate_captcha_to_human with keys
                ``url``, ``captcha_type``, ``task_id``.
        """
        payload = payload or {}
        self.context.update_stats("captcha_escalated", 1)
        logger.warning(
            "Manual CAPTCHA solve required | type=%s url=%s",
            payload.get("captcha_type", "unknown"),
            payload.get("url", ""),
        )

    def _on_provider_timed_out(self, payload: Any) -> None:
        """Handles a watchdog-reported stuck provider worker.

        Consumer for PROVIDER_TIMED_OUT. Records the timeout as session
        evidence and attempts recovery: when the stuck worker is the task the
        loop is currently dispatching, it is rescheduled for retry so the
        session does not silently lose the work. When the stuck worker cannot
        be mapped to a task, the timeout is recorded only — fabricating a
        re-queue would be worse.

        Args:
            payload: Dict from ProviderWatchdog with keys ``worker_id``,
                ``provider_name``, ``last_action``.
        """
        payload = payload or {}
        worker_id = payload.get("worker_id", "")
        provider_name = payload.get("provider_name", "unknown")
        last_action = payload.get("last_action", "")

        logger.error(
            "Provider timed out | worker=%s provider=%s last_action=%s",
            worker_id,
            provider_name,
            last_action,
        )
        self.context.update_stats("provider_timeout", 1)

        current = self.context.current_work_unit
        if current is not None and current.id == worker_id:
            error_msg = (
                f"provider '{provider_name}' timed out during '{last_action}'"
            )
            rescheduled = self.task_queue.reschedule_for_retry(
                current.id, error_msg
            )
            if rescheduled:
                logger.info(
                    "Stuck task rescheduled for retry | id=%s", current.id[:8]
                )
            else:
                logger.error(
                    "Stuck task permanently failed (retry budget exhausted) | id=%s",
                    current.id[:8],
                )

    def _on_redirect_to_list_detected(self, payload: Any) -> None:
        """Handles an application redirect to a job-listing page.

        Consumer for REDIRECT_TO_LIST_DETECTED. Enqueues a DISCOVER_COMPANY
        WorkUnit for the listing URL so the jobs on it flow through the normal
        discover → vet → apply pipeline, per the Event docstring, instead of
        retrying the application that redirected. The same URL is not enqueued
        twice in one session.

        Args:
            payload: Dict from ApplicationsWorkflow with keys ``url`` and
                ``job_title``.
        """
        payload = payload or {}
        url = payload.get("url", "")
        if not url:
            logger.warning(
                "RedirectToListDetected payload had no URL — nothing to enqueue"
            )
            return

        if url in self._seen_redirect_urls:
            logger.debug(
                "Redirect URL already enqueued this session | url=%s", url[:80]
            )
            return
        self._seen_redirect_urls.add(url)

        company_name = payload.get("company_name") or payload.get("job_title") or "Unknown"
        logger.info(
            "Redirect to job list detected — enqueueing company discovery | url=%s",
            url[:80],
        )
        self.task_queue.queue_task(
            WorkUnit(
                priority=4,
                task_type=TaskType.DISCOVER_COMPANY,
                payload={"careers_url": url, "company_name": company_name},
                source="redirect_to_list",
            )
        )

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

        # ── Phase 5: Provider watchdog ───────────────────────────────────
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
            2. Cross-session: ``task_queue.has_applied_previously()`` checks
               the persistent ``applied_jobs`` table. Prevents re-applying to
               jobs from prior sessions after a restart.

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

        # 2. Cross-session persistence check via the permanent applied_jobs table.
        try:
            if self.task_queue.has_applied_previously(url):
                return True
        except Exception as exc:
            # Treat DB errors as non-duplicate — better to process twice
            # than silently drop a task due to a persistence glitch.
            logger.warning(
                "Dedup DB check (has_applied_previously) failed | url=%s error=%s — treating as new",
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

        # ── 1a. Stop provider watchdog (Phase 5) ─────────────────────────
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

        # ── 5. Finalize and save session report ───────────────────────────
        try:
            self._session_report.finalize(
                duration_seconds=self.context.elapsed_seconds()
            )
            reports_dir = USER_DATA_DIR / "reports"
            report_path = self._session_report.save(reports_dir)
            logger.info("Session report saved | path=%s", report_path)
        except Exception as exc:
            logger.warning(
                "Session report save failed (non-fatal) | error=%s", exc
            )

        logger.info(
            "Teardown complete | %s", self.context.stats.summary_line()
        )


def _task_detail(task: WorkUnit) -> str:
    """Extract a short human-readable detail string from a WorkUnit payload."""
    try:
        if hasattr(task.payload, "title") and hasattr(task.payload, "company"):
            return f"{task.payload.title[:25]} @ {task.payload.company[:20]}"
        if isinstance(task.payload, dict):
            # Show the first value that looks like a job title or URL
            for key in ("query", "title", "url", "careers_url"):
                val = task.payload.get(key, "")
                if val:
                    return str(val)[:50]
        return ""
    except Exception:
        return ""
