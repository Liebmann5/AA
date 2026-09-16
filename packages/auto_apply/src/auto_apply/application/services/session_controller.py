"""Manages the active session lifecycle and satisfies UIPort structurally.

This module acts as the sole bridge between the UI layer (GUI or CLI) and
the agent backend. It strictly enforces the Three-Tier Configuration
Hierarchy via CapabilitiesRegistry before the Orchestrator is allowed to
launch, translates UI wizard output into WorkUnits, and exposes a clean
polling API for dashboard updates.

Architecture Contract:
    The SessionController is the ONLY object the UI touches. Since the
    UIPort driving port landed (domain/ports/ui_port.py), this class is
    its structural implementation — there is NO wrapper class and no
    inheritance; runtime_checkable satisfaction is asserted by
    tests/application/test_ui_port_conformance.py.

    Two surfaces exist, deliberately:

    1. The typed surface (UIPort). ``start_session(SessionRequest)``,
       ``snapshot()``, ``summary()``, ``queue_snapshot()``,
       ``pending_approvals()``, ``recent_events()``, and the lifecycle
       commands. Every value that crosses this surface is a frozen DTO
       from domain/models/ui_contract.py.

    2. The legacy dict surface (DEPRECATED shim). ``initialize_session``
       also accepts the historical ``dict[str, Any]`` config. It
       translates known keys (``mode``, ``input``, ``keywords``,
       ``location``, ``max_results``, ``links``, ``execution_mode``) into
       a ``SessionRequest`` and delegates to the typed path, WARNING on
       any unrecognised key. The shim exists so the CLI and GUI wizards
       and 1,200-plus tests keep working; it is REMOVED at stage U5 when
       both surfaces are retyped to emit SessionRequest directly.

    Seeding:
    - ONE link seeder (``_seed_link_tasks``) parameterised by
      ``execution_mode`` replaces the legacy pair
      ``_seed_direct_apply_tasks`` / ``_seed_vet_tasks``. The two remain
      as thin shims with identical behavior: priority (1 vs 3) is derived
      from ``request.seed_priority``; ``next_task``/``skip_vetting`` are
      derived from ``execution_mode`` — the execution-mode axis that was
      previously written out in literals.
    - The shim's mode label maps to a SessionExecutionMode through
      ``_LEGACY_ENTRY_TO_EXECUTION_MODE``, and EVERY private shim reads
      the same table — there is exactly one answer per label no matter
      which door the caller uses. See the table's comment: it carries
      the revision history of the two ways this has already gone wrong
      (a blanket default, then a row narrowed by enum-name reading).

    Execution mode:
    - A SessionRequest's ``execution_mode`` reaches the live session plan
      end to end: the controller rebuilds the frozen SessionPlan via
      ``model_copy`` and assigns it to ``self.orchestrator.session_plan``,
      which the orchestrator reads at every dispatch. Seeded WorkUnits
      also carry the mode in ``context_data["execution_mode"]`` so a
      checkpoint-restored queue remains self-describing.

    Providers:
    - A SessionRequest's ``providers`` reaches the live session plan the
      same way: threaded into ``active_providers`` when non-empty, the
      plan default kept when empty. DiscoveryWorkflow's fan-out filters
      by this field (see _initialize_sources), so a request naming one
      engine runs one engine. The rebuilt plan is also pushed into every
      plan-holding workflow at the same moment — without that refresh,
      workflows keep the boot plan and request values never reach them
      (this is also why the wizard's max_results used to reach the plan
      but never the scraper).

    Statistics (CHANGED in this stage):
    - This module no longer touches the orchestrator's private session
      report. ``summary()`` / ``get_stats()`` are projections built from
      (a) the orchestrator's PUBLIC ``context.stats`` and queue stats,
      and (b) a controller-owned ``SessionReport`` fed by EventBus
      events (APPLICATION_SUBMITTED / APPLICATION_FAILED with an
      ``evidence_outcome`` payload). The orchestrator's own saved report
      (written at teardown) remains the authoritative record; this
      projection is the live UI view. Disclosed gaps: per-application
      timing and ``report_path`` are only in the saved report, and
      dedupe-skip records (recorded by the orchestrator directly, with
      no event) appear in the saved report's ``applications_completed``
      but not here — "attempted" now means "actually attempted".

    Approval evidence:
    - Every HITL gate answer is recorded with an ``AnsweredBy`` stamp in
      ``self._approval_evidence`` and the recent-events stream, not only
      in the log. A 300 s timeout used to return "skip" with nothing but
      a WARNING; it is now recorded as ``AnsweredBy.TIMEOUT``. Submissions
      made with autonomy ON are stamped ``AnsweredBy.POLICY`` (stage E1),
      so a machine-authorised submission is labelled, never passed as human.

    Activity projection (stage D1):
    - The controller subscribes to 17 EventBus events (was 10) and
      projects every record onto a UI-sized ``ActivityKind`` vocabulary
      defined in domain/models/ui_contract.py. The raw internal ``Event``
      enum never crosses the port on ``recent_events()``.
    - One mapping table (``_EVENT_KIND_MAP``) and one outcome-refinement
      table (``_OUTCOME_KIND_MAP``) live here, owned by the application
      layer. A pin (tests/application/test_ui_port_conformance.py)
      asserts every subscribed event maps to exactly one kind and every
      kind is reachable, so adding a subscription without deciding its
      kind fails loudly.
    - One feed record per application: the thinner ``_submit_application``
      event (published without ``evidence_outcome``) no longer produces a
      second, mislabeled entry.

    SessionController.from_profile() eliminated; construction is the
    sole responsibility of the composition root (infrastructure/composition_root.py).

Threading Model:
    The orchestrator runs in a daemon thread. The UI polls snapshot()/
    summary() from the main thread. Event handlers subscribed here run
    on the orchestrator thread and only append to in-memory structures
    (EventBus handler contract: <5ms, no I/O).

Example:
    >>> from auto_apply.infrastructure.composition_root import build_session_controller
    >>> controller = build_session_controller(profile)
    >>> task_count = controller.start_session(
    ...     SessionRequest(entry=EntryPoint.SEARCH, keywords=("Python Dev",),
    ...                    execution_mode=SessionExecutionMode.DISCOVER_ONLY))
    >>> controller.start()
    >>> # ... poll controller.snapshot() from the UI ...
    >>> controller.stop()
"""

import csv
import getpass
import json
import logging
import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Any

from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.agent.state_machine import AgentState
from auto_apply.application.services.autonomy import (
    apply_autonomy,
    autonomy_enabled_for_profile,
)
from auto_apply.domain.config import USER_DATA_DIR
from auto_apply.domain.events import Event
from auto_apply.domain.models.application_evidence import ApplicationEvidence
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.models.task_priority import TaskPriority
from auto_apply.domain.models.ui_contract import (
    ActivityKind,
    ApprovalRequest,
    DiscoveredJob,
    EntryPoint,
    QueueSnapshot,
    SessionEventRecord,
    SessionHistoryEntry,
    SessionRequest,
    SessionSnapshot,
    SessionSummary,
    SessionViewState,
    SubmittedApplication,
    entry_point_from_label,
    view_state_from_agent_state,
)
from auto_apply.domain.models.work_unit import TaskType, WorkUnit
from auto_apply.domain.ports.profile_repository_port import ProfileRepositoryPort
from auto_apply.domain.ports.registry_port import RegistryPort
from auto_apply.domain.ports.work_queue_port import WorkQueuePort

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Approval evidence vocabulary (this stage's home; lift to ui_contract when
# the workflow starts stamping POLICY — the workflow change is a later stage)
# ═════════════════════════════════════════════════════════════════════════════


class AnsweredBy(Enum):
    """Who produced the answer to a HITL gate.

    HUMAN  — a person chose an option (via provide_approval / answer_approval).
    POLICY — the interrupt policy authorised the action without a human
             (the workflow's should_pause=False path). Stamped by the
             controller from its own frozen autonomy state: when autonomy
             is on, the authoriser can only take the no-pause path, so a
             successful submission is provably policy-authorised (stage E1).
    TIMEOUT — the gate's wait elapsed and the machine returned "skip".
    """

    HUMAN = auto()
    POLICY = auto()
    TIMEOUT = auto()


@dataclass(frozen=True)
class ApprovalAnswer:
    """One recorded answer to one HITL gate, for research-grade evidence."""

    context_id: str
    checkpoint: str
    choice: str
    answered_by: AnsweredBy
    at: datetime


# ═════════════════════════════════════════════════════════════════════════════
# Activity projection (D1) — Event → ActivityKind mapping, outcome refinement,
# and the single wording site for every feed record's text.
#
# These tables are owned by the application layer per the D1 ruling. The pins
# in tests/application/test_ui_port_conformance.py assert:
#   * the live subscription set equals _EVENT_KIND_MAP's keys (minus the two
#     HITL events recorded locally);
#   * _STREAM_TEXT_RENDERERS covers every stream-only subscription;
#   * _OUTCOME_KIND_MAP covers every ApplicationEvidence outcome literal;
#   * every ActivityKind is reachable from these tables.
# Adding a subscription without adding its row in all the right places fails
# loudly — that is the point of keeping the tables here, in one place.
# ═════════════════════════════════════════════════════════════════════════════

_EVENT_KIND_MAP: dict[Event, ActivityKind] = {
    # Discovery
    Event.JOBS_DISCOVERED: ActivityKind.FOUND,
    Event.DISCOVERY_COMPLETE: ActivityKind.INFO,
    Event.TASK_SKIPPED_DUPLICATE: ActivityKind.SKIPPED,
    # Vetting
    Event.JOB_VETTED_PASS: ActivityKind.VETTED,
    Event.JOB_VETTED_FAIL: ActivityKind.REJECTED,
    # Application (APPLICATION_FAILED is refined per-payload below)
    Event.APPLICATION_SUBMITTED: ActivityKind.APPLIED,
    Event.APPLICATION_FAILED: ActivityKind.FAILED,
    Event.REDIRECT_TO_LIST_DETECTED: ActivityKind.INFO,
    # Access barriers
    Event.CAPTCHA_REQUIRES_MANUAL_SOLVE: ActivityKind.BLOCKED,
    Event.BROWSER_UNHEALTHY: ActivityKind.BLOCKED,
    Event.BROWSER_DEAD: ActivityKind.BLOCKED,
    Event.NETWORK_UNHEALTHY: ActivityKind.BLOCKED,
    # Degradation / recovery
    Event.BROWSER_DEGRADED: ActivityKind.INFO,
    Event.NETWORK_RESTORED: ActivityKind.INFO,
    # Provider failures
    Event.PROVIDER_TIMED_OUT: ActivityKind.FAILED,
    Event.PROVIDER_BENCHED: ActivityKind.INFO,
    # Task lifecycle
    Event.TASK_PERMANENTLY_FAILED: ActivityKind.FAILED,
    # HITL (recorded locally, not bus-subscribed)
    Event.HUMAN_APPROVAL_REQUESTED: ActivityKind.WAITING,
    Event.HUMAN_APPROVAL_GRANTED: ActivityKind.INFO,
}

#: Every outcome literal of ApplicationEvidence.outcome maps to exactly one
#: kind. A pin asserts set(get_args(outcome Literal)) == set(this dict).
_OUTCOME_KIND_MAP: dict[str, ActivityKind] = {
    "SUBMITTED": ActivityKind.APPLIED,
    "PROBABLY_SUBMITTED": ActivityKind.APPLIED,
    "USER_SKIPPED": ActivityKind.SKIPPED,
    "SUBMISSION_GATE_BLOCKED": ActivityKind.REFUSED,
    "POLICY_BLOCKED": ActivityKind.REFUSED,
    "CAPTCHA_BLOCKED": ActivityKind.BLOCKED,
    "LOGIN_WALL_BLOCKED": ActivityKind.BLOCKED,
    "AMBIGUOUS": ActivityKind.FAILED,
    "FAILED_NO_SUBMIT_BUTTON": ActivityKind.FAILED,
    "FAILED_NAVIGATION": ActivityKind.FAILED,
    "FAILED_REQUIRED_FIELD": ActivityKind.FAILED,
    "FAILED_FILE_UPLOAD": ActivityKind.FAILED,
    "ERROR": ActivityKind.FAILED,
}

#: Kinds whose records surface at WARNING level in the feed. Everything else
#: is INFO. Level is display data, not a log level.
_STREAM_WARNING_KINDS: frozenset[ActivityKind] = frozenset({
    ActivityKind.BLOCKED,
    ActivityKind.REFUSED,
    ActivityKind.FAILED,
    ActivityKind.WAITING,
})


# ─────────────────────────────────────────────────────────────────────────────
# Per-event text renderers (whitelist-only: each reads only the keys named in
# its own body — unknown payload keys, including any PII-shaped values, are
# never interpolated. Pinned by test_projection_drops_payload_pii.)
# ─────────────────────────────────────────────────────────────────────────────

def _render_discovery_complete(p: dict) -> str:
    return (
        f"Discovery round complete: {p.get('enqueued', 0)} new job(s) "
        f"from {p.get('raw_found', 0)} found"
    )


def _render_captcha_manual_solve(p: dict) -> str:
    captcha_type = str(p.get("captcha_type") or "unknown")
    return f"A CAPTCHA needs a human ({captcha_type})"


def _render_provider_timed_out(p: dict) -> str:
    return (
        f"Provider stuck: {p.get('provider_name', 'unknown')} "
        f"({p.get('last_action', '')})"
    )


def _render_provider_benched(p: dict) -> str:
    return f"Provider benched for this session: {p.get('provider', 'unknown')}"


def _render_task_permanently_failed(p: dict) -> str:
    return f"Task failed permanently: {p.get('task_type', 'unknown')}"


def _render_task_skipped_duplicate(p: dict) -> str:
    return f"Skipped duplicate job: {str(p.get('url', ''))[:60]}"


def _render_browser_degraded(p: dict) -> str:
    if "response_ms" in p:
        return f"Browser is slow ({p['response_ms']}ms)"
    return f"Browser degraded ({p.get('consecutive_failures', '?')} failed checks)"


def _render_browser_unhealthy(_p: dict) -> str:
    return "Browser unresponsive — attempting recovery"


def _render_browser_dead(_p: dict) -> str:
    return "Browser died — the session will stop cleanly"


def _render_network_unhealthy(_p: dict) -> str:
    return "Network connection lost — pausing until it returns"


def _render_network_restored(p: dict) -> str:
    downtime = p.get("downtime_seconds")
    if downtime is not None:
        return f"Network restored ({downtime}s offline)"
    return "Network restored"


def _render_redirect_to_list(p: dict) -> str:
    url = str(p.get("url", ""))
    host = url.split("/")[2] if url.count("/") >= 2 else url
    return f"Apply link led to a job board — searching it instead ({host})"


#: One renderer per stream-only subscription. A pin asserts this dict's keys
#: equal the live stream-only subscription set.
_STREAM_TEXT_RENDERERS: dict[Event, Any] = {
    Event.DISCOVERY_COMPLETE: _render_discovery_complete,
    Event.CAPTCHA_REQUIRES_MANUAL_SOLVE: _render_captcha_manual_solve,
    Event.PROVIDER_TIMED_OUT: _render_provider_timed_out,
    Event.PROVIDER_BENCHED: _render_provider_benched,
    Event.TASK_PERMANENTLY_FAILED: _render_task_permanently_failed,
    Event.TASK_SKIPPED_DUPLICATE: _render_task_skipped_duplicate,
    Event.BROWSER_DEGRADED: _render_browser_degraded,
    Event.BROWSER_UNHEALTHY: _render_browser_unhealthy,
    Event.BROWSER_DEAD: _render_browser_dead,
    Event.NETWORK_UNHEALTHY: _render_network_unhealthy,
    Event.NETWORK_RESTORED: _render_network_restored,
    Event.REDIRECT_TO_LIST_DETECTED: _render_redirect_to_list,
}


def _application_outcome_text(kind: ActivityKind, payload: dict) -> str:
    """Sentence for one application outcome. Whitelist: job_title, company,
    evidence_outcome. Nothing else is interpolated."""
    title = str(payload.get("job_title", ""))[:80]
    company = str(payload.get("company", ""))[:60]
    who = f"{title} @ {company}" if title else (company or "(unknown job)")
    outcome = str(payload.get("evidence_outcome", ""))
    if kind is ActivityKind.APPLIED:
        return f"Applied: {who}"
    if kind is ActivityKind.SKIPPED:
        return f"Skipped: {who}"
    if kind is ActivityKind.REFUSED:
        return f"Submission refused by gate: {who}"
    if kind is ActivityKind.BLOCKED:
        if outcome == "CAPTCHA_BLOCKED":
            barrier = "CAPTCHA"
        elif outcome == "LOGIN_WALL_BLOCKED":
            barrier = "login wall"
        else:
            barrier = "an access barrier"
        return f"Blocked by {barrier}: {who}"
    return f"Application failed: {who} ({outcome})"


def _vetting_text(kind: ActivityKind, payload: dict) -> str:
    """Sentence for one vetting decision. Whitelist: job_title, company,
    reason (truncated)."""
    title = str(payload.get("job_title", ""))[:80]
    company = str(payload.get("company", ""))[:60]
    who = f"{title} @ {company}" if title else (company or "(unknown job)")
    if kind is ActivityKind.VETTED:
        return f"Passed vetting: {who}"
    return f"Rejected: {who} — {str(payload.get('reason', ''))[:80]}"


class SessionController:
    """Controls the secure execution lifecycle of the automation agent.

    This is the single entry point for the UI layer and the structural
    implementation of UIPort. It manages:
        1. Zero-Trust boot (CapabilitiesRegistry construction).
        2. Work queue seeding from a typed SessionRequest or the legacy dict shim.
        3. Orchestrator thread lifecycle (start/stop/poll).
        4. Crash recovery (interrupted task reset on startup).
        5. Network health pre-check before seeding tasks (Wave J3).
        6. HITL approval gating with AnsweredBy evidence.
        7. Custody operations: results export, profile export, session history.
        8. Activity projection onto a UI-sized ActivityKind vocabulary (D1).
        9. Autonomy state read/write (E1): autonomy() answers whether THIS
           session submits without asking (frozen at composition);
           set_autonomy() writes the profile for FUTURE sessions.

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
        profile_repo: ProfileRepositoryPort | None = None,
    ) -> None:
        """Stores pre-built dependencies and starts the event-fed projections.

        Direct construction is discouraged. Use build_session_controller()
        in infrastructure/composition_root.py which wires everything correctly.

        Args:
            registry: A RegistryPort — the fully resolved session config.
            db: The WorkQueuePort for task queue operations.
            orchestrator: The AgentOrchestrator, ready to run.
            profile_repo: Optional ProfileRepositoryPort for custody operations
                (export_profile) and the autonomy write (set_autonomy). When
                None, both raise a clear error rather than guessing.
        """
        self.registry = registry
        self.db = db
        self.orchestrator = orchestrator
        self._profile_repo = profile_repo
        self._agent_thread: threading.Thread | None = None
        # HITL: maps context_id → (gate_event, chosen_value_holder, payload).
        self._pending_approvals: dict[
            str, tuple[threading.Event, list[str], dict]
        ] = {}
        self._approvals_lock = threading.Lock()

        # ── Event-fed projections (no private-attribute access) ─────────────
        # The controller owns a SessionReport fed by EventBus events. The
        # orchestrator's own saved report remains the authoritative record.
        self._report = SessionReport(
            session_id=getattr(
                getattr(orchestrator, "context", None), "session_id", "unknown"
            ),
            profile_name=getattr(
                registry.get_active_profile(), "profile_name", "unknown"
            ),
        )
        self._recent_events: deque[SessionEventRecord] = deque(maxlen=200)

        # ── Approval evidence ────────────────────────────────────────────────
        self._approval_evidence: dict[str, ApprovalAnswer] = {}

        # ── Autonomy state (E1) — frozen at this controller's composition ──
        # Computed from the checkpoints the interrupt policy was built from.
        # The policy is built once (composition_root) and never rebuilt, so
        # this answer cannot move during the session — it is the "off is off"
        # guarantee made queryable. set_autonomy writes the profile but never
        # rebuilds a built policy, which is what keeps the guarantee true.
        profile_for_autonomy = registry.get_active_profile()
        self._autonomy_at_construction: bool = (
            autonomy_enabled_for_profile(profile_for_autonomy)
            if profile_for_autonomy is not None
            else False
        )

        # ── Lifecycle flags ──────────────────────────────────────────────────
        self._session_seeded: bool = False

        self._subscribe_session_events()

        logger.info("SessionController initialized")

    # =========================================================================
    # CONSTRUCTION
    # =========================================================================

    # The from_profile classmethod has been DELETED.  Construction is now
    # centralized in infrastructure/composition_root.py ← the Composition Root.

    def _subscribe_session_events(self) -> None:
        """Subscribes the event-fed projections to the orchestrator's EventBus.

        Handlers run on the orchestrator thread and only append to in-memory
        structures — no I/O, no blocking (EventBus handler contract).
        Degrades gracefully if the bus is absent (e.g., a mock orchestrator).

        The subscriptions are written out one per line rather than looped:
        tests/architecture/test_event_wiring.py resolves event references by
        shape (direct Event.X, an inline ternary, or a single-assignment
        local), and a loop variable is none of those. Do NOT fold these back
        into a for-loop without teaching that pin a fourth form.

        The set is 17 bus events (D1) — see the module docstring's Activity
        projection section for the in/out ruling. HUMAN_APPROVAL_REQUESTED is
        deliberately NOT subscribed: the controller publishes it from
        request_approval (the single choke point every gate passes through)
        and records WAITING there directly.
        """
        try:
            bus = self.orchestrator.event_bus
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "SessionController: no event bus to subscribe to (%s) — "
                "projections will run from public state only", exc,
            )
            return
        try:
            bus.subscribe(Event.APPLICATION_SUBMITTED, self._on_application_outcome)
            bus.subscribe(Event.APPLICATION_FAILED, self._on_application_outcome)
            bus.subscribe(Event.JOB_VETTED_PASS, self._on_vetting_event)
            bus.subscribe(Event.JOB_VETTED_FAIL, self._on_vetting_event)
            bus.subscribe(Event.JOBS_DISCOVERED, self._on_discovery_event)
            bus.subscribe(Event.DISCOVERY_COMPLETE, partial(self._on_stream_event, Event.DISCOVERY_COMPLETE))
            bus.subscribe(Event.CAPTCHA_REQUIRES_MANUAL_SOLVE, partial(self._on_stream_event, Event.CAPTCHA_REQUIRES_MANUAL_SOLVE))
            bus.subscribe(Event.PROVIDER_TIMED_OUT, partial(self._on_stream_event, Event.PROVIDER_TIMED_OUT))
            bus.subscribe(Event.PROVIDER_BENCHED, partial(self._on_stream_event, Event.PROVIDER_BENCHED))
            bus.subscribe(Event.TASK_PERMANENTLY_FAILED, partial(self._on_stream_event, Event.TASK_PERMANENTLY_FAILED))
            bus.subscribe(Event.TASK_SKIPPED_DUPLICATE, partial(self._on_stream_event, Event.TASK_SKIPPED_DUPLICATE))
            bus.subscribe(Event.BROWSER_DEGRADED, partial(self._on_stream_event, Event.BROWSER_DEGRADED))
            bus.subscribe(Event.BROWSER_UNHEALTHY, partial(self._on_stream_event, Event.BROWSER_UNHEALTHY))
            bus.subscribe(Event.BROWSER_DEAD, partial(self._on_stream_event, Event.BROWSER_DEAD))
            bus.subscribe(Event.NETWORK_UNHEALTHY, partial(self._on_stream_event, Event.NETWORK_UNHEALTHY))
            bus.subscribe(Event.NETWORK_RESTORED, partial(self._on_stream_event, Event.NETWORK_RESTORED))
            bus.subscribe(Event.REDIRECT_TO_LIST_DETECTED, partial(self._on_stream_event, Event.REDIRECT_TO_LIST_DETECTED))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SessionController: event subscription failed (%s) — "
                "projections may be incomplete", exc,
            )

    # =========================================================================
    # EVENT FEED (report + stream)
    # =========================================================================

    def _on_application_outcome(self, payload: Any) -> None:
        """Records one application outcome into the controller's SessionReport
        and one feed record into the recent-events stream.

        Only payloads carrying ``evidence_outcome`` are recorded — the
        workflow's richer ``_record_application_outcome`` event. The thinner
        ``_submit_application`` event (published without evidence_outcome)
        is skipped entirely (D1): it previously produced a second feed entry
        that was mislabeled as a failure even for successful submits. Each
        application now produces exactly one feed record, with its kind
        refined from the outcome (BLOCKED for access barriers, REFUSED for
        gate/policy refusals, SKIPPED for user-declined, APPLIED for
        submissions, FAILED for everything else).

        POLICY stamp (stage E1): when this session runs with autonomy on,
        the authoriser can only take the no-pause path for every submission,
        so a successful outcome is provably policy-authorised — no gate was
        consulted and no human answer exists. The stamp makes that machine
        decision visible in the evidence record instead of passing as human.
        """
        if not isinstance(payload, dict) or "evidence_outcome" not in payload:
            return
        outcome = str(payload["evidence_outcome"])
        try:
            job = Job(
                title=str(payload.get("job_title", "")),
                company=str(payload.get("company", "")),
                url=str(payload.get("job_url") or payload.get("url", "")),
                source="event_bus",
            )
            evidence = ApplicationEvidence(
                outcome=outcome,  # type: ignore[arg-type]
                confidence=float(payload.get("evidence_confidence") or 0.0),
                ats_platform=payload.get("ats"),
                required_fields_filled=int(payload.get("fields_filled") or 0),
                pages_navigated=int(payload.get("pages_navigated") or 0),
                used_gpt4all=bool(payload.get("used_gpt4all", False)),
            )
            self._report.record_application(job, evidence)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "SessionController: could not record application event | %s",
                exc,
            )

        # ── POLICY stamp (autonomy) — the record must not pass a machine
        # authorisation off as a human one. Derivable from the controller's
        # own frozen state: autonomy on + successful outcome ⟹ policy.
        if self.autonomy() and outcome in ("SUBMITTED", "PROBABLY_SUBMITTED"):
            context_id = f"policy:{payload.get('job_url') or payload.get('url', '')}"
            self._approval_evidence[context_id] = ApprovalAnswer(
                context_id=context_id,
                checkpoint="BEFORE_FORM_SUBMIT",
                choice="submit",
                answered_by=AnsweredBy.POLICY,
                at=datetime.now(timezone.utc),
            )
            self._record_stream(
                ActivityKind.INFO,
                "Submission authorized by policy (autonomy on): "
                f"{str(payload.get('job_title', ''))[:60]} @ "
                f"{str(payload.get('company', ''))[:40]}",
            )

        kind = _OUTCOME_KIND_MAP.get(outcome, ActivityKind.FAILED)
        self._record_stream(kind, _application_outcome_text(kind, payload))

    def _on_vetting_event(self, payload: Any) -> None:
        """JOB_VETTED_PASS increments the passed-vetting counter; both stream.

        The EventBus hands the same handler both events, so pass/fail is
        inferred from the payload shape the workflow publishes:
          pass: {"job_title","company","fit_score","reason":"all_filters_passed"}
          fail: {"job_title","company","fit_score","reason":"<filter>: <why>"}
        """
        is_pass = (
            isinstance(payload, dict)
            and payload.get("reason") == "all_filters_passed"
        )
        if is_pass:
            self._report.pending_jobs_to_apply_for += 1
        kind = ActivityKind.VETTED if is_pass else ActivityKind.REJECTED
        self._record_stream(
            kind,
            _vetting_text(kind, payload if isinstance(payload, dict) else {}),
        )

    def _on_discovery_event(self, payload: Any) -> None:
        """JOBS_DISCOVERED increments the raw-found counter and streams."""
        count = 0
        if isinstance(payload, dict):
            try:
                count = int(payload.get("count", 0))
            except (TypeError, ValueError):
                count = 0
        if count > 0:
            self._report.raw_results_found += count
        source = "discovery"
        if isinstance(payload, dict):
            source = str(payload.get("source") or "discovery")
        self._record_stream(
            ActivityKind.FOUND, f"Found {count} job(s) ({source})"
        )

    def _on_stream_event(self, event: Event, payload: Any) -> None:
        """Stream-only events (no report effect), one handler for all twelve.

        Bound per-subscription via functools.partial so the handler knows
        which Event fired and can look up its kind and renderer.
        """
        self._record_event(event, payload)

    def _record_event(self, event: Event, payload: Any) -> None:
        """Projects one bus event onto the recent-events stream.

        The kind comes from ``_EVENT_KIND_MAP``; the sentence comes from
        ``_STREAM_TEXT_RENDERERS``. An event missing from either table is
        dropped with a warning rather than raising — the conformance pin
        exists so that never happens in production; a raise here would be
        swallowed by the EventBus into a log line nobody reads.
        """
        kind = _EVENT_KIND_MAP.get(event)
        renderer = _STREAM_TEXT_RENDERERS.get(event)
        if kind is None or renderer is None:
            logger.warning(
                "SessionController: stream event %r has no kind/renderer "
                "mapping — record dropped (add it to _EVENT_KIND_MAP and "
                "_STREAM_TEXT_RENDERERS)",
                event,
            )
            return
        data = payload if isinstance(payload, dict) else {}
        try:
            text = renderer(data)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "SessionController: stream renderer for %r failed (%s)",
                event, exc,
            )
            return
        self._record_stream(kind, text)

    def _record_stream(
        self, kind: ActivityKind, text: str, level: str | None = None
    ) -> None:
        """Appends one record to the bounded recent-events stream.

        Level defaults from the kind: BLOCKED / REFUSED / FAILED / WAITING
        records surface at WARNING; everything else at INFO. This is display
        data for the feed, not a log level.
        """
        try:
            if level is None:
                level = "WARNING" if kind in _STREAM_WARNING_KINDS else "INFO"
            self._recent_events.append(
                SessionEventRecord(kind=kind, text=text, level=level)
            )
        except Exception:  # noqa: BLE001 — the stream must never break a session
            pass

    # =========================================================================
    # SESSION INITIALIZATION — typed surface
    # =========================================================================

    def start_session(self, request: SessionRequest) -> int:
        """Translates a typed SessionRequest into queued WorkUnits.

        This is the typed entry point (UIPort-preferred). It rejects legacy
        dicts — use initialize_session(dict) for the deprecated shim.

        Args:
            request: The validated session request.

        Returns:
            The number of tasks queued.

        Raises:
            TypeError: If request is not a SessionRequest.
            ValueError: If the profile fails completeness validation.
        """
        if not isinstance(request, SessionRequest):
            raise TypeError(
                f"start_session expects a SessionRequest, got "
                f"{type(request).__name__}. For the deprecated dict shim, "
                f"call initialize_session(dict)."
            )
        return self._initialize_session_typed(request)

    def _initialize_session_typed(self, request: SessionRequest) -> int:
        """The single seeding implementation behind both typed and shim paths.

        Steps:
            1. Network health pre-check (Wave J3).
            2. Profile completeness validation (mode label derived from entry).
            3. Session plan rebuild with request.execution_mode (and the
               result cap when declared).
            4. Seeding by request.entry, with execution_mode stamped on every
               queued WorkUnit's context_data.
        """
        is_online = self._check_network_connectivity()
        if not is_online:
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
                mode = _legacy_mode_label(request.entry)
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

        # ── Rebuild the live session plan from the request ──────────────────
        self._rebuild_plan_for_request(request)

        # ── Autonomy label for the session record (E1) ──────────────────────
        # A run with autonomy on is labelled data, not spoiled data: the feed
        # states plainly that no per-submission review prompt will appear.
        if self.autonomy():
            self._record_stream(
                ActivityKind.INFO,
                "Autonomy ON for this session — submissions are authorized "
                "by policy; no per-submission review prompt will appear",
            )

        # ── Seed by entry point ──────────────────────────────────────────────
        if (
            request.entry in (EntryPoint.DIRECT_URLS, EntryPoint.VET_URLS)
            and not request.execution_mode.includes_application
        ):
            logger.warning(
                "SessionController: %d URL(s) seeded but execution_mode=%s "
                "does not include application — they will not be applied.",
                len(request.urls),
                request.execution_mode.value,
            )

        if request.entry is EntryPoint.SEARCH:
            task_count = self._seed_search_tasks(request)
        elif request.entry in (EntryPoint.DIRECT_URLS, EntryPoint.VET_URLS):
            task_count = self._seed_link_tasks(request)
        elif request.entry is EntryPoint.COMPANY_PAGES:
            task_count = self._seed_company_urls(request.urls)
        else:
            # EntryPoint is an enum; an unknown member cannot exist without
            # a type error at construction. Fail loud rather than guess.
            raise ValueError(f"Unknown entry point {request.entry!r}.")

        self._session_seeded = task_count > 0

        logger.info(
            "Session initialized | entry=%s execution_mode=%s tasks_queued=%d",
            request.entry.name,
            request.execution_mode.value,
            task_count,
        )
        return task_count

    def _rebuild_plan_for_request(self, request: SessionRequest) -> None:
        """Rebuilds the live session plan with the request's mode, cap, and engines.

        The registry's plan is the boot plan and stays read-only. The
        orchestrator's plan is the live one: it is what every dispatch-time
        branch reads (``orchestrator.session_plan.execution_mode``).

        ``max_results`` from the request becomes the per-query cap when
        declared — the CLI wizard's value is live for the first time (it
        was previously collected and discarded). Only positive integers are
        applied; anything else keeps the resolved plan value.

        ``providers`` from the request becomes the plan's
        ``active_providers`` when declared (non-empty); an empty tuple keeps
        the plan default. DiscoveryWorkflow's fan-out filters by this field,
        so a request naming one engine runs one engine.

        The rebuilt plan is also pushed into every plan-holding workflow
        (Discovery, Applications). Workflows receive their plan at
        composition time — the boot plan — so without this refresh, values
        the request changes (execution_mode, max_results_per_query,
        active_providers) would never reach them: the plan they hold is a
        different, older object. That staleness is why the wizard's
        max_results used to reach the plan but never the scraper.
        """
        base_plan = self.registry.get_session_plan()
        updates: dict[str, Any] = {"execution_mode": request.execution_mode}
        if isinstance(request.max_results, int) and request.max_results > 0:
            updates["max_results_per_query"] = request.max_results
        if request.providers:
            updates["active_providers"] = request.providers
        try:
            new_plan = base_plan.model_copy(update=updates)
            self.orchestrator.session_plan = new_plan
            self._refresh_workflow_plans(new_plan)
            logger.debug(
                "SessionController: session plan rebuilt | mode=%s cap=%s "
                "providers=%s",
                new_plan.execution_mode.value,
                new_plan.max_results_per_query,
                new_plan.active_providers,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SessionController: plan rebuild failed (%s) — continuing "
                "with the boot plan", exc,
            )

    def _refresh_workflow_plans(self, plan: SessionPlan) -> None:
        """Pushes the rebuilt plan into every plan-holding workflow.

        Workflows get their plan from the composition root at build time —
        the boot plan, which the controller's model_copy replaces rather than
        mutates. Without this refresh the workflow keeps the old object and
        reads stale values for every field the request can change. Vetting
        has no plan reference (its mode arrives per call), so it is skipped.
        """
        workflows = getattr(self.orchestrator, "_workflows", None)
        if not isinstance(workflows, dict):
            return
        for workflow in workflows.values():
            if hasattr(workflow, "_plan"):
                workflow._plan = plan

    # =========================================================================
    # SESSION INITIALIZATION — deprecated dict shim
    # =========================================================================

    def initialize_session(self, ui_config: dict[str, Any] | SessionRequest) -> int:
        """DEPRECATED shim: translate a legacy dict config and delegate.

        The typed entry point is :meth:`start_session`. This method exists
        so the CLI/GUI wizards and the existing test suite keep working; it
        is REMOVED at stage U3 when both surfaces are retyped.

        Shim behavior (ruled: fail kind for users, fail loud for maintainers):
            - ``mode`` is resolved via the alias table (``direct_links``
              from cli/wizard.py:47 now maps to DIRECT_URLS instead of
              raising).
            - ``execution_mode`` defaults from the LABEL through
              ``_LEGACY_ENTRY_TO_EXECUTION_MODE`` — 'direct'/'direct_links'
              become APPLY_ONLY (priority 1, apply immediately) and 'vet'
              becomes VET_AND_APPLY (priority 3, vet first, apply if passed —
              the legacy apply-after-vet behavior, restored after one
              revision where the row was VET_ONLY and silently narrowed it).
              An explicit ``execution_mode`` key in the dict overrides the
              label-derived default; an invalid value warns and falls back
              to FULL_PIPELINE.
            - ``keywords``/``location``/``max_results``/``links``/``input``
              are translated; the wizard's answers are no longer discarded.
            - Any unrecognised key (including ``strategy``, which no
              mechanism consumes) produces a WARNING, never an exception.

        Args:
            ui_config: The legacy dict config (or a SessionRequest, which
                is passed straight through for UIPort compatibility).

        Returns:
            The number of tasks queued.

        Raises:
            ValueError: For an unknown ``mode`` label (as before).
        """
        if isinstance(ui_config, SessionRequest):
            return self._initialize_session_typed(ui_config)
        if not isinstance(ui_config, dict):
            raise TypeError(
                f"initialize_session expects a SessionRequest or a legacy "
                f"dict, got {type(ui_config).__name__}."
            )
        request = self._request_from_legacy_dict(ui_config)
        return self._initialize_session_typed(request)

    def _request_from_legacy_dict(self, ui_config: dict[str, Any]) -> SessionRequest:
        """Builds a SessionRequest from a legacy UI config dict.

        The ``execution_mode`` default is derived from the mode label via
        ``_LEGACY_ENTRY_TO_EXECUTION_MODE`` — NOT a blanket FULL_PIPELINE.
        A blanket default is exactly the defect that turned legacy 'direct'
        into 'vet' payloads (priority 3, next_task="VET") because
        FULL_PIPELINE.includes_vetting is True. An explicit
        ``execution_mode`` key in the dict overrides the label-derived
        default.

        See initialize_session's docstring for the full translation rules.
        """
        known_keys = {
            "mode", "input", "keywords", "location",
            "max_results", "links", "execution_mode",
        }
        unknown = sorted(set(ui_config) - known_keys)
        for key in unknown:
            logger.warning(
                "SessionController: unrecognised session config key %r — "
                "ignored (fail-loud, not silent)",
                key,
            )
        if "strategy" in ui_config:
            logger.warning(
                "SessionController: key 'strategy' (%r) is collected by the "
                "wizard but consumed by no session mechanism; the prompt is "
                "being removed at stage U3.",
                ui_config.get("strategy"),
            )

        entry = entry_point_from_label(str(ui_config.get("mode", "discovery")))

        # Label-derived default first; an explicit key overrides it.
        execution_mode = _LEGACY_ENTRY_TO_EXECUTION_MODE[entry]
        if "execution_mode" in ui_config:
            try:
                execution_mode = SessionExecutionMode(
                    str(ui_config["execution_mode"])
                )
            except ValueError:
                logger.warning(
                    "SessionController: execution_mode=%r is not a valid "
                    "SessionExecutionMode — falling back to full_pipeline.",
                    ui_config["execution_mode"],
                )
                execution_mode = SessionExecutionMode.FULL_PIPELINE

        if entry is EntryPoint.SEARCH:
            raw = str(ui_config.get("input", "") or "")
            keyword_source = ui_config.get("keywords") or raw
            keywords = tuple(
                t.strip() for t in str(keyword_source).split(",") if t.strip()
            )
            location = str(ui_config.get("location", "") or "").strip()
            max_raw = ui_config.get("max_results")
            max_results = max_raw if isinstance(max_raw, int) else None
            return SessionRequest(
                entry=entry,
                execution_mode=execution_mode,
                keywords=keywords,
                location=location,
                max_results=max_results,
            )

        links = ui_config.get("links")
        if links is None:
            links = str(ui_config.get("input", "") or "")
        if isinstance(links, (list, tuple)):
            urls = tuple(str(u).strip() for u in links if str(u).strip())
        else:
            urls = tuple(
                u.strip() for u in str(links).splitlines() if u.strip()
            )
        return SessionRequest(
            entry=entry,
            execution_mode=execution_mode,
            urls=urls,
        )

    # =========================================================================
    # SEEDING — one implementation per entry point
    # =========================================================================

    def _seed_search_tasks(self, request: SessionRequest) -> int:
        """Creates DISCOVER tasks from the request (or the profile fallback).

        The request's keywords and location override the profile; an empty
        keyword list falls back to the profile's desired_job_titles, and an
        empty location falls back to preferred_locations, then "Remote".
        """
        profile = self.registry.get_active_profile()
        search_prefs = getattr(profile, "search_preferences", None)

        titles: list[str] = list(request.keywords)
        if not titles and search_prefs is not None:
            titles = list(getattr(search_prefs, "desired_job_titles", []) or [])
        if not titles:
            return 0

        if request.location:
            locations = [request.location]
        else:
            locations = (
                list(getattr(search_prefs, "preferred_locations", []) or [])
                if search_prefs is not None
                else []
            )
        if not locations:
            locations = ["Remote"]

        mode_value = request.execution_mode.value
        count = 0
        for title in titles:
            for location in locations:
                task = WorkUnit(
                    priority=TaskPriority.DISCOVER,
                    task_type=TaskType.DISCOVER,
                    payload={"query": title, "location": location},
                    source="user_discovery_input",
                    context_data={
                        "title": title,
                        "location": location,
                        "execution_mode": mode_value,
                    },
                )
                self.db.queue_task(task)
                count += 1
        return count

    def _seed_link_tasks(self, request: SessionRequest) -> int:
        """The ONE link seeder — creates RESOLVE_JOB_URL tasks from URLs.

        Replaces the legacy ``_seed_direct_apply_tasks`` /
        ``_seed_vet_tasks`` pair. All four legacy literals are derived:

            priority      = request.seed_priority (1 when vetting is skipped,
                            3 otherwise — preserves the legacy 1-vs-3 split)
            next_task     = "APPLY" when the mode applies without vetting,
                            "VET" otherwise
            skip_vetting  = same predicate as next_task
            source        = "user_direct_input" vs "user_vet_input"
        """
        applies_directly = (
            not request.execution_mode.includes_vetting
            and request.execution_mode.includes_application
        )
        skip_vetting = applies_directly
        next_task = "APPLY" if applies_directly else "VET"
        priority = request.seed_priority
        source = "user_direct_input" if skip_vetting else "user_vet_input"
        mode_value = request.execution_mode.value

        count = 0
        for url in request.urls:
            task = WorkUnit(
                priority=priority,
                task_type=TaskType.RESOLVE_JOB_URL,
                payload={
                    "url": url,
                    "next_task": next_task,
                    "skip_vetting": skip_vetting,
                },
                source=source,
                context_data={
                    "skip_vetting": skip_vetting,
                    "execution_mode": mode_value,
                },
            )
            self.db.queue_task(task)
            count += 1

        logger.info(
            "Queued %d link-resolution tasks | next_task=%s priority=%d",
            count,
            next_task,
            priority,
        )
        return count

    def _seed_company_urls(self, urls: tuple[str, ...]) -> int:
        """Creates DISCOVER_COMPANY tasks from careers-page URLs."""
        count = 0
        for url in urls:
            task = WorkUnit(
                priority=4,
                task_type=TaskType.DISCOVER_COMPANY,
                payload={
                    "careers_url": url,
                    "company_name": "Unknown",
                },
                source="user_company_input",
            )
            self.db.queue_task(task)
            count += 1

        logger.info("Queued %d company discovery tasks", count)
        return count

    # ── Legacy private seeders (thin shims; identical behavior) ─────────────

    def _seed_discovery_tasks(self, raw_input: str) -> int:
        """DEPRECATED shim — delegates to :meth:`_seed_search_tasks`.

        Reads ``_LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.SEARCH]`` — the
        SAME table the dict shim reads — so 'discovery' resolves to exactly
        one execution_mode no matter which door the caller uses.
        """
        keywords = tuple(t.strip() for t in raw_input.split(",") if t.strip())
        return self._seed_search_tasks(
            SessionRequest(
                entry=EntryPoint.SEARCH,
                execution_mode=_LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.SEARCH],
                keywords=keywords,
            )
        )

    def _seed_direct_apply_tasks(self, raw_input: str) -> int:
        """DEPRECATED shim — the merged seeder with the table-derived apply mode.

        Reads ``_LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.DIRECT_URLS]`` —
        the SAME table the dict shim reads — so 'direct' resolves to exactly
        one execution_mode no matter which door the caller uses. Produces
        exactly the legacy payloads: priority 1, next_task APPLY,
        skip_vetting True, source "user_direct_input".
        """
        return self._seed_link_tasks(
            SessionRequest(
                entry=EntryPoint.DIRECT_URLS,
                execution_mode=_LEGACY_ENTRY_TO_EXECUTION_MODE[
                    EntryPoint.DIRECT_URLS
                ],
                urls=tuple(self._parse_links(raw_input)),
            )
        )

    def _seed_vet_tasks(self, raw_input: str) -> int:
        """DEPRECATED shim — the merged seeder with the table-derived vet mode.

        Reads ``_LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.VET_URLS]`` —
        the SAME table the dict shim reads — so legacy 'vet' resolves to
        exactly one execution_mode no matter which door the caller uses.
        It previously hardcoded FULL_PIPELINE here while the table said
        otherwise: two doors, two answers, one label. That is now impossible
        by construction. Produces exactly the legacy payloads: priority 3,
        next_task VET, skip_vetting False, source "user_vet_input".
        """
        return self._seed_link_tasks(
            SessionRequest(
                entry=EntryPoint.VET_URLS,
                execution_mode=_LEGACY_ENTRY_TO_EXECUTION_MODE[
                    EntryPoint.VET_URLS
                ],
                urls=tuple(self._parse_links(raw_input)),
            )
        )

    def _seed_company_tasks(self, raw_input: str) -> int:
        """DEPRECATED shim — delegates to :meth:`_seed_company_urls`.

        Builds the request with ``_LEGACY_ENTRY_TO_EXECUTION_MODE
        [EntryPoint.COMPANY_PAGES]`` — the SAME table the dict shim reads —
        so 'company' resolves to exactly one execution_mode no matter which
        door the caller uses.
        """
        request = SessionRequest(
            entry=EntryPoint.COMPANY_PAGES,
            execution_mode=_LEGACY_ENTRY_TO_EXECUTION_MODE[
                EntryPoint.COMPANY_PAGES
            ],
            urls=tuple(self._parse_links(raw_input)),
        )
        return self._seed_company_urls(request.urls)

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
    # AUTONOMY CONTROL (stage E1)
    # =========================================================================

    def autonomy(self) -> bool:
        """True when THIS session's policy will submit without asking.

        Computed at this controller's construction from the checkpoints the
        interrupt policy was built from. The policy is frozen at composition
        and nothing rebuilds it, so this answer cannot change during the
        session — it is the "off is off" guarantee made queryable. When
        False, every submission is gated by a recorded human answer (or
        blocked when no approver is wired); when True, submissions are
        authorised by policy and stamped AnsweredBy.POLICY in the evidence
        record.
        """
        return self._autonomy_at_construction

    def set_autonomy(
        self, enabled: bool, acknowledgements: tuple[str, ...] = ()
    ) -> bool:
        """Configure whether FUTURE sessions submit without asking.

        Writes the checkpoint list to the active profile and persists it via
        the profile repository. This NEVER touches the current session's
        interrupt policy — a session's behaviour cannot change after its
        composition; the new value applies to the next session built from
        this profile (the next Start in the GUI, the next run in the CLI).
        Enabling requires two acknowledgements (the surfaces show two
        differently-worded warnings); without them this returns False and
        changes nothing.

        Args:
            enabled: True to submit without per-submission review; False to
                restore the review default.
            acknowledgements: The surfaces' confirmation tokens. Two are
                required to enable; none to disable.

        Returns:
            True when applied and persisted; False when refused.

        Raises:
            RuntimeError: When no profile repository is wired — an
                in-memory-only change would vanish on restart.
        """
        if self._profile_repo is None:
            raise RuntimeError(
                "no profile repository is wired to this controller — autonomy "
                "cannot be persisted. Build the controller via "
                "build_session_controller(profile, profile_repo=repo)."
            )
        return apply_autonomy(
            self.registry.get_active_profile(),
            self._profile_repo,
            enabled,
            acknowledgements,
        )

    # =========================================================================
    # STATUS POLLING — typed surface (UIPort)
    # =========================================================================

    def snapshot(self) -> SessionSnapshot:
        """Returns the every-500-ms poll view as typed data.

        Never None and never raises for "no session" — when no session is
        active the state is NO_SESSION with zeroed counters (the
        null-object ruling in domain/ports/ui_port.py).
        """
        stats = self.orchestrator.context.stats
        queue = self.get_queue_stats()
        return SessionSnapshot(
            state=self._view_state(),
            jobs_discovered=int(getattr(stats, "jobs_discovered", 0) or 0),
            jobs_vetted=int(getattr(stats, "jobs_vetted", 0) or 0),
            applications_submitted=int(
                getattr(stats, "applications_submitted", 0) or 0
            ),
            applications_failed=int(getattr(stats, "applications_failed", 0) or 0),
            queue_pending=int(queue.get("pending", 0) or 0),
            pending_approvals=len(self._pending_approvals),
            duration_seconds=_safe_duration_seconds(stats),
            current_task=self._current_task_label(),
            autonomy_enabled=self.autonomy(),
        )

    def summary(self) -> SessionSummary:
        """Returns the end-of-session results view as typed data.

        Built from the orchestrator's PUBLIC context stats plus the
        controller's event-fed SessionReport — never from the private
        orchestrator report. Never None; NO_SESSION when idle.

        The discovered list is read from job_history for this session's id,
        so it is truthful even when vetting/application never ran
        (DISCOVER_ONLY) and even if the session died mid-run.
        """
        stats = self.orchestrator.context.stats
        report = self._report
        return SessionSummary(
            state=self._view_state(),
            jobs_discovered=int(getattr(stats, "jobs_discovered", 0) or 0),
            jobs_vetted=int(getattr(stats, "jobs_vetted", 0) or 0),
            jobs_passed_vetting=report.pending_jobs_to_apply_for,
            applications_attempted=report.applications_completed,
            applications_submitted=report.applications_submitted,
            applications_failed=report.applications_failed,
            submissions_blocked_by_gate=report.submissions_blocked_by_gate,
            gate_block_remedy=report.gate_block_remedy,
            success_rate=report.success_rate,
            duration_seconds=_safe_duration_seconds(stats),
            total_task_duration_seconds=report.total_task_duration_seconds,
            average_application_seconds=report.average_application_seconds,
            submitted=tuple(
                SubmittedApplication(
                    url=record.job_url,
                    company=record.company,
                    outcome=record.outcome,
                )
                for record in report.applications
                if record.outcome in ("SUBMITTED", "PROBABLY_SUBMITTED")
            ),
            discovered=self._load_discovered_jobs(),
            report_path=report.report_path,
            autonomy_enabled=self.autonomy(),
        )

    def _load_discovered_jobs(self) -> tuple[DiscoveredJob, ...]:
        """Reads this session's discovered jobs from job_history.

        Degrades to an empty tuple when the read is unavailable (e.g. a
        mock database in tests, or a history read that fails) — a results
        view must never break because history could not be loaded.
        """
        try:
            session_id = str(self.orchestrator.context.session_id)
            rows = self.db.get_jobs_for_session(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "SessionController: discovered-job history unavailable | %s", exc
            )
            return ()
        return tuple(
            DiscoveredJob(
                title=str(getattr(j, "title", "") or ""),
                company=str(getattr(j, "company", "") or ""),
                url=str(getattr(j, "url", "") or ""),
                source=str(getattr(j, "source", "") or ""),
            )
            for j in rows
        )

    def queue_snapshot(self) -> QueueSnapshot:
        """Returns work-queue status counts as typed data."""
        stats = self.get_queue_stats()
        return QueueSnapshot(
            pending=int(stats.get("pending", 0) or 0),
            in_progress=int(stats.get("in_progress", 0) or 0),
            completed=int(stats.get("completed", 0) or 0),
            failed=int(stats.get("failed", 0) or 0),
            skipped=int(stats.get("skipped", 0) or 0),
            permanently_failed=int(stats.get("permanently_failed", 0) or 0),
        )

    def pending_approvals(self) -> tuple[ApprovalRequest, ...]:
        """Returns all currently open HITL gates as typed data."""
        return tuple(
            ApprovalRequest(
                context_id=str(payload.get("context_id", "")),
                checkpoint=str(payload.get("checkpoint", "")),
                question=str(payload.get("question", "")),
                options=tuple(str(o) for o in payload.get("options", ())),
            )
            for payload in self.get_pending_approvals()
        )

    def recent_events(self, limit: int = 50) -> tuple[SessionEventRecord, ...]:
        """Returns the most recent session events, oldest first.

        Each record carries a projected ActivityKind (never the raw
        internal Event) and a rendered sentence naming the job title and
        company where applicable — never the applicant's name, email,
        phone, or address. Empty tuple when no session exists or no events
        have been recorded yet.
        """
        if limit <= 0:
            return ()
        events = list(self._recent_events)
        return tuple(events[-limit:])

    # =========================================================================
    # STATUS POLLING — legacy dict surface (kept for the dashboards)
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Returns a legacy stats dict, projected from the typed summary.

        CHANGED in this stage: this method no longer touches the
        orchestrator's private session report. The dict is projected from
        :meth:`summary`, which is built from public context stats and the
        controller's event-fed SessionReport.

        Keys preserved for the dashboards: jobs_found, jobs_vetted,
        jobs_passed_vetting, applications_attempted, applications_submitted,
        applications_failed, submissions_blocked_by_gate, gate_block_remedy,
        session_duration_seconds, submitted_job_urls, submitted_companies,
        success_rate, total_task_duration_seconds,
        average_application_seconds, and the backward-compatible dashboard
        keys jobs_discovered, duration_str, report_path.

        Disclosed differences from the saved report: duration values are
        now LIVE during the session (the saved report froze them at
        teardown); report_path is None here (the saved file's path is only
        known to the orchestrator's teardown); dedupe-skip records are not
        in this view's attempted count.
        """
        summary = self.summary()
        return {
            "jobs_found": summary.jobs_discovered,
            "jobs_vetted": summary.jobs_vetted,
            "jobs_passed_vetting": summary.jobs_passed_vetting,
            "applications_attempted": summary.applications_attempted,
            "applications_submitted": summary.applications_submitted,
            "applications_failed": summary.applications_failed,
            "submissions_blocked_by_gate": summary.submissions_blocked_by_gate,
            "gate_block_remedy": summary.gate_block_remedy,
            "session_duration_seconds": summary.duration_seconds,
            "submitted_job_urls": list(summary.submitted_urls),
            "submitted_companies": summary.submitted_companies,
            "success_rate": summary.success_rate,
            "total_task_duration_seconds": summary.total_task_duration_seconds,
            "average_application_seconds": summary.average_application_seconds,
            # Backward-compatible keys (used by GUI/CLI dashboard polling)
            "jobs_discovered": summary.jobs_discovered,
            "duration_str": summary.duration_str,
            "report_path": (
                str(summary.report_path) if summary.report_path else None
            ),
        }

    def get_current_state(self) -> str:
        """Returns the current agent state as a string.

        Safe to call from any thread. Enum reads are atomic in CPython.

        Returns:
            The AgentState name, e.g. "RUNNING", "DISCOVERING", "IDLE".
        """
        return self.orchestrator.state_machine.current_state.name

    @property
    def is_running(self) -> bool:
        """Returns True if the orchestrator thread is alive.

        Structurally satisfies UIPort.is_running (a property satisfies a
        runtime_checkable Protocol method member).
        """
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
    # CUSTODY — results export, profile export, session history
    # =========================================================================

    def export_session_results(self, destination_dir: Path, *, overwrite: bool = False) -> Path:
        """Writes this session's discovered jobs to a CSV in the chosen directory.

        The deliverable of a collect-links run: title, company, URL. The
        ruling for collect runs is show-on-screen, export-on-request — this
        method only runs because the user asked, and nothing else in AA
        writes a results file.

        Guards:
            - The destination must be an existing directory (no creating
              paths the user didn't pick, no path traversal via "..").
            - An existing results file is only replaced when the caller
              passed ``overwrite=True`` explicitly.

        Args:
            destination_dir: An existing directory chosen by the user.
            overwrite: Replace an existing results CSV for this session.

        Returns:
            The written file path.
        """
        destination_dir = Path(destination_dir)
        if ".." in destination_dir.parts:
            raise ValueError(
                "destination contains '..' — exports only write inside a plain directory"
            )
        if not destination_dir.is_dir():
            raise ValueError(
                f"destination is not an existing directory: {destination_dir}"
            )

        session_id = str(self.orchestrator.context.session_id)
        target = destination_dir / f"aa_results_{session_id[:8]}.csv"
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"{target} already exists — pass overwrite=True to replace it"
            )

        jobs = self.db.get_jobs_for_session(session_id)
        rows = [["title", "company", "url", "source"]]
        rows.extend(
            [
                str(getattr(j, "title", "") or ""),
                str(getattr(j, "company", "") or ""),
                str(getattr(j, "url", "") or ""),
                str(getattr(j, "source", "") or ""),
            ]
            for j in jobs
        )
        self._write_csv_atomic(target, rows)
        logger.info("Session results exported: %s", target)
        return target

    @staticmethod
    def _write_csv_atomic(target: Path, rows: list[list[str]]) -> None:
        """Write CSV rows to target atomically (temp file → rename)."""
        tmp = target.with_name(target.name + ".tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerows(rows)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def export_profile(self, name: str, destination_dir: Path, *, overwrite: bool = False) -> Path:
        """Exports a stored profile via the profile repository.

        Delegates to the ProfileRepositoryPort wired at construction. The
        repository owns the plaintext export, the overwrite guard, the
        traversal guard, and the Never-Touch-The-Store guard — the stored
        profile and its encryption state are never touched.

        Raises:
            RuntimeError: When no profile repository is wired to this controller.
        """
        if self._profile_repo is None:
            raise RuntimeError(
                "no profile repository is wired to this controller — profile "
                "export is unavailable. Build the controller via "
                "build_session_controller(profile, profile_repo=repo)."
            )
        return self._profile_repo.export_profile(
            name, Path(destination_dir), overwrite=overwrite
        )

    def list_session_history(self) -> tuple[SessionHistoryEntry, ...]:
        """Reads past session reports from the reports directory, newest first.

        Each entry carries the session's completion outcome and its
        discovery/vetting/application counts. Reports written before
        ``completion_state`` existed read as "unknown" rather than guessing.
        Unreadable files are skipped by SessionReport.list_reports, never
        surfaced as errors.
        """
        entries: list[SessionHistoryEntry] = []
        for data in SessionReport.list_reports(USER_DATA_DIR / "reports"):
            discovery = data.get("discovery") or {}
            vetting = data.get("vetting") or {}
            applications = data.get("applications") or {}
            try:
                entries.append(
                    SessionHistoryEntry(
                        session_id=str(data.get("session_id", "")),
                        profile_name=str(data.get("profile_name", "")),
                        mode=str(data.get("mode", "discovery")),
                        completion_state=str(data.get("completion_state", "unknown")),
                        started_at=str(data.get("started_at", "")),
                        finished_at=(
                            str(data["finished_at"]) if data.get("finished_at") else None
                        ),
                        duration_seconds=float(data.get("duration_seconds") or 0.0),
                        jobs_found=int(discovery.get("raw_results_found", 0) or 0),
                        jobs_vetted=int(vetting.get("jobs_approved", 0) or 0),
                        applications_submitted=int(applications.get("submitted", 0) or 0),
                        applications_failed=int(applications.get("failed", 0) or 0),
                        report_path=(
                            Path(data["report_path"]) if data.get("report_path") else None
                        ),
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "SessionController: skipping malformed history entry | %s", exc
                )
                continue
        return tuple(entries)

    # =========================================================================
    # VIEW-STATE HELPERS
    # =========================================================================

    def _view_state(self) -> SessionViewState:
        """Computes the UI-facing session state.

        STOPPED/FAILED map through the FSM mapping (COMPLETE/FAILED).
        A live thread maps the current AgentState. No thread but seeded
        tasks means READY; otherwise NO_SESSION.
        """
        state = self.orchestrator.state_machine.current_state
        if state in (AgentState.STOPPED, AgentState.FAILED):
            return view_state_from_agent_state(state.name)
        if self.is_running:
            return view_state_from_agent_state(state.name)
        if self._session_seeded:
            return SessionViewState.READY
        return SessionViewState.NO_SESSION

    def _current_task_label(self) -> str:
        """A short human-readable label for the current work unit.

        This is the typed home for what the CLI dashboard reads directly
        from orchestrator.context.current_work_unit today
        (cli/dashboard.py:170, its own P2-cleanup comment).
        """
        try:
            task = self.orchestrator.context.current_work_unit
        except Exception:  # noqa: BLE001
            return ""
        if task is None:
            return ""
        try:
            detail = _task_detail(task)
            name = task.task_type.name
            return f"{name} — {detail}" if detail else name
        except Exception:  # noqa: BLE001
            return ""

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _resolve_default_location(self) -> str:
        """Resolves the user's preferred default location from the profile.

        Retained for backward compatibility; no current call site (the
        search seeder uses the full preferred_locations list, not a single
        default).

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

    def get_pending_approvals(self) -> list[dict]:
        """Returns a snapshot of the payloads of every currently open HITL gate.

        A dashboard that binds AFTER a gate was published cannot see the
        publish — but it can read this state and render the open gate
        immediately. This is what makes subscriber order irrelevant: the
        gate is readable state, not a one-shot broadcast. Returned payloads
        are copies so callers cannot mutate controller state.

        Returns:
            A list of payload dicts (context_id, checkpoint, question,
            options), one per open gate. Empty when no gate is open.
        """
        with self._approvals_lock:
            return [dict(entry[2]) for entry in self._pending_approvals.values()]

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
        engine can continue rather than hanging indefinitely — and NOW records
        that machine answer as ``AnsweredBy.TIMEOUT`` in the approval-evidence
        record (previously it was a WARNING log line and nothing else).

        A WAITING feed record is written immediately after the request is
        published (D1) — a late-binding reader sees "the agent asked" before
        it sees the answer.

        Args:
            question: Human-readable description of what needs approval.
            options: List of valid choices; ``"skip"`` is appended if absent.
            checkpoint: Checkpoint name for the payload (informational).
            timeout: Seconds to wait for a response (default 300 = 5 minutes).

        Returns:
            The option string chosen by the user, or ``"skip"`` on timeout.
        """
        if "skip" not in options:
            options = list(options) + ["skip"]

        context_id = str(uuid.uuid4())
        gate = threading.Event()
        choice_holder: list[str] = (
            []
        )  # mutable container so the grant side can write

        payload = {
            "context_id": context_id,
            "checkpoint": checkpoint,
            "question": question,
            "options": options,
        }

        with self._approvals_lock:
            self._pending_approvals[context_id] = (gate, choice_holder, payload)

        try:
            self.orchestrator.event_bus.publish(
                Event.HUMAN_APPROVAL_REQUESTED, payload
            )
        except Exception as exc:
            logger.warning(
                "SessionController: could not publish HITL event | %s", exc
            )

        self._record_stream(
            _EVENT_KIND_MAP[Event.HUMAN_APPROVAL_REQUESTED],
            f"Waiting for you: {str(question)[:80]}",
        )

        logger.info(
            "SessionController: HITL gate open | context_id=%s question=%r "
            "subscribers=%s",
            context_id,
            question,
            self.orchestrator.event_bus.subscriber_count(
                Event.HUMAN_APPROVAL_REQUESTED
            ),
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
            self._record_approval_answer(
                context_id, "skip", AnsweredBy.TIMEOUT, checkpoint
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
        """Legacy entry point — a human answered from the UI thread.

        Delegates to :meth:`answer_approval` with ``AnsweredBy.HUMAN``.
        """
        return self.answer_approval(context_id, choice, AnsweredBy.HUMAN)

    def answer_approval(
        self,
        context_id: str,
        choice: str,
        answered_by: AnsweredBy,
    ) -> bool:
        """Resolves a pending HITL gate AND records who answered.

        Stricter than the legacy provide_approval in one way: the choice
        must be one of the options the gate was opened with — an out-of-band
        answer does not unblock the gate and is not recorded (evidence
        integrity for a research record).

        Args:
            context_id: The UUID from the HUMAN_APPROVAL_REQUESTED payload.
            choice: The option selected.
            answered_by: Who produced the answer (HUMAN today; POLICY is
                reserved for the workflow's policy path in a later stage).

        Returns:
            True if the gate was found, the choice was in-band, and the
            gate was unblocked. False otherwise.
        """
        with self._approvals_lock:
            entry = self._pending_approvals.get(context_id)

        if entry is None:
            logger.warning(
                "SessionController.answer_approval: unknown context_id=%s",
                context_id,
            )
            return False

        gate, choice_holder, payload = entry
        options = list(payload.get("options", []))
        if options and choice not in options:
            logger.warning(
                "SessionController.answer_approval: choice %r is not in the "
                "gate's options %s — refusing to unblock",
                choice,
                options,
            )
            return False

        # Publish GRANTED first so orchestrator transitions state machine to
        # RUNNING (or STOPPING) BEFORE the agent thread unblocks and resumes.
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

        self._record_approval_answer(
            context_id,
            choice,
            answered_by,
            str(payload.get("checkpoint", "")),
        )

        choice_holder.append(choice)
        gate.set()

        return True

    def _record_approval_answer(
        self,
        context_id: str,
        choice: str,
        answered_by: AnsweredBy,
        checkpoint: str = "",
    ) -> None:
        """Stamps one approval outcome into the evidence record and the stream."""
        answer = ApprovalAnswer(
            context_id=context_id,
            checkpoint=checkpoint,
            choice=choice,
            answered_by=answered_by,
            at=datetime.now(timezone.utc),
        )
        self._approval_evidence[context_id] = answer
        self._record_stream(
            _EVENT_KIND_MAP[Event.HUMAN_APPROVAL_GRANTED],
            f"HITL gate closed | checkpoint={checkpoint or 'unknown'} "
            f"choice={choice!r} answered_by={answered_by.name}",
        )

    def approval_evidence(self) -> tuple[ApprovalAnswer, ...]:
        """Returns every recorded approval answer for this controller.

        Additive public query beyond the port — the research-grade record
        of who answered each HITL gate (human, timeout, or policy when the
        workflow starts stamping it in a later stage).
        """
        return tuple(self._approval_evidence.values())

    def _wire_approval_gate(self) -> None:
        """Late-binds request_approval into the ApplicationsWorkflow and the
        orchestrator.

        Called after controller construction to resolve the circular dependency:
        both the workflow and the orchestrator are built before SessionController
        exists, so the gate cannot be passed at construction time.  This method
        is called by the composition root during controller assembly.
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

        try:
            self.orchestrator.set_approval_gate(self.request_approval)
            logger.info(
                "SessionController: approval gate wired into orchestrator"
            )
        except Exception as exc:
            logger.warning(
                "SessionController: could not wire orchestrator approval "
                "gate | %s — CAPTCHA escalation will not prompt",
                exc,
            )

    # =========================================================================
    # CRASH RECOVERY
    # =========================================================================

    def _perform_startup_recovery(self) -> None:
        """Resets tasks stuck in 'IN_PROGRESS' from a previous crashed session,
        and discards browser-context-bound reactive tasks left by that session.

        Called once during construction. Two kinds of leftovers are handled:
        tasks stuck IN_PROGRESS are re-queued (their work is URL-addressable
        and can simply restart), and reactive tasks tied to a live page
        (HANDLE_CAPTCHA) are marked SKIPPED — the page they referenced was
        closed in teardown, so dispatching them would block on a phantom.
        Safe to call on a fresh database (both are no-ops when nothing exists).
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

        try:
            discarded = self.db.discard_stale_reactive_tasks()
            if discarded > 0:
                logger.warning(
                    "Discarded %d stale browser-context task(s) from a "
                    "previous session — the pages they referenced no "
                    "longer exist",
                    discarded,
                )
        except Exception as exc:
            logger.error(
                "Stale reactive task discard failed | error=%s — "
                "proceeding anyway",
                exc,
                exc_info=True,
            )

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


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────


# The label → execution-mode translation table for the legacy dict shim.
# THIS TABLE IS LOAD-BEARING, and every door reads it (the dict shim via
# _request_from_legacy_dict; every private shim reads its own row). It has
# already gone wrong twice — read the history before editing any row.
#
#   VET_URLS → VET_AND_APPLY
#       Legacy 'vet' meant "vet these URLs first, then apply to the ones
#       that pass" — the original initialize_session docstring documented
#       the mode as 'Newline-separated job URLs to vet before applying',
#       and _seed_vet_tasks said passed URLs 'become APPLY tasks
#       automatically via the orchestrator'. VET_AND_APPLY
#       (includes_vetting=True, includes_application=True) reproduces
#       exactly that: the merged seeder derives next_task="VET",
#       skip_vetting=False, priority=3, and passed jobs are enqueued for
#       application downstream.
#
#       REVISION HISTORY — this row was VET_ONLY for one revision (the
#       2026-09 label-mapping fix). That was wrong: VET_ONLY has
#       includes_application=False, which structurally prevents
#       application, silently narrowing a mode whose whole point was
#       apply-after-vetting. The enum name read like "vet, only"; the
#       legacy docstring read like "vet, then apply". The docstring wins.
#
#       VET_ONLY remains the right mode ONLY if someone deliberately wants
#       a vet mode that structurally cannot submit. That is a DIFFERENT
#       EntryPoint (its own row, its own label), not a reinterpretation of
#       this one. Do not change this row to get no-submit behavior; add
#       the entry point.
#
#   DIRECT_URLS → APPLY_ONLY
#       Legacy 'direct' and 'direct_links' meant "apply to these pasted
#       URLs immediately, no vetting" (the original _seed_direct_apply_tasks
#       produced priority 1, next_task="APPLY", skip_vetting=True).
#       APPLY_ONLY is includes_vetting=False / includes_application=True,
#       which reproduces all three: applies_directly=True, next_task="APPLY",
#       skip_vetting=True, and seed_priority yields 1.
#
#   SEARCH → FULL_PIPELINE
#       Legacy 'discovery' ran discover → vet → apply end to end.
#
#   COMPANY_PAGES → FULL_PIPELINE
#       Legacy 'company' likewise ran the full pipeline.
#
# An explicit "execution_mode" key in the legacy dict overrides the row,
# per the maintainer's instruction in the label-mapping fix.
_LEGACY_ENTRY_TO_EXECUTION_MODE: dict[EntryPoint, SessionExecutionMode] = {
    EntryPoint.SEARCH: SessionExecutionMode.FULL_PIPELINE,
    EntryPoint.DIRECT_URLS: SessionExecutionMode.APPLY_ONLY,
    EntryPoint.VET_URLS: SessionExecutionMode.VET_AND_APPLY,
    EntryPoint.COMPANY_PAGES: SessionExecutionMode.FULL_PIPELINE,
}


def _legacy_mode_label(entry: EntryPoint) -> str:
    """Maps an EntryPoint to the mode label profile validation expects.

    profile_validator treats "direct"/"apply" as apply-mode (stricter
    document checks) and everything else as discovery-tier. Preserves the
    legacy dict path's behavior exactly.
    """
    return {
        EntryPoint.SEARCH: "discovery",
        EntryPoint.DIRECT_URLS: "direct",
        EntryPoint.VET_URLS: "vet",
        EntryPoint.COMPANY_PAGES: "company",
    }[entry]


def _task_detail(task: WorkUnit) -> str:
    """Extracts a short human-readable detail string from a WorkUnit payload."""
    try:
        if hasattr(task.payload, "title") and hasattr(task.payload, "company"):
            return f"{task.payload.title[:25]} @ {task.payload.company[:20]}"
        if isinstance(task.payload, dict):
            for key in ("query", "title", "url", "careers_url"):
                val = task.payload.get(key, "")
                if val:
                    return str(val)[:50]
        return ""
    except Exception:
        return ""


def _safe_duration_seconds(stats: Any) -> float:
    """Extracts duration in seconds from an ExecutionContext stats object."""
    try:
        duration = getattr(stats, "duration", None)
        if duration is None:
            return 0.0
        return float(duration.total_seconds())
    except Exception:  # noqa: BLE001
        return 0.0
