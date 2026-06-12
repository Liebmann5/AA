"""Defines every event that can flow through AA's EventBus.

This module is the single source of truth for all event types in the system.
Every component that publishes or subscribes to the EventBus must use the
Event enum defined here — never raw strings.

Design Rules:
    - Events are facts, not commands. They describe what *happened*, not what
      should happen next. "APPLICATION_SUBMITTED" is correct. "SUBMIT_APPLICATION"
      is wrong — that would be a command, which belongs in the engine, not on the bus.
    - Every significant state change in the system should have a corresponding
      event. This makes the system auditable: the full event log tells the
      complete story of every session.
    - Subscribers must never assume they are the only listener for an event.
      The bus delivers to all subscribers; design handlers accordingly.

Grouping:
    Events are grouped by the subsystem that publishes them. The group a
    subscriber cares about tells you which layer of the architecture they
    live in.

Example:
    >>> from auto_apply.domain.events import Event
    >>> event_bus.publish(Event.JOBS_DISCOVERED, {"count": 42})
    >>> event_bus.subscribe(Event.BROWSER_UNHEALTHY, handle_browser_failure)
"""

from enum import Enum, auto


class Event(Enum):
    """Complete catalog of all system events.

    Published by specific subsystems; subscribed to by any interested component.
    The docstring on each member names its publisher and typical payload shape.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION LIFECYCLE
    # Published by: SessionController, AgentOrchestrator
    # ─────────────────────────────────────────────────────────────────────────

    SESSION_STARTED = auto()
    """Session has been fully initialized and the work queue is seeded.

    Payload: {'session_id': str, 'profile_name': str}
    """

    SESSION_PAUSED = auto()
    """User or system has paused execution. Browser remains alive.

    Payload: {'reason': str}  # e.g. "user_request", "network_lost", "captcha"
    """

    SESSION_RESUMED = auto()
    """Execution has resumed after a pause.

    Payload: {'reason': str}  # e.g. "user_request", "network_restored"
    """

    SESSION_COMPLETE = auto()
    """The work queue has been fully processed and the session ended cleanly.

    Payload: {'session_id': str, 'stats': dict}
    """

    SESSION_ABORTED = auto()
    """The session was terminated before completion due to an unrecoverable error.

    Payload: {'session_id': str, 'reason': str}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # TASK LIFECYCLE
    # Published by: AgentOrchestrator
    # ─────────────────────────────────────────────────────────────────────────

    TASK_STARTED = auto()
    """A WorkUnit has been dequeued and dispatched to a handler.

    Payload: {'task_id': str, 'task_type': str, 'priority': int}
    """

    TASK_COMPLETED = auto()
    """A WorkUnit was processed successfully and marked complete in the DB.

    Payload: {'task_id': str, 'task_type': str}
    """

    TASK_FAILED = auto()
    """A WorkUnit raised an exception. It may be retried.

    Payload: {'task_id': str, 'task_type': str, 'error': str, 'retry_count': int}
    """

    TASK_PERMANENTLY_FAILED = auto()
    """A WorkUnit exhausted its retry budget. It will not be retried.

    Payload: {'task_id': str, 'task_type': str, 'error': str}
    """

    TASK_SKIPPED_DUPLICATE = auto()
    """A WorkUnit was skipped because its URL was already seen/applied.

    Payload: {'task_id': str, 'url': str}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # DISCOVERY DOMAIN
    # Published by: DiscoveryEngine, AgentOrchestrator._handle_discovery
    # ─────────────────────────────────────────────────────────────────────────

    JOBS_DISCOVERED = auto()
    """A discovery run completed and found one or more job listings.

    Payload: {'count': int, 'source': str, 'query': str}
    """

    DISCOVERY_PAGE_SCRAPED = auto()
    """A single SERP or company careers page was successfully scraped.

    Payload: {'url': str, 'jobs_found': int, 'page_number': int}
    """

    DISCOVERY_COMPLETE = auto()
    """All discovery tasks for the current session have been processed.

    Payload: {'total_jobs_found': int}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # VETTING DOMAIN
    # Published by: VettingEngine, AgentOrchestrator._handle_vetting
    # ─────────────────────────────────────────────────────────────────────────

    JOB_VETTED_PASS = auto()
    """A job passed all vetting filters and was queued for application.

    Payload: {'job_title': str, 'company': str, 'fit_score': float}
    """

    JOB_VETTED_FAIL = auto()
    """A job failed at least one vetting filter and was discarded.

    Payload: {'job_title': str, 'company': str, 'reason': str, 'filter': str}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # APPLICATION DOMAIN
    # Published by: ApplicationEngine, AgentOrchestrator._apply_batch
    # ─────────────────────────────────────────────────────────────────────────

    APPLICATION_STARTED = auto()
    """AA has begun filling out a job application form.

    Payload: {'job_title': str, 'company': str, 'url': str}
    """

    APPLICATION_SUBMITTED = auto()
    """An application was successfully submitted.

    Payload: {'job_title': str, 'company': str, 'url': str}
    """

    APPLICATION_FAILED = auto()
    """An application attempt failed (form error, navigation failure, etc.).

    Payload: {'job_title': str, 'company': str, 'url': str, 'reason': str}
    """

    APPLICATION_SKIPPED_PRIOR_SESSION = auto()
    """An application was skipped because this job was applied to previously.

    Payload: {'job_title': str, 'company': str, 'url': str}
    """

    REDIRECT_TO_LIST_DETECTED = auto()
    """ApplicationEngine detected a redirect to a job listing page instead of a form.

    The orchestrator should enqueue a Discovery WorkUnit for the URL rather than
    retrying the application. Engines never call each other directly.

    Payload: {'url': str, 'job_title': str, 'company': str}
    """

    FORM_FIELD_FILLED = auto()
    """A single form field was filled successfully. Used for granular telemetry.

    Payload: {'field_label': str, 'field_type': str, 'strategy': str}
    """

    FORM_FIELD_FAILED = auto()
    """A single form field could not be filled. Triggers retry or skip logic.

    Payload: {'field_label': str, 'field_type': str, 'error': str}
    """

    LOGIC_CONFLICT_DETECTED = auto()
    """A form field presented a conflict the solver could not auto-resolve.

    Example: "Select only 1 option" but the user profile has 4 matching values.
    The session is paused and this event is published so the GUI can display
    a resolution prompt.

    Payload: {'field_label': str, 'options': list, 'profile_matches': list}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # CAPTCHA AND SECURITY INTERRUPTIONS
    # Published by: EvasionManager, CaptchaHandler, AgentOrchestrator
    # ─────────────────────────────────────────────────────────────────────────

    CAPTCHA_DETECTED = auto()
    """A CAPTCHA challenge was detected on the current page.

    Payload: {'url': str, 'captcha_type': str}  # e.g. "recaptcha_v2"
    """

    CAPTCHA_RESOLVED = auto()
    """A CAPTCHA was resolved (automatically or manually).

    Payload: {'url': str, 'method': str}  # e.g. "auto", "manual"
    """

    CAPTCHA_REQUIRES_MANUAL_SOLVE = auto()
    """Auto-resolution failed. The GUI must prompt the user to solve manually.

    Payload: {'url': str, 'captcha_type': str, 'screenshot_path': str}
    """

    BOT_DETECTION_TRIGGERED = auto()
    """The site indicated it has detected automation (e.g. block page, honeypot).

    Payload: {'url': str, 'indicator': str}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # BROWSER HEALTH
    # Published by: BrowserHealthMonitor (daemon thread → EventBus → main loop)
    # ─────────────────────────────────────────────────────────────────────────

    BROWSER_HEALTHY = auto()
    """Periodic confirmation that the browser is responsive. Low-frequency.

    Payload: {'response_time_ms': float, 'consecutive_successes': int}
    """

    BROWSER_DEGRADED = auto()
    """Browser is responding slowly but still functional.

    Payload: {'response_time_ms': float, 'threshold_ms': float}
    """

    BROWSER_UNHEALTHY = auto()
    """Browser has stopped responding. Triggers driver teardown and restart.

    Payload: {'consecutive_failures': int, 'last_error': str}
    """

    BROWSER_DEAD = auto()
    """The browser is unrecoverable — failures exceeded the monitor's hard ceiling.

    Distinct from BROWSER_UNHEALTHY, which is a recoverable signal that pauses
    the loop and waits for restart. BROWSER_DEAD is terminal: the monitor has
    given up, has stopped its own polling loop, and the orchestrator should
    move to clean shutdown.

    Payload: {'consecutive_failures': int, 'ceiling': int, 'metrics': dict}
    """

    BROWSER_RESTARTED = auto()
    """The browser was torn down and a new driver was initialized successfully.

    Payload: {'new_driver': str, 'cascade_attempt': int}
    """

    BROWSER_CASCADE_EXHAUSTED = auto()
    """All available browsers in the BrowserCascade have failed.

    This is a terminal event for the session. The orchestrator will abort.

    Payload: {'attempted_browsers': list}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # NETWORK HEALTH
    # Published by: NetworkHealthMonitor (daemon thread → EventBus → main loop)
    # ─────────────────────────────────────────────────────────────────────────

    NETWORK_HEALTHY = auto()
    """Periodic confirmation that network connectivity is available.

    Payload: {'latency_ms': float}
    """

    NETWORK_UNHEALTHY = auto()
    """Network connectivity has been lost. Triggers session pause.

    Payload: {'last_successful_check': str}  # ISO timestamp
    """

    NETWORK_RESTORED = auto()
    """Network connectivity has been restored after an outage.

    Payload: {'downtime_seconds': float}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # PROVIDER HEALTH (Watchdog)
    # Published by: ProviderWatchdog (daemon thread → EventBus)
    # ─────────────────────────────────────────────────────────────────────────

    PROVIDER_TIMED_OUT = auto()
    """A provider worker thread has not sent a heartbeat within the configured
    timeout and is presumed stuck. The watchdog will attempt to recover by
    re‑queuing the work unit.

    Payload: {'worker_id': str, 'provider_name': str, 'last_action': str}
    """

    # ─────────────────────────────────────────────────────────────────────────
    # RESILIENCE AND CHECKPOINTING
    # Published by: CheckpointManager, AgentOrchestrator
    # ─────────────────────────────────────────────────────────────────────────

    CHECKPOINT_SAVED = auto()
    """Session state was successfully persisted to disk.

    Payload: {'checkpoint_path': str, 'actions_since_last': int}
    """

    CHECKPOINT_RESTORED = auto()
    """A prior session's checkpoint was loaded and state was restored.

    Payload: {'checkpoint_timestamp': str, 'stats': dict}
    """

    CHECKPOINT_FAILED = auto()
    """A checkpoint save or load operation failed. Session continues but
    crash recovery for this interval is not guaranteed.

    Payload: {'operation': str, 'error': str}  # operation: "save" | "load"
    """

    # ─────────────────────────────────────────────────────────────────────────
    # RESEARCH DATA COLLECTION
    # Published by: ResearchCollector (passive EventBus subscriber)
    # Only fires when the user has opted into research collection.
    # ─────────────────────────────────────────────────────────────────────────

    RESEARCH_SIGNAL_RECORDED = auto()
    """An anonymized research signal was recorded.

    Payload: {'signal_type': str, 'category': str}
    Note: Payload deliberately contains NO job URLs, company names, or any
    data that could identify the user or their specific applications.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # HUMAN-IN-THE-LOOP (HITL)
    # Published by: ApplicationEngine, AgentOrchestrator
    # Consumed by: GUI dashboard (modal), CLI dashboard (stdin prompt)
    # ─────────────────────────────────────────────────────────────────────────

    HUMAN_APPROVAL_REQUESTED = auto()
    """The agent has paused at a HITL checkpoint and needs the user to decide.

    The publishing side blocks on a threading.Event until HUMAN_APPROVAL_GRANTED
    arrives or a timeout elapses (default 300 s → auto-skip).

    Payload: {
        'context_id': str,       # UUID; correlates request ↔ grant
        'checkpoint': str,       # Checkpoint enum name
        'question': str,         # Human-readable description of the decision
        'options': list[str],    # Available choices (always includes 'skip')
    }
    """

    HUMAN_APPROVAL_GRANTED = auto()
    """The user has responded to a HITL prompt. Unblocks the waiting engine thread.

    Payload: {
        'context_id': str,   # Must match the HUMAN_APPROVAL_REQUESTED context_id
        'choice': str,       # One of the options listed in the request
    }
    """

    # ─────────────────────────────────────────────────────────────────────────
    # UI AND PROGRESS REPORTING
    # Published by: AgentOrchestrator, domain engines
    # Consumed by: GUI dashboard, CLI dashboard, telemetry service
    # ─────────────────────────────────────────────────────────────────────────

    PROGRESS_UPDATE = auto()
    """General progress tick for UI display. Published frequently.

    Payload: {
        'discovered': int,
        'vetted': int,
        'applied': int,
        'failed': int,
        'current_action': str,
    }
    """

    LOG_MESSAGE = auto()
    """A log message intended for display in the live UI log pane.

    Payload: {'level': str, 'message': str}  # level: "info"|"warning"|"error"
    """

    STATUS_UPDATE = auto()
    """A human-readable status string for display in the UI status bar.

    Payload: {'status': str}  # e.g. "Scanning Google Jobs..."
    """