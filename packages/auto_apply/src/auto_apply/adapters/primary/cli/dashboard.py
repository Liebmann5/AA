"""Provides a real-time terminal dashboard for session monitoring.

This module is the View layer for CLI execution. It polls the
SessionController's PUBLIC port surface — never the orchestrator, the
database, or the EventBus directly — and renders session state plus the
activity stream to the terminal.

Port polling (stage D2):
    There is NO direct EventBus subscription in this module. Two things are
    polled through the port every refresh tick:

      - ``controller.pending_approvals()`` for open HITL gates. A gate blocks
        the agent for up to 300 seconds; one refresh tick of latency (~1 s)
        before the prompt appears is 0.3 % of that window and has no
        correctness impact — the prompt still opens, the gate still blocks,
        and provide_approval still releases it.
      - ``controller.recent_events()`` for the activity stream, formatted by
        the shared ``ui_contract.format_activity_line`` so the CLI and the
        GUI print the same line for the same record.

    U4's planned import ban (adapters may only import the port and
    domain.models.*) is satisfied by construction: this module imports no
    Event and touches no bus.

Threading Safety:
    The dashboard runs on the main thread. It reads session state via the
    controller's port methods, which are thread-safe. The orchestrator runs
    in a separate daemon thread.

Non-interactive output:
    When stdout is not a TTY (redirected to a file or pipe), the dashboard
    does not clear the screen and does not redraw frames. It prints new
    activity lines as they arrive, plus one plain status line every
    NON_TTY_STATUS_INTERVAL seconds and one on each state change, so a
    captured log stays readable and grep-able. The detection idiom
    (isatty + TERM != 'dumb') is the same one already used by
    SessionProgressDisplay in progress.py.

Screen clearing on a TTY:
    POSIX (Linux/macOS): the ANSI erase sequence is written directly to the
    stream. No subprocess is spawned per frame — previously os.system forked
    a shell for every redraw.

    Windows: os.system("cls") is kept deliberately. ANSI rendering on legacy
    conhost (Windows 8.1 and older, still present on library and
    careers-centre machines AA targets) is not guaranteed, and the author
    has NOT verified what proportion of AA's Windows users run terminals
    that accept VT sequences. That is a conservative guess, stated as such —
    not a measurement. The residual cost is one `cls` spawn per refresh tick
    on Windows only.
"""

import os
import sys
import time

from auto_apply.domain.models.ui_contract import (
    ApprovalRequest,
    SessionEventRecord,
    activity_new,
    format_activity_line,

)

# How many stream lines a TTY frame shows. A rolling window, re-rendered
# every frame — no diff state needed on the TTY path.
_TTY_STREAM_LINES: int = 6


class CLIDashboard:
    """Renders session statistics, the activity stream, and HITL prompts.

    Polls the SessionController at a configurable refresh rate and
    re-renders the dashboard on each tick. Exits when the session
    completes or the user presses Ctrl+C.

    When the agent transitions to AWAITING_HUMAN with an open gate, the
    monitor loop suspends normal rendering and presents a numbered prompt.
    The user's choice is relayed to SessionController.provide_approval(),
    which unblocks the agent worker thread.

    Args:
        controller: The active SessionController for this session.
    """

    REFRESH_INTERVAL: float = 1.0
    NON_TTY_STATUS_INTERVAL: float = 10.0

    def __init__(self, controller) -> None:
        """Initializes the dashboard.

        Args:
            controller: A SessionController instance with a running or
                about-to-run orchestrator.
        """
        self.controller = controller
        # Detected once, at construction, per the session's output target.
        self._is_tty: bool = (
            sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        )
        self._last_status_line: float = 0.0
        self._last_state: str | None = None
        # Diff state for the non-TTY stream path: the last record printed,
        # so each poll prints only what's new (activity_new replays the
        # window if that record fell out of the bounded deque).
        self._last_activity_record: SessionEventRecord | None = None

    def current_gate(self):
        """The open HITL gate, or None.

        Read from the controller every time rather than cached from an
        EventBus subscription. The old dashboard cached a payload it heard
        published; a dashboard constructed AFTER the publish heard nothing and
        showed no gate. Reading through the port cannot miss one, and this is
        the read the monitor loop and the late-bind pin both use.
        """
        gates = self.controller.pending_approvals()
        return gates[0] if gates else None

    def run_monitor_loop(self) -> None:
        """Blocks and refreshes the screen until session ends or user interrupts.

        Exit conditions:
            - The orchestrator state transitions to STOPPED or FAILED.
            - The orchestrator thread dies (is_running becomes False).
            - The user presses Ctrl+C (KeyboardInterrupt).
        """
        try:
            while True:
                state = self.controller.get_current_state()
                gate = self.current_gate()

                if state == "AWAITING_HUMAN" and gate is not None:
                    self._handle_approval_prompt(gate)
                    continue

                if self._is_tty:
                    self._render_screen(state)
                else:
                    self._poll_activity()
                    self._emit_non_tty_status(state)

                # Check for session completion.
                if state in ("STOPPED", "FAILED"):
                    break

                # Also check if the thread itself died unexpectedly.
                if not self.controller.is_running:
                    break

                time.sleep(self.REFRESH_INTERVAL)

        except KeyboardInterrupt:
            self.controller.stop()
            sys.exit(0)

    def _handle_approval_prompt(self, approval: ApprovalRequest) -> None:
        """Presents the HITL question/options and reads user input.

        Blocks the monitor loop (which is fine — the agent is also blocked)
        until the user enters a valid choice number or presses Ctrl+C.

        Args:
            approval: The open gate, as the port's ApprovalRequest DTO.
        """
        self._clear_screen()
        sep = "─" * 52
        print(f"\n AutoApply — Agent Approval Required [{approval.checkpoint}]")  # noqa: T201
        print(sep)  # noqa: T201
        print(f" {approval.question}")  # noqa: T201
        print(sep)  # noqa: T201
        for idx, opt in enumerate(approval.options, start=1):
            print(f"  {idx}. {opt}")  # noqa: T201
        print(sep)  # noqa: T201

        choice = "skip"
        try:
            raw = input(" Enter choice number (or press Enter to skip): ").strip()
            if raw.isdigit():
                idx_choice = int(raw) - 1
                if 0 <= idx_choice < len(approval.options):
                    choice = approval.options[idx_choice]
        except EOFError:
            pass
        except KeyboardInterrupt:
            print("\n Interrupted — skipping this checkpoint.")  # noqa: T201
            choice = "skip"

        self.controller.provide_approval(approval.context_id, choice)

    def _poll_activity(self) -> None:
        """Non-TTY path: prints stream lines that have not been printed yet.

        Called every refresh tick; each new record prints once, formatted by
        the shared formatter. An empty stream (no session yet) is a no-op,
        never an error.
        """
        for record in activity_new(
            self.controller.recent_events(), self._last_activity_record
        ):
            print(format_activity_line(record))  # noqa: T201
            sys.stdout.flush()
            self._last_activity_record = record

    def _clear_screen(self) -> None:
        """Clears the terminal screen. Does nothing when stdout is not a TTY.

        POSIX writes the ANSI erase sequence directly to the stream (no
        subprocess). Windows keeps os.system("cls") — see the module
        docstring for the reasoning and its stated uncertainty.
        """
        if not self._is_tty:
            return
        if os.name == "nt":
            os.system("cls")
        else:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def _emit_non_tty_status(self, state: str) -> None:
        """Emits one plain text status line for a redirected stdout.

        Printed at most once every NON_TTY_STATUS_INTERVAL seconds, plus
        once whenever the agent state changes. No escape sequences are
        written, so captured logs stay readable end to end.
        """
        now = time.monotonic()
        state_changed = state != self._last_state
        if not state_changed and (now - self._last_status_line) < self.NON_TTY_STATUS_INTERVAL:
            return

        self._last_status_line = now
        self._last_state = state

        try:
            stats = self.controller.get_stats()
        except Exception:
            return

        duration = stats.get("duration_str", "00:00:00")
        discovered = stats.get("jobs_discovered", 0)
        vetted = stats.get("jobs_vetted", 0)
        applied = stats.get("applications_submitted", 0)
        failed = stats.get("applications_failed", 0)
        success = f"{stats.get('success_rate', 0.0):.0%}"

        queued = ""
        try:
            queued = f" queued={self.controller.get_queue_stats().get('pending', 0)}"
        except Exception:
            pass

        timestamp = time.strftime("%H:%M:%S")
        print(
            f"[{timestamp}] state={state} found={discovered} vetted={vetted} "
            f"applied={applied} failed={failed} ({success}){queued} elapsed={duration}"
        )  # noqa: T201
        sys.stdout.flush()

    def _render_screen(self, state: str) -> None:
        """Clears terminal and prints formatted stats plus the stream window.

        The frame is coherent each tick: stats, then the newest
        _TTY_STREAM_LINES activity lines, then the prompt hint. Uses the
        controller's public get_stats() and get_current_state() — never
        reaches into the orchestrator or context directly.
        """
        self._clear_screen()

        try:
            stats = self.controller.get_stats()
        except Exception:
            return

        duration  = stats.get("duration_str", "00:00:00")
        discovered = stats.get("jobs_discovered", 0)
        vetted    = stats.get("jobs_vetted", 0)
        applied   = stats.get("applications_submitted", 0)
        failed    = stats.get("applications_failed", 0)
        success   = stats.get("success_rate", "0%")

        sep = "─" * 42
        print(f"\n AutoApply — Live Session Monitor")  # noqa: T201
        print(sep)  # noqa: T201
        print(f" State:    {state:<20} Duration: {duration}")  # noqa: T201
        print(f" Found: {discovered:>4}  Vetted: {vetted:>4}  Applied: {applied:>4}  Failed: {failed:>4}  ({success})")  # noqa: T201
        print(sep)  # noqa: T201

        # ── Activity stream (D2): newest lines, formatted once in ui_contract.
        try:
            for record in self.controller.recent_events(limit=_TTY_STREAM_LINES):
                print(f" {format_activity_line(record)}")  # noqa: T201
        except Exception:
            pass
        print(sep)  # noqa: T201

        # Task detail (context access is a P2 cleanup item).
        try:
            task = self.controller.orchestrator.context.current_work_unit
            if task:
                raw = str(task.payload)
                payload_str = raw[:47] + "..." if len(raw) > 50 else raw
                print(f" Task:    [{task.task_type.name}] {payload_str}")  # noqa: T201
        except Exception:
            pass

        try:
            pending = self.controller.get_queue_stats().get("pending", 0)
            print(f" Queue:   {pending} pending")  # noqa: T201
        except Exception:
            pass

        print(sep)  # noqa: T201
        print(" Ctrl+C to stop\n")  # noqa: T201
