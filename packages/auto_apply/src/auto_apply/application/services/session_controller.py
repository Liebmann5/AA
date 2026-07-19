"""Manages the active session lifecycle and Zero-Trust boot sequence.

This module acts as the sole bridge between the UI layer (GUI or CLI) and
the agent backend. It strictly enforces the Three-Tier Configuration
Hierarchy via CapabilitiesRegistry before the Orchestrator is allowed to
launch, translates UI wizard output into WorkUnits, and exposes a clean
polling API for dashboard updates.

Architecture Contract:
    The SessionController is the ONLY object the UI touches. It provides:
        - from_profile()       → Construction from a loaded UserProfile.  *REMOVED*
        - initialize_session() → Translates wizard config into WorkUnits.
        - start()              → Spawns the orchestrator in a background thread.
        - stop()               → Signals graceful shutdown and joins the thread.
        - get_stats()          → Thread-safe snapshot of session statistics.
        - get_current_state()  → Current AgentState name as a string.
        - is_running           → Whether the orchestrator loop is active.

    The UI never imports AgentOrchestrator, DatabaseManager, or any engine
    directly. All backend access flows through this controller.

Threading Model:
    The orchestrator runs in a daemon thread. The UI polls get_stats() and
    get_current_state() from the main thread (via Tkinter after() for GUI,
    or a sleep loop for CLI). These methods are thread-safe by design:
    stats are protected by a lock in ExecutionContext, and state_machine
    reads are atomic enum assignments.

    SessionController.from_profile() eliminated; construction is now the
    sole responsibility of the composition root (infrastructure/composition_root.py).
    The controller itself no longer imports from infrastructure.

Example:
    >>> from auto_apply.infrastructure.composition_root import build_session_controller
    >>> from auto_apply.domain.models.profile import UserProfile
    >>>
    >>> profile = repo.load_profile("my_profile")
    >>> controller = build_session_controller(profile)
    >>> task_count = controller.initialize_session({
    ...     "mode": "discovery",
    ...     "input": "Python Developer, Data Engineer",
    ... })
    >>> controller.start()
    >>> # ... poll controller.get_stats() from UI ...
    >>> controller.stop()
"""

import logging
import threading
import uuid
from typing import Any
from pathlib import Path

from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.registry_port import RegistryPort
from auto_apply.domain.ports.work_queue_port import WorkQueuePort

logger = logging.getLogger(__name__)


class SessionController:
    """Controls the secure execution lifecycle of the automation agent.

    This is the single entry point for the UI layer. It manages:
        1. Zero-Trust boot (CapabilitiesRegistry construction).
        2. Work queue seeding from wizard configuration.
        3. Orchestrator thread lifecycle (start/stop/poll).
        4. Crash recovery (interrupted task reset on startup).
        5. Network health pre-check before seeding tasks (Wave J3).

    The controller is stateful — one instance per session. When the session
    ends, discard the controller and create a new one for the next session.

    Attributes:
        registry: A RegistryPort (CapabilitiesRegistry) for this session.
        orchestrator: The AgentOrchestrator managing task dispatch.
        is_running: True while the orchestrator thread is alive.
    """

    def __init__(
        self,
        registry: RegistryPort,
        db: WorkQueuePort,
        orchestrator: AgentOrchestrator,
    ) -> None:
        """Stores pre-built dependencies.

        Direct construction is discouraged. Use build_session_controller()
        in infrastructure/composition_root.py which wires everything correctly.

        Args:
            registry: A RegistryPort — the fully resolved session config.
            db: The WorkQueuePort for task queue operations.
            orchestrator: The AgentOrchestrator, ready to run.
        """
        self.registry = registry
        self.db = db
        self.orchestrator = orchestrator
        self._agent_thread: threading.Thread | None = None
        # HITL: maps context_id → (gate_event, chosen_value_holder)
        self._pending_approvals: dict[
            str, tuple[threading.Event, list[str]]
        ] = {}
        self._approvals_lock = threading.Lock()

        logger.info("SessionController initialized")

    # =========================================================================
    # CONSTRUCTION
    # =========================================================================

    # The from_profile classmethod has been DELETED.  Construction is now
    # centralized in infrastructure/composition_root.py ← the Composition Root.

    # =========================================================================
    # NETWORK HEALTH PRE-CHECK (Wave J3)
    # =========================================================================

    def _check_network_connectivity(self) -> bool:
        """Quick connectivity check before seeding tasks.

        Tries to reach known stable endpoints. Logs a warning if unreachable
        but does not block the session (static mode works offline).

        Returns:
            True if at least one test URL is reachable.
        """
        import urllib.request

        test_urls = [
            "https://www.google.com",
            "https://httpbin.org/status/200",
            "https://www.bing.com",
        ]
        for url in test_urls:
            try:
                req = urllib.request.Request(
                    url,
                    method="HEAD",
                    headers={
                        "User-Agent": "connectivity-check/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
                logger.debug(
                    "Network check: connectivity OK via %s", url
                )
                return True
            except Exception:
                continue

        logger.warning(
            "Network check: cannot reach internet. "
            "Discovery will likely fail. "
            "Static mode may still work for local data operations."
        )
        return False

    # =========================================================================
    # SESSION INITIALIZATION (translates wizard config → WorkUnits)
    # =========================================================================

    def initialize_session(self, ui_config: dict[str, Any]) -> int:
        """Translates UI wizard configuration into queued WorkUnits.

        The registry is immutable after boot. This method does NOT modify
        any configuration — it only creates WorkUnits in the database queue.

        Before seeding any tasks:
            1. Network connectivity is checked (Wave J3).
            2. The active profile is validated for completeness.

        Supported modes:
            - "discovery": Comma-separated keywords to search for jobs.
            - "direct":    Newline-separated job URLs to apply to directly.
            - "vet":       Newline-separated job URLs to vet before applying.
            - "company":   Newline-separated company careers page URLs.

        Args:
            ui_config: Dictionary from the wizard. Expected keys:
                - "mode" (str): One of "discovery", "direct", "vet", "company".
                - "input" (str): The raw user input (keywords or URLs).

        Returns:
            The number of tasks queued.

        Raises:
            ValueError: If the mode is not recognized, or if the profile
                fails completeness validation (see
                :func:`auto_apply.application.services.profile_validator.validate_profile`).
        """
        # ── Network health pre-check (Wave J3) ──────────────────────────
        is_online = self._check_network_connectivity()
        if not is_online:
            # Check if the capability profile has a live browser — if so,
            # discovery will definitely fail. Warn the user.
            profile = self.registry.get_active_profile()
            if profile is not None:
                print(  # noqa: T201 — intentional user-facing CLI output
                    "\n  \u26a0\ufe0f  Warning: Cannot reach the internet.\n"
                    "     Job discovery requires internet access.\n"
                    "     Check your connection and try again, or use static mode.\n"
                )

        # ── Profile completeness check ─────────────────────────────────────
        try:
            from auto_apply.application.services.profile_validator import (
                validate_profile,
            )

            profile = self.registry.get_active_profile()
            if profile is not None:
                mode = ui_config.get("mode", "discovery")
                validation = validate_profile(profile, mode=mode)

                if (
                    validation.warnings
                    or validation.errors
                    or validation.missing_for_gpt4all
                ):
                    print(  # noqa: T201 — intentional user-facing CLI output
                        "\n  Profile Check:"
                    )
                    print(validation.format_for_cli())  # noqa: T201
                    print()  # noqa: T201

                if not validation.is_valid:
                    raise ValueError(
                        "Profile validation failed. Fix the issues above "
                        "before starting a session.\n"
                        f"Errors: {'; '.join(validation.errors)}"
                    )
        except ImportError:
            # profile_validator module not available — skip validation
            # (graceful degradation for worst-case environments)
            pass
        except ValueError:
            raise
        except Exception as exc:
            logger.warning(
                "Profile validation skipped due to unexpected error: %s", exc
            )

        # ── Existing task seeding ────────────────────────────────────────
        mode = ui_config.get("mode", "discovery")
        raw_input = ui_config.get("input", "")

        dispatch = {
            "discovery": self._seed_discovery_tasks,
            "direct": self._seed_direct_apply_tasks,
            "vet": self._seed_vet_tasks,
            "company": self._seed_company_tasks,
        }

        handler = dispatch.get(mode)
        if handler is None:
            raise ValueError(
                f"Unknown session mode '{mode}'. "
                f"Expected one of: {', '.join(dispatch.keys())}."
            )

        task_count = handler(raw_input)

        logger.info(
            "Session initialized | mode=%s tasks_queued=%d",
            mode,
            task_count,
        )
        return task_count

    def _seed_discovery_tasks(self, raw_input: str) -> int:
        """Creates DISCOVER tasks from comma-separated keywords.

        Each keyword becomes a separate discovery task. Location is pulled
        from the user profile's search preferences.

        Args:
            raw_input: Comma-separated job titles or keywords.

        Returns:
            Number of tasks queued.
        """
        # ── 1. Resolve titles from input or profile ────────────────────────
        titles: list[str] = [t.strip() for t in raw_input.split(",") if t.strip()]
        if not titles:
            profile = self.registry.get_active_profile()
            search_prefs = getattr(profile, "search_preferences", None)
            if search_prefs and hasattr(search_prefs, "desired_job_titles"):
                titles = list(search_prefs.desired_job_titles or [])
        if not titles:
            return 0

        # ── 2. Resolve locations from profile or fallback ──────────────────
        profile = self.registry.get_active_profile()
        search_prefs = getattr(profile, "search_preferences", None)
        locations: list[str] = getattr(search_prefs, "preferred_locations", []) or []
        if not locations:
            locations = ["Remote"]

        # ── 3. Seed one WorkUnit per (title, location) pair ────────────────
        count = 0
        for title in titles:
            for location in locations:
                task = WorkUnit(
                    priority=5,
                    task_type=TaskType.DISCOVER,
                    payload={"query": title, "location": location},
                    source="user_discovery_input",
                    context_data={"title": title, "location": location},
                )
                self.db.queue_task(task)
                count += 1
        return count

    def _seed_direct_apply_tasks(self, raw_input: str) -> int:
        """Creates RESOLVE_JOB_URL tasks from newline-separated URLs.

        Direct-apply URLs flow through RESOLVE_JOB_URL first so the
        orchestrator can navigate to the URL, extract a proper Job object,
        and then queue the APPLY task.  This prevents the AttributeError
        that occurs when _buffer_application receives a raw string.

        Args:
            raw_input: Newline-separated job application URLs.

        Returns:
            Number of tasks queued.
        """
        links = self._parse_links(raw_input)
        count = 0

        for link in links:
            task = WorkUnit(
                priority=1,
                task_type=TaskType.RESOLVE_JOB_URL,
                payload={
                    "url": link,
                    "next_task": "APPLY",
                    "skip_vetting": True,
                },
                source="user_direct_input",
                context_data={"skip_vetting": True},
            )
            self.db.queue_task(task)
            count += 1

        logger.info(
            "Queued %d direct-apply tasks (via URL resolution)", count
        )
        return count

    def _seed_vet_tasks(self, raw_input: str) -> int:
        """Creates RESOLVE_JOB_URL tasks from newline-separated URLs.

        These jobs will go through URL resolution first, then vetting.
        If they pass, they become APPLY tasks automatically via the orchestrator.

        Args:
            raw_input: Newline-separated job listing URLs.

        Returns:
            Number of tasks queued.
        """
        links = self._parse_links(raw_input)
        count = 0

        for link in links:
            task = WorkUnit(
                priority=3,
                task_type=TaskType.RESOLVE_JOB_URL,
                payload={
                    "url": link,
                    "next_task": "VET",
                    "skip_vetting": False,
                },
                source="user_vet_input",
            )
            self.db.queue_task(task)
            count += 1

        logger.info("Queued %d vet tasks (via URL resolution)", count)
        return count

    def _seed_company_tasks(self, raw_input: str) -> int:
        """Creates DISCOVER_COMPANY tasks from newline-separated URLs.

        Each URL is a company's careers/jobs page. The discovery engine
        will scrape it for individual job listings, which then flow through
        the normal vetting → application pipeline.

        Args:
            raw_input: Newline-separated company careers page URLs.

        Returns:
            Number of tasks queued.
        """
        links = self._parse_links(raw_input)
        count = 0

        for link in links:
            task = WorkUnit(
                priority=4,
                task_type=TaskType.DISCOVER_COMPANY,
                payload={
                    "careers_url": link,
                    "company_name": "Unknown",
                },
                source="user_company_input",
            )
            self.db.queue_task(task)
            count += 1

        logger.info("Queued %d company discovery tasks", count)
        return count

    # =========================================================================
    # EXECUTION CONTROL
    # =========================================================================

    def start(self) -> None:
        """Spawns the orchestrator in a non-blocking background thread.

        The orchestrator's run() method blocks until stop() is called or
        all work completes. This method returns immediately.

        Calling start() when the orchestrator is already running is safe
        (it logs a warning and returns).
        """
        if self._agent_thread and self._agent_thread.is_alive():
            logger.warning(
                "Agent is already running — ignoring duplicate start()"
            )
            return

        logger.info("Spawning Agent Orchestrator thread...")
        self._agent_thread = threading.Thread(
            target=self.orchestrator.run,
            name="AgentWorker",
            daemon=True,
        )
        self._agent_thread.start()

    def stop(self) -> None:
        """Signals the orchestrator to halt gracefully and waits for it.

        The orchestrator finishes its current task before stopping. This
        method blocks for up to 10 seconds waiting for the thread to exit.
        If the thread doesn't exit in time, it is abandoned (daemon thread
        will die with the process).
        """
        logger.info("Stop signal received")
        self.orchestrator.stop()

        if self._agent_thread and self._agent_thread.is_alive():
            self._agent_thread.join(timeout=10.0)
            if self._agent_thread.is_alive():
                logger.warning(
                    "Orchestrator thread did not exit within 10s — "
                    "it will be killed when the process exits"
                )

    def pause(self) -> None:
        """Pauses the orchestrator without killing the browser session."""
        self.orchestrator.pause()

    def resume(self) -> None:
        """Resumes the orchestrator after a pause."""
        self.orchestrator.resume()

    # =========================================================================
    # STATUS POLLING (called from UI thread — must be thread-safe)
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Returns a thread-safe snapshot of session statistics.

        Safe to call from any thread (Tkinter main thread, CLI poll loop).
        Delegates to the SessionReport attached to the orchestrator, which
        accumulates application records incrementally during the session.

        Returns:
            Dict with keys: jobs_found, jobs_vetted, jobs_passed_vetting,
            applications_attempted, applications_submitted, applications_failed,
            session_duration_seconds, submitted_job_urls, submitted_companies,
            success_rate, and backward-compatible keys (jobs_discovered,
            duration_str, report_path).
        """
        return self.orchestrator._session_report.get_stats()

    def get_current_state(self) -> str:
        """Returns the current agent state as a string.

        Safe to call from any thread. Enum reads are atomic in CPython.

        Returns:
            The AgentState name, e.g. "RUNNING", "DISCOVERING", "IDLE".
        """
        return self.orchestrator.state_machine.current_state.name

    @property
    def is_running(self) -> bool:
        """Returns True if the orchestrator thread is alive."""
        if self._agent_thread is None:
            return False
        return self._agent_thread.is_alive()

    def get_queue_stats(self) -> dict[str, int]:
        """Returns work queue status counts from the database.

        Returns:
            Dict with keys: pending, in_progress, completed, failed, skipped.
        """
        return self.db.get_queue_stats()

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _resolve_default_location(self) -> str:
        """Resolves the user's preferred default location from the profile.

        Returns:
            The first preferred location, or "Remote" if none configured.
        """
        profile = self.registry.get_active_profile()
        search_prefs = getattr(profile, "search_preferences", None)
        if search_prefs and hasattr(search_prefs, "preferred_locations"):
            locations = search_prefs.preferred_locations
            if locations:
                return locations[0]
        return "Remote"

    @staticmethod
    def _parse_links(raw_input: str) -> list[str]:
        """Parses newline-separated URLs, stripping whitespace and blanks.

        Args:
            raw_input: Raw text from the wizard input field.

        Returns:
            A cleaned list of non-empty URLs.
        """
        return [
            link.strip()
            for link in raw_input.split("\n")
            if link.strip()
        ]

    # =========================================================================
    # HUMAN-IN-THE-LOOP APPROVAL GATE
    # =========================================================================

    def request_approval(
        self,
        question: str,
        options: list[str],
        checkpoint: str = "BEFORE_FORM_SUBMIT",
        timeout: float = 300.0,
    ) -> str:
        """Publishes HUMAN_APPROVAL_REQUESTED and blocks until the user responds.

        Called from the agent worker thread. Blocks for up to *timeout* seconds.
        If the timeout elapses without a response, returns ``"skip"`` so the
        engine can continue rather than hanging indefinitely.

        Args:
            question: Human-readable description of what needs approval.
            options: List of valid choices; the UI presents these as buttons or
                a numbered list. ``"skip"`` is appended automatically if absent.
            checkpoint: Checkpoint name for the payload (informational).
            timeout: Seconds to wait for a response (default 300 = 5 minutes).

        Returns:
            The option string chosen by the user, or ``"skip"`` on timeout.
        """
        from auto_apply.domain.events import Event  # noqa: PLC0415

        if "skip" not in options:
            options = list(options) + ["skip"]

        context_id = str(uuid.uuid4())
        gate = threading.Event()
        choice_holder: list[str] = (
            []
        )  # mutable container so the grant side can write

        with self._approvals_lock:
            self._pending_approvals[context_id] = (gate, choice_holder)

        payload = {
            "context_id": context_id,
            "checkpoint": checkpoint,
            "question": question,
            "options": options,
        }

        try:
            self.orchestrator.event_bus.publish(
                Event.HUMAN_APPROVAL_REQUESTED, payload
            )
        except Exception as exc:
            logger.warning(
                "SessionController: could not publish HITL event | %s", exc
            )

        logger.info(
            "SessionController: HITL gate open | context_id=%s question=%r",
            context_id,
            question,
        )
        responded = gate.wait(timeout=timeout)

        with self._approvals_lock:
            self._pending_approvals.pop(context_id, None)

        if not responded:
            logger.warning(
                "SessionController: HITL timeout after %.0fs | "
                "context_id=%s — skipping",
                timeout,
                context_id,
            )
            return "skip"

        choice = choice_holder[0] if choice_holder else "skip"
        logger.info(
            "SessionController: HITL gate closed | context_id=%s choice=%r",
            context_id,
            choice,
        )
        return choice

    def provide_approval(self, context_id: str, choice: str) -> bool:
        """Called from the UI thread to resolve a pending HITL gate.

        Args:
            context_id: The UUID from the HUMAN_APPROVAL_REQUESTED payload.
            choice: The option the user selected.

        Returns:
            True if the gate was found and unblocked. False if context_id
            is unknown (already timed out, duplicate call, etc.).
        """
        from auto_apply.domain.events import Event  # noqa: PLC0415

        with self._approvals_lock:
            entry = self._pending_approvals.get(context_id)

        if entry is None:
            logger.warning(
                "SessionController.provide_approval: unknown context_id=%s",
                context_id,
            )
            return False

        gate, choice_holder = entry

        # Publish GRANTED first so orchestrator transitions state machine to
        # RUNNING (or STOPPING) BEFORE the agent thread unblocks and resumes.
        # EventBus delivers synchronously so the transition completes before
        # gate.set() is called.
        try:
            self.orchestrator.event_bus.publish(
                Event.HUMAN_APPROVAL_GRANTED,
                {"context_id": context_id, "choice": choice},
            )
        except Exception as exc:
            logger.warning(
                "SessionController: could not publish HITL granted event | %s",
                exc,
            )

        choice_holder.append(choice)
        gate.set()

        return True

    def _wire_approval_gate(self) -> None:
        """Late-binds request_approval into the ApplicationsWorkflow.

        Called after controller construction to resolve the circular dependency:
        the workflow is built before SessionController exists, so the gate
        cannot be passed at construction time.  This method is called by the
        composition root during controller assembly.
        """
        try:
            workflows = getattr(self.orchestrator, "_workflows", {})
            app_workflow = workflows.get("ApplicationsWorkflow")
            if app_workflow is not None and hasattr(
                app_workflow, "set_approval_gate"
            ):
                app_workflow.set_approval_gate(self.request_approval)
                logger.info(
                    "SessionController: approval gate wired into "
                    "ApplicationsWorkflow"
                )
        except Exception as exc:
            logger.warning(
                "SessionController: could not wire approval gate | %s "
                "— HITL disabled",
                exc,
            )

    # =========================================================================
    # CRASH RECOVERY
    # =========================================================================

    def _perform_startup_recovery(self) -> None:
        """Resets tasks stuck in 'IN_PROGRESS' from a previous crashed session.

        Called once during construction. If the app died while tasks were
        running, this ensures they get picked up again. Safe to call on
        a fresh database (does nothing if no interrupted tasks exist).
        """
        try:
            recovered = self.db.recover_interrupted_tasks()
            if recovered > 0:
                logger.warning(
                    "Recovered %d interrupted tasks from a previous session",
                    recovered,
                )
        except Exception as exc:
            logger.error(
                "Startup recovery failed | error=%s — proceeding anyway",
                exc,
                exc_info=True,
            )