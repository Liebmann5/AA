"""Provides a real-time terminal dashboard for session monitoring.

This module is the View layer for CLI execution. It polls the
SessionController's public API and renders a live status table to the
terminal. It never touches the orchestrator, database, or engines directly.

Threading Safety:
    The dashboard runs on the main thread. It reads session state via
    SessionController.get_stats() and get_current_state(), both of which
    are thread-safe. The orchestrator runs in a separate daemon thread.
"""

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)


class CLIDashboard:
    """Renders session statistics and active task info to the terminal.

    Polls the SessionController at a configurable refresh rate and
    re-renders the dashboard on each tick. Exits when the session
    completes or the user presses Ctrl+C.

    When the agent transitions to AWAITING_HUMAN, the monitor loop suspends
    normal rendering and presents a numbered prompt. The user's choice is
    relayed to SessionController.provide_approval(), which unblocks the
    agent worker thread.

    Args:
        controller: The active SessionController for this session.
    """

    REFRESH_INTERVAL: float = 1.0

    def __init__(self, controller) -> None:
        """Initializes the dashboard.

        Args:
            controller: A SessionController instance with a running or
                about-to-run orchestrator.
        """
        self.controller = controller
        self._pending_approval: dict | None = None
        self._approval_lock = threading.Lock()
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        """Subscribes to HUMAN_APPROVAL_REQUESTED on the orchestrator event bus."""
        try:
            from auto_apply.domain.events import Event  # noqa: PLC0415
            event_bus = self.controller.orchestrator.event_bus
            event_bus.subscribe(Event.HUMAN_APPROVAL_REQUESTED, self._on_approval_requested)
        except Exception:
            pass

    def _on_approval_requested(self, payload: dict) -> None:
        """EventBus handler — stores the pending approval payload."""
        with self._approval_lock:
            self._pending_approval = payload

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

                if state == "AWAITING_HUMAN":
                    with self._approval_lock:
                        payload = self._pending_approval
                    if payload is not None:
                        self._handle_approval_prompt(payload)
                        with self._approval_lock:
                            self._pending_approval = None
                    else:
                        # Payload not yet delivered; wait briefly.
                        time.sleep(0.2)
                    continue

                self._render_screen()

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

    def _handle_approval_prompt(self, payload: dict) -> None:
        """Presents the HITL question/options and reads user input.

        Blocks the monitor loop (which is fine — the agent is also blocked)
        until the user enters a valid choice number or presses Ctrl+C.

        Args:
            payload: The HUMAN_APPROVAL_REQUESTED event payload.
        """
        context_id: str = payload.get("context_id", "")
        checkpoint: str = payload.get("checkpoint", "")
        question: str = payload.get("question", "The agent needs your approval.")
        options: list[str] = payload.get("options", ["approve", "skip"])

        os.system("cls" if os.name == "nt" else "clear")
        sep = "─" * 52
        print(f"\n AutoApply — Agent Approval Required [{checkpoint}]")  # noqa: T201
        print(sep)  # noqa: T201
        print(f" {question}")  # noqa: T201
        print(sep)  # noqa: T201
        for idx, opt in enumerate(options, start=1):
            print(f"  {idx}. {opt}")  # noqa: T201
        print(sep)  # noqa: T201

        choice = "skip"
        try:
            raw = input(" Enter choice number (or press Enter to skip): ").strip()
            if raw.isdigit():
                idx_choice = int(raw) - 1
                if 0 <= idx_choice < len(options):
                    choice = options[idx_choice]
        except EOFError:
            pass
        except KeyboardInterrupt:
            print("\n Interrupted — skipping this checkpoint.")  # noqa: T201
            choice = "skip"

        self.controller.provide_approval(context_id, choice)

    def _render_screen(self) -> None:
        """Clears terminal and prints formatted stats.

        Uses the SessionController's public get_stats() and
        get_current_state() methods — never reaches into the
        orchestrator or context directly.
        """
        os.system("cls" if os.name == "nt" else "clear")

        try:
            state = self.controller.get_current_state()
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