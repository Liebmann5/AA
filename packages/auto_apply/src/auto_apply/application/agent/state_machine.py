"""Finite State Machine governing the AgentOrchestrator's operational states.

This module defines every valid state the agent can be in, every valid
transition between states, and the guard conditions that must pass before a
transition is allowed. All state transition logic lives here and nowhere else.

Why a Formal State Machine:
    Without an FSM, state management sprawls across the codebase as a
    collection of boolean flags (self.running, self.paused, self.recovering...)
    that interact in ways that are hard to reason about and easy to break.
    An FSM makes the contract explicit: the agent is always in exactly one
    state, transitions are only allowed along defined edges, and any attempt
    to make an invalid transition is caught and logged immediately.

AgentState is the upgrade of the old two-flag system:
    Old:  self.running=True, self.paused=False → some state
    New:  self.state == AgentState.RUNNING      → unambiguous

Transition Rules:
    A transition from state A to state B is valid if and only if:
    1. The (A, B) pair exists in the VALID_TRANSITIONS table, AND
    2. All guard conditions registered for that transition return True.

    If a guard fails, the transition is blocked and the current state is
    unchanged. The caller receives False from transition_to() and can
    handle it appropriately (log a warning, retry, abort).

Adding a New State:
    1. Add the state to AgentState.
    2. Add all valid transitions to and from it in VALID_TRANSITIONS.
    3. Add any required guards in StateMachine._register_guards().
    4. Add a corresponding Event to core/events.py if the UI needs to react.
    5. Add a test in tests/agent/test_state_machine.py.

Example:
    >>> from agent.state_machine import StateMachine, AgentState
    >>>
    >>> sm = StateMachine(initial_state=AgentState.IDLE)
    >>> sm.current_state
    AgentState.IDLE
    >>>
    >>> sm.transition_to(AgentState.INITIALIZING)
    True
    >>> sm.transition_to(AgentState.APPLYING)  # Invalid jump
    False
    >>> sm.current_state
    AgentState.INITIALIZING
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Every operational state the AgentOrchestrator can occupy.

    The agent is always in exactly one of these states. UI components,
    health monitors, and the orchestrator itself use this to understand
    what is happening and what is allowed next.
    """

    # ── Startup ───────────────────────────────────────────────────────────
    IDLE = auto()
    """No session is active. The agent is waiting for input.
    This is both the initial state and the state after a session completes
    with the work queue empty but the application still running.
    """

    INITIALIZING = auto()
    """Session setup is in progress: registry build, policy enforcement,
    browser cascade initialization, checkpoint recovery check, work queue seeding.
    """

    # ── Active Execution ──────────────────────────────────────────────────
    RUNNING = auto()
    """The main event loop is active and processing tasks from the queue.
    This is the normal operating state during a job hunt session.
    """

    DISCOVERING = auto()
    """A DISCOVER or DISCOVER_COMPANY task is actively executing.
    The DiscoveryEngine has the browser and is navigating search results.
    """

    VETTING = auto()
    """A VET task is actively executing.
    The VettingEngine is analyzing a job's description against the user profile.
    """

    APPLYING = auto()
    """An APPLY task batch is actively executing.
    The ApplicationEngine has the browser and is filling a form.
    """

    # ── Interruption ──────────────────────────────────────────────────────
    PAUSED = auto()
    """Execution is temporarily suspended. The browser session remains alive.
    May be caused by: user request, network loss, CAPTCHA requiring manual solve,
    or a logic conflict that requires user input.
    """

    RESOLVING_CAPTCHA = auto()
    """A CAPTCHA has been detected and the resolution service is active.
    Transitions to RUNNING if auto-resolved, or PAUSED if manual solve needed.
    """

    RESOLVING_LOGIC_CONFLICT = auto()
    """A form field conflict was detected that requires user input to resolve.
    Example: "Choose only 1" but the profile has 4 matching values.
    The GUI presents the options; the user picks one; execution resumes.
    """

    # ── Human-in-the-loop ────────────────────────────────────────────────
    AWAITING_HUMAN = auto()
    """The agent is paused at a HITL checkpoint waiting for user approval.

    Published as HUMAN_APPROVAL_REQUESTED event. Transitions back to RUNNING
    when the user provides a choice, or to STOPPING if the user elects to stop.
    """

    # ── Recovery ─────────────────────────────────────────────────────────
    ERROR_RECOVERY = auto()
    """A recoverable error occurred (browser crash, network timeout, etc.).
    The orchestrator is attempting self-healing before resuming RUNNING.
    """

    # ── Shutdown ──────────────────────────────────────────────────────────
    STOPPING = auto()
    """A stop signal has been received. The current task will complete before
    the loop exits. No new tasks will be dispatched.
    """

    STOPPED = auto()
    """The session has ended. Browser is closed, final checkpoint saved,
    SESSION_COMPLETE event published. Terminal state.
    """

    FAILED = auto()
    """The session ended due to an unrecoverable error (e.g., all browsers
    exhausted in BrowserCascade, persistent network failure). Terminal state.
    """


# ─────────────────────────────────────────────────────────────────────────────
# VALID TRANSITIONS TABLE
#
# The set of (from_state, to_state) pairs that are structurally allowed.
# A transition not listed here is invalid regardless of context or guards.
# Guards may further restrict listed transitions but cannot expand them.
#
# Read as: "From state X, it is valid to transition to state Y."
# ─────────────────────────────────────────────────────────────────────────────
VALID_TRANSITIONS: frozenset[tuple[AgentState, AgentState]] = frozenset({

    # ── Startup sequence ─────────────────────────────────────────────────
    (AgentState.IDLE,           AgentState.INITIALIZING),
    (AgentState.INITIALIZING,   AgentState.RUNNING),
    (AgentState.INITIALIZING,   AgentState.FAILED),      # Failed during setup

    # ── Normal execution cycle ────────────────────────────────────────────
    (AgentState.RUNNING,        AgentState.DISCOVERING),
    (AgentState.RUNNING,        AgentState.VETTING),
    (AgentState.RUNNING,        AgentState.APPLYING),
    (AgentState.RUNNING,        AgentState.IDLE),         # Queue drained
    (AgentState.RUNNING,        AgentState.PAUSED),
    (AgentState.RUNNING,        AgentState.STOPPING),
    (AgentState.RUNNING,        AgentState.ERROR_RECOVERY),

    # ── Domain engine → back to running ──────────────────────────────────
    (AgentState.DISCOVERING,    AgentState.RUNNING),
    (AgentState.DISCOVERING,    AgentState.ERROR_RECOVERY),
    (AgentState.DISCOVERING,    AgentState.PAUSED),
    # Queue-exhausted path: when all DISCOVER tasks have permanently failed or
    # finished, the orchestrator may still be in DISCOVERING (if the handler
    # raised before its trailing RUNNING transition). The main loop reaches
    # IDLE only after `get_next_task()` returns None and the application
    # buffer is empty — same precondition as the RUNNING→IDLE edge above.
    (AgentState.DISCOVERING,    AgentState.IDLE),

    (AgentState.VETTING,        AgentState.RUNNING),
    (AgentState.VETTING,        AgentState.ERROR_RECOVERY),
    (AgentState.VETTING,        AgentState.PAUSED),

    (AgentState.APPLYING,       AgentState.RUNNING),
    (AgentState.APPLYING,       AgentState.RESOLVING_CAPTCHA),
    (AgentState.APPLYING,       AgentState.RESOLVING_LOGIC_CONFLICT),
    (AgentState.APPLYING,       AgentState.ERROR_RECOVERY),
    (AgentState.APPLYING,       AgentState.PAUSED),

    # ── Interruption handling ─────────────────────────────────────────────
    (AgentState.PAUSED,         AgentState.RUNNING),
    (AgentState.PAUSED,         AgentState.STOPPING),
    (AgentState.PAUSED,         AgentState.FAILED),       # Timeout while paused

    # Bible §5.2 documents RUNNING → RESOLVING_CAPTCHA → RUNNING; this edge
    # was missing from the table even though _handle_captcha transitions
    # unconditionally (HANDLE_CAPTCHA tasks are dispatched at RUNNING, since
    # every handler restores RUNNING before the next dequeue). No other
    # inbound edges are added: DISCOVERING/VETTING/IDLE cannot dispatch a
    # HANDLE_CAPTCHA task by construction.
    (AgentState.RUNNING,        AgentState.RESOLVING_CAPTCHA),
    (AgentState.RESOLVING_CAPTCHA,          AgentState.RUNNING),   # Auto-resolved
    (AgentState.RESOLVING_CAPTCHA,          AgentState.PAUSED),    # Needs manual
    (AgentState.RESOLVING_CAPTCHA,          AgentState.FAILED),
    (AgentState.RESOLVING_CAPTCHA,          AgentState.STOPPING),  # Stop during resolution

    (AgentState.RESOLVING_LOGIC_CONFLICT,   AgentState.RUNNING),   # User chose
    (AgentState.RESOLVING_LOGIC_CONFLICT,   AgentState.PAUSED),
    (AgentState.RESOLVING_LOGIC_CONFLICT,   AgentState.STOPPING),  # User cancels

    # ── Human-in-the-loop pause ──────────────────────────────────────
    (AgentState.RUNNING,                    AgentState.AWAITING_HUMAN),
    (AgentState.APPLYING,                   AgentState.AWAITING_HUMAN),
    (AgentState.RESOLVING_LOGIC_CONFLICT,   AgentState.AWAITING_HUMAN),
    (AgentState.AWAITING_HUMAN,             AgentState.RUNNING),    # User approved (generic)
    (AgentState.AWAITING_HUMAN,             AgentState.APPLYING),   # User approved mid-apply
    (AgentState.AWAITING_HUMAN,             AgentState.STOPPING),   # User stopped

    # ── Error recovery ────────────────────────────────────────────────────
    (AgentState.ERROR_RECOVERY, AgentState.RUNNING),      # Recovery succeeded
    (AgentState.ERROR_RECOVERY, AgentState.PAUSED),
    (AgentState.ERROR_RECOVERY, AgentState.STOPPING),
    (AgentState.ERROR_RECOVERY, AgentState.FAILED),       # Recovery failed

    # ── Shutdown sequence ─────────────────────────────────────────────────
    # stop() can arrive from any active state (called while a task is running
    # or while the queue is drained).
    (AgentState.IDLE,            AgentState.STOPPING),
    (AgentState.DISCOVERING,     AgentState.STOPPING),
    (AgentState.VETTING,         AgentState.STOPPING),
    (AgentState.APPLYING,        AgentState.STOPPING),
    (AgentState.STOPPING,        AgentState.STOPPED),
    # FAILED is not fully terminal — teardown must still reach STOPPED.
    (AgentState.FAILED,          AgentState.STOPPED),
})


@dataclass
class TransitionRecord:
    """Immutable record of a single state transition. Used for history and audit.

    Attributes:
        from_state: The state before the transition.
        to_state: The state after the transition.
        timestamp: UTC timestamp of the transition.
        triggered_by: Optional label identifying what triggered the transition.
    """
    from_state: AgentState
    to_state: AgentState
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    triggered_by: str | None = None


# Type alias for a guard function.
# A guard receives no arguments and returns True if the transition is allowed.
GuardFn = Callable[[], bool]


class StateMachine:
    """Enforces valid state transitions for the AgentOrchestrator.

    Maintains the current state and a full history of all transitions.
    Blocks invalid transitions and evaluates guard conditions before
    allowing valid ones.

    Thread safety: transition_to() is protected by a lock, making it safe
    to call from the main loop and from event handlers on monitor threads.

    Args:
        initial_state: The state the machine starts in. Typically IDLE.

    Example:
        >>> sm = StateMachine(initial_state=AgentState.IDLE)
        >>> sm.transition_to(AgentState.INITIALIZING, triggered_by="SessionController")
        True
        >>> sm.current_state
        AgentState.INITIALIZING
        >>> sm.history[-1].from_state
        AgentState.IDLE
    """

    def __init__(self, initial_state: AgentState = AgentState.IDLE) -> None:
        """Initializes the state machine in the given initial state.

        Args:
            initial_state: The starting state. Defaults to IDLE.
        """
        self._state = initial_state
        self._lock = threading.Lock()
        self._history: list[TransitionRecord] = []

        # Guards: {(from_state, to_state): [guard_fn, ...]}
        # All guards for a transition must return True for it to proceed.
        self._guards: dict[tuple[AgentState, AgentState], list[GuardFn]] = {}

        self._register_guards()

        logger.info("StateMachine initialized | state=%s", initial_state.name)

    # =========================================================================
    # CORE TRANSITION LOGIC
    # =========================================================================

    def transition_to(
        self,
        new_state: AgentState,
        triggered_by: str | None = None,
    ) -> bool:
        """Attempts to transition to a new state.

        Checks structural validity (is this pair in VALID_TRANSITIONS?),
        then evaluates all registered guard conditions for this pair.
        If all pass, the state is updated and the transition is recorded.

        Args:
            new_state: The desired target state.
            triggered_by: Optional label for the audit log (e.g., method name
                or event name that caused the transition).

        Returns:
            True if the transition succeeded. False if it was blocked by
            either the validity table or a guard condition.

        Example:
            >>> sm.transition_to(AgentState.RUNNING, triggered_by="checkpoint_recovery_done")
            True
        """  # noqa: E501
        with self._lock:
            current = self._state
            pair = (current, new_state)

            # Self-transition: going to the same state is always silently ignored.
            if current == new_state:
                return True

            # Structural validity check.
            if pair not in VALID_TRANSITIONS:
                logger.warning(
                    "StateMachine: invalid transition blocked | %s → %s (triggered_by=%s)",  # noqa: E501
                    current.name,
                    new_state.name,
                    triggered_by,
                )
                return False

            # Guard evaluation: all guards must pass.
            guards = self._guards.get(pair, [])
            for guard in guards:
                if not guard():
                    logger.warning(
                        "StateMachine: guard blocked transition | %s → %s guard=%s",
                        current.name,
                        new_state.name,
                        getattr(guard, "__qualname__", repr(guard)),
                    )
                    return False

            # Transition approved.
            self._state = new_state
            record = TransitionRecord(
                from_state=current,
                to_state=new_state,
                triggered_by=triggered_by,
            )
            self._history.append(record)

            logger.info(
                "StateMachine: %s → %s (triggered_by=%s)",
                current.name,
                new_state.name,
                triggered_by or "unspecified",
            )
            return True

    # =========================================================================
    # STATE QUERIES
    # =========================================================================

    @property
    def current_state(self) -> AgentState:
        """The current state. Thread-safe read.

        Returns:
            The current AgentState.
        """
        with self._lock:
            return self._state

    def is_in(self, *states: AgentState) -> bool:
        """Returns True if the current state is one of the given states.

        Args:
            *states: One or more AgentState values to check against.

        Returns:
            True if the current state matches any of the given states.

        Example:
            >>> sm.is_in(AgentState.PAUSED, AgentState.STOPPING)
            False
        """
        with self._lock:
            return self._state in states

    def is_active(self) -> bool:
        """Returns True if the agent is in any non-terminal, non-idle state.

        Useful for UI components that need to know whether a session is
        currently in progress.

        Returns:
            True if the agent is doing work or is paused mid-session.
        """
        inactive = {AgentState.IDLE, AgentState.STOPPED, AgentState.FAILED}
        return not self.is_in(*inactive)

    def can_transition_to(self, new_state: AgentState) -> bool:
        """Returns True if a transition to new_state is structurally valid.

        Does NOT evaluate guards — this is a structural check only.
        Useful for UI components that need to know which buttons to enable.

        Args:
            new_state: The state to check reachability for.

        Returns:
            True if the (current, new_state) pair is in VALID_TRANSITIONS.

        Example:
            >>> sm.can_transition_to(AgentState.PAUSED)
            True
        """
        with self._lock:
            return (self._state, new_state) in VALID_TRANSITIONS

    def get_reachable_states(self) -> set[AgentState]:
        """Returns all states reachable from the current state.

        Returns:
            Set of AgentState values that are valid next states from here.

        Example:
            >>> sm.get_reachable_states()
            {AgentState.DISCOVERING, AgentState.VETTING, AgentState.PAUSED, ...}
        """
        with self._lock:
            current = self._state
        return {
            to_state
            for (from_state, to_state) in VALID_TRANSITIONS
            if from_state == current
        }

    # =========================================================================
    # HISTORY AND AUDIT
    # =========================================================================

    @property
    def history(self) -> list[TransitionRecord]:
        """Ordered list of all transitions that have occurred.

        Returns a copy to prevent external mutation.

        Returns:
            List of TransitionRecord objects in chronological order.
        """
        with self._lock:
            return list(self._history)

    def time_in_current_state(self) -> float:
        """Returns the number of seconds spent in the current state.

        Returns:
            Elapsed seconds since the last transition, or 0.0 if no
            transitions have occurred yet.
        """
        with self._lock:
            if not self._history:
                return 0.0
            last = self._history[-1]
        elapsed = datetime.now(timezone.utc) - last.timestamp
        return elapsed.total_seconds()

    def get_summary(self) -> dict:
        """Returns a structured summary of the state machine's current status.

        Intended for checkpoint serialization and session reporting.

        Returns:
            A dict with current_state, transition_count, and time_in_state_seconds.
        """
        return {
            "current_state": self.current_state.name,
            "transition_count": len(self._history),
            "time_in_state_seconds": round(self.time_in_current_state(), 2),
        }

    # =========================================================================
    # GUARD REGISTRATION
    # =========================================================================

    def register_guard(
        self,
        from_state: AgentState,
        to_state: AgentState,
        guard: GuardFn,
    ) -> None:
        """Registers a guard condition for a specific state transition.

        Multiple guards can be registered for the same transition. All must
        return True for the transition to be allowed.

        Args:
            from_state: The source state this guard applies to.
            to_state: The target state this guard applies to.
            guard: A callable that returns True if the transition is allowed.

        Example:
            >>> def browser_ready() -> bool:
            ...     return driver is not None and driver.is_alive()
            >>> sm.register_guard(AgentState.RUNNING, AgentState.APPLYING, browser_ready)
        """  # noqa: E501
        key = (from_state, to_state)
        if key not in self._guards:
            self._guards[key] = []
        self._guards[key].append(guard)

    def _register_guards(self) -> None:
        """Registers all built-in guard conditions.

        Guards are registered here rather than inline in transition_to() so
        the full set of constraints is visible in one place.

        Adding a new guard:
            Call self.register_guard(from_state, to_state, guard_fn) here.
            The guard_fn must be a zero-argument callable returning bool.
        """
        # Guard: Cannot transition to STOPPED without going through STOPPING.
        # This prevents accidental jumps that skip cleanup.
        # Note: STOPPING → STOPPED is defined in VALID_TRANSITIONS and needs
        # no guard; the structural check handles it. The guard here is a
        # belt-and-suspenders check during development.

        # Guard: FAILED is a terminal state — no transitions out.
        # Enforced structurally by VALID_TRANSITIONS (no outgoing edges from FAILED).
        # No guard needed; the table is the authoritative source.

        pass

    # =========================================================================
    # REPR
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"StateMachine("
            f"state={self._state.name}, "
            f"transitions={len(self._history)})"
        )
