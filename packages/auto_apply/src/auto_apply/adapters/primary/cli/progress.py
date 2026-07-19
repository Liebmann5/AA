"""Simple in-place progress display for the CLI.

Uses ANSI escape codes to overwrite the same line rather than scrolling.
Falls back to plain newline logging if the terminal doesn't support ANSI.

Usage:
    progress = SessionProgressDisplay()
    progress.start()
    progress.update("APPLY", "Senior Engineer @ Acme Corp")
    ...
    progress.stop()
"""

from __future__ import annotations

import os
import sys
import threading
import time


class SessionProgressDisplay:
    """Displays a single updating status line during a session.

    The line shows: current task type, job being processed, and elapsed time.
    Automatically disabled if output is not a TTY (e.g., piped to a file).

    Usage:
        progress = SessionProgressDisplay()
        progress.start()
        progress.update("APPLY", "Senior Engineer @ Acme Corp")
        ...
        progress.stop()
    """

    def __init__(self) -> None:
        self._is_tty = (
            sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        )
        self._current_task = "Starting..."
        self._current_detail = ""
        self._start_time = time.monotonic()
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Begin the background render loop."""
        if not self._is_tty:
            return
        self._running = True
        self._start_time = time.monotonic()
        self._thread = threading.Thread(
            target=self._render_loop, daemon=True
        )
        self._thread.start()

    def update(self, task_type: str, detail: str = "") -> None:
        """Update the displayed task type and detail string.

        Args:
            task_type: Short label (e.g. "DISCOVER", "APPLY", "IDLE").
            detail: Job or query description (truncated to 50 chars).
        """
        with self._lock:
            self._current_task = task_type
            self._current_detail = detail[:50]

    def stop(self) -> None:
        """Stop the render loop and clear the progress line."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._is_tty:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

    def _render_loop(self) -> None:
        """Background daemon: redraws the progress line every 100 ms."""
        SPINNER = "\u280b\u280f\u2819\u2818\u281c\u2814\u2806\u2807\u2803\u280f"  # noqa: E501 — braille spinner
        i = 0
        while self._running:
            elapsed = time.monotonic() - self._start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            spinner = SPINNER[i % len(SPINNER)]

            with self._lock:
                task = self._current_task
                detail = self._current_detail

            line = (
                f"\r  {spinner} [{mins:02d}:{secs:02d}] "
                f"{task:<20} {detail}"
            )
            line = line[:79]  # Truncate to avoid line wrap
            sys.stdout.write(line)
            sys.stdout.flush()

            i += 1
            time.sleep(0.1)