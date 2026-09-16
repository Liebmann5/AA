"""The driving port for the UI-to-backend interface.

Why this port exists
--------------------
Two primary adapters (CLI, GUI) drive the session through the application
layer's concrete SessionController, and in several places reach past it
into orchestrator internals that are none of the UI's business:

* SessionController.get_stats() reaches self.orchestrator._session_report
  (application/services/session_controller.py:495).
* The CLI dashboard subscribes via controller.orchestrator.event_bus
  (adapters/primary/cli/dashboard.py:93) and reads
  orchestrator.context.current_work_unit directly (cli/dashboard.py:170,
  which carries its own P2-cleanup comment about it).
* The GUI dashboard does the same (adapters/primary/gui/dashboard.py:219).

The result is one untyped dict in each direction and no declared surface
at all — and the two surfaces already drifted apart (cli/wizard.py's
"direct_links" is not in the controller's dispatch table,
session_controller.py:182-187). This port is that surface, declared once,
satisfied structurally by the application layer (SessionController, wired
in Turn 2) with no wrapper class — the same precedent as
ProfileRepositoryPort, which declares ProfileRepository's full public
surface structurally. adapters_primary → domain is already a permitted
import direction (tests/test_architecture.py:119-125), so the port sits
in domain/ports where both adapters can see it. Verified.

Whole surface, deliberately: 17 methods.
-----------------------------------------
AA's idiom prefers narrow ports, but this port describes a whole surface,
not a capability, and the ProfileRepositoryPort precedent applies. The 17
methods are measured from the real consumed surface — the 11 legacy calls
both adapters actually make today (initialize_session, start, stop, pause,
resume, get_stats, get_current_state, is_running, get_queue_stats,
get_pending_approvals, provide_approval) plus one new stream query
(recent_events), plus three custody methods added when the results surface
landed (export_session_results, export_profile, list_session_history),
plus the two autonomy methods added at stage E1 (autonomy, set_autonomy).
tests/domain/test_ui_contract.py and tests/application/test_ui_port_conformance.py
pin this exact set, so growth is mechanical, not accidental. If the
consumers only ever take halves, splitting then is cheap — the types do
not change. Today SessionController already carries all 17, so one port
wins on current evidence.

Legacy → port mapping (Turn 2 wires these):
    initialize_session(ui_config: dict)   → initialize_session(SessionRequest)
    start / stop / pause / resume          → unchanged
    get_stats() → dict                     → summary() → SessionSummary
    get_current_state() → str              → snapshot().state → SessionViewState
    get_queue_stats() → dict               → queue_snapshot() → QueueSnapshot
    is_running (property)                  → is_running() → bool
    get_pending_approvals() → list[dict]   → pending_approvals() → tuple[ApprovalRequest, ...]
    provide_approval                       → unchanged
    (new)                                  → recent_events() → tuple[SessionEventRecord, ...]
    (custody)                              → export_session_results / export_profile /
                                             list_session_history
    (autonomy, E1)                         → autonomy() → bool  (read: this session's
                                             frozen answer) ; set_autonomy(enabled,
                                             acknowledgements) → bool  (write: the profile,
                                             persisted, effective next session)

Ruling: "there is no session right now" is a VALUE, not None, not an exception.
--------------------------------------------------------------------------------
snapshot(), summary(), queue_snapshot(), pending_approvals() and
recent_events() are polled by dashboards every 500 ms — before the first
session, between sessions, and after one ends. Three shapes were weighed:

* None returns: every call site branches, twice (CLI + GUI). The
  dashboards today do stats.get(key, 0) with no None check
  (cli/dashboard.py:245, gui/app.py:494); None would force edits at every
  one of those sites, and the parity pin would then have to compare two
  surfaces' branch logic instead of one shared shape.
* Raise: "no session" is the NORMAL state before the first session and
  after the last. It is not exceptional. An exception in a 500 ms poll
  loop is noise, and each adapter would still have to invent its own
  fallback view — the exact divergence this port exists to prevent.
* Null object (chosen): the satisfying side returns a fully-formed zeroed
  snapshot — SessionSnapshot(state=SessionViewState.NO_SESSION) — and
  callers never branch. The dashboards' existing get(key, 0) contract is
  preserved by construction.

Cost to the adapters: none at the type level. Between sessions both
surfaces show a zeroed dashboard, which is also the correct thing for a
first-time user to see. The one real cost is a rule: adapters read
liveness from ``state``, never from counters. That rule is what lets the
parity pin compare SHAPES mechanically (same controller state → identical
snapshot fields on both surfaces) instead of comparing branching.

AgentState has no member for "finished, choose again" — STOPPED/FAILED
are FSM-terminal, not UI states. The port therefore keeps its own
SessionViewState with the two UI-vocabulary members the FSM lacks:
NO_SESSION (never started) and COMPLETE (ended, choose again), plus READY
for "seeded but not yet started".

pending_approvals() returns an empty tuple when no gate is open (today's
behavior, session_controller.py:527).

Autonomy (stage E1)
-------------------
``autonomy()`` answers the question a user can never otherwise answer:
is THIS session going to submit without asking? It is a frozen read —
computed at the controller's composition and unable to move during the
session. ``set_autonomy()`` is the write: it changes the profile (and
persists it), never the built policy, so the guarantee "off is off" is
structural for the session's lifetime rather than a runtime promise.
Enabling requires two acknowledgements; the port refuses without them, so
no surface can skip a warning by construction.

Types only
----------
Every parameter and return type in this port is a frozen DTO from
ui_contract, an Enum, a Path, or a builtin. No UserProfile, no driver, no
repository, no orchestrator, no callback. tests/domain/test_ui_contract.py
enforces it mechanically against this Protocol, and proves the checker
discriminates by running it against the CURRENT SessionController, which
it rejects for dict[str, Any] (initialize_session, get_stats) and
list[dict] (get_pending_approvals).

A subscribe/callback stream was rejected for this same reason: a
Callable parameter violates the no-live-objects rule, and both dashboards
already poll — a polled recent_events() query is the data-shaped stream
that matches the existing architecture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from auto_apply.domain.models.ui_contract import (
    ApprovalRequest,
    QueueSnapshot,
    SessionEventRecord,
    SessionHistoryEntry,
    SessionRequest,
    SessionSnapshot,
    SessionSummary,
)


@runtime_checkable
class UIPort(Protocol):
    """The complete session surface a UI needs: commands, queries, a stream.

    Satisfied structurally by the application layer (SessionController in
    Turn 2) — no wrapper class, following the ProfileRepositoryPort
    precedent of declaring a complete public surface once.
    """

    # ── Commands ────────────────────────────────────────────────────────────

    def initialize_session(self, request: SessionRequest) -> int:
        """Seed the work queue from a typed request. Returns the task count."""
        ...

    def start(self) -> None:
        """Start the orchestrator thread. No-op if already running."""
        ...

    def stop(self) -> None:
        """Signal graceful shutdown and join the orchestrator thread."""
        ...

    def pause(self) -> None:
        """Pause task dispatching without tearing down the session."""
        ...

    def resume(self) -> None:
        """Resume task dispatching after a pause."""
        ...

    def provide_approval(self, context_id: str, choice: str) -> bool:
        """Resolve one open HITL gate.

        Returns:
            True if the gate was found and unblocked. False if context_id
            is unknown (already timed out, duplicate call).
        """
        ...

    # ── Custody commands ────────────────────────────────────────────────────

    def export_session_results(self, destination_dir: Path, *, overwrite: bool = False) -> Path:
        """Write the current session's discovered jobs to a CSV in the
        given directory.

        Only writes because the user asked — the ruling for collect runs is
        show-on-screen, export-on-request, and nothing reaches a file
        otherwise. Refuses to overwrite without the flag and refuses a
        path-traversal destination.

        Returns:
            The written file path.
        """
        ...

    def export_profile(self, name: str, destination_dir: Path, *, overwrite: bool = False) -> Path:
        """Export a stored profile as plaintext JSON to a user-chosen directory.

        Symmetric with import_profile: a person who can bring a profile in
        can take one away. Delegates to the profile repository; the stored
        profile and its encryption state are never touched.

        Returns:
            The written file path.
        """
        ...

    # ── Autonomy (stage E1) ─────────────────────────────────────────────────

    def set_autonomy(self, enabled: bool, acknowledgements: tuple[str, ...] = ()) -> bool:
        """Configure whether FUTURE sessions submit without asking.

        Writes the checkpoint list to the active profile and persists it.
        The current session's interrupt policy is never touched: a session's
        behaviour cannot change after composition; the new value applies to
        the next session built from this profile (the next Start in the
        GUI, the next run in the CLI). Enabling requires two
        acknowledgements — the surfaces show two differently-worded
        warnings; without them this returns False and changes nothing.

        Returns:
            True when applied and persisted; False when refused for
            missing acknowledgements.
        """
        ...

    # ── Queries ─────────────────────────────────────────────────────────────

    def snapshot(self) -> SessionSnapshot:
        """The every-500-ms poll view. Never None; NO_SESSION when idle."""
        ...

    def summary(self) -> SessionSummary:
        """The end-of-session results view. Never None; NO_SESSION when idle."""
        ...

    def queue_snapshot(self) -> QueueSnapshot:
        """Work-queue status counts. Zeroed when no session exists."""
        ...

    def pending_approvals(self) -> tuple[ApprovalRequest, ...]:
        """All currently open HITL gates. Empty tuple when none are open."""
        ...

    def is_running(self) -> bool:
        """True while the orchestrator thread is alive."""
        ...

    def autonomy(self) -> bool:
        """True when THIS session's policy will submit without asking.

        Frozen at this controller's composition — the current run's answer,
        and it cannot change during the run. When False, every submission
        is gated by a recorded human answer (or blocked when no approver is
        wired); when True, submissions are authorised by policy and stamped
        AnsweredBy.POLICY in the evidence record.
        """
        ...

    def list_session_history(self) -> tuple[SessionHistoryEntry, ...]:
        """Past sessions read from the reports directory, newest first.

        Each entry carries the session's completion outcome and its
        discovered/vetted/applied counts. Empty tuple when no reports exist.
        """
        ...

    # ── Stream ──────────────────────────────────────────────────────────────

    def recent_events(self, limit: int = 50) -> tuple[SessionEventRecord, ...]:
        """The most recent session events, oldest first, for the live feed.

        Each record carries a projected ActivityKind — a small, UI-sized
        vocabulary — rather than the raw internal Event, plus a rendered
        sentence. Sentences name the job title and company where applicable
        and never the applicant's name, email, phone, or address.

        The satisfying side maintains a bounded buffer of recent events.
        Empty tuple when no session exists.
        """
        ...
