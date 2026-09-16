"""Defines the main dashboard widget for the AutoApply UI.

This module provides the `Dashboard` class, a reusable `ttk.Frame` that serves
as the central command center. It adheres to the Model-View-Controller (MVC)
pattern by remaining passive; it displays data provided to it but does not
contain business logic.

Key Features:
- Internationalization (I18n) ready via `strings` injection.
- Accessibility (a11y) friendly using native `ttk` widgets and semantic grouping.
- Thread-safe logging display.

Activity stream (stage D2):
- The Activity panel is fed from the PORT, not the EventBus. `feed_activity()`
  diffs the controller's `recent_events()` window and writes each new record
  through `log_message()` — the writer this panel has always had — formatted
  by the shared `ui_contract.format_activity_line` so the GUI and the CLI
  print the same line for the same record.
- The HITL modal is triggered by the application's poll of
  `controller.pending_approvals()` (gui/app.py) and consumes the
  `ApprovalRequest` DTO directly. There is NO direct EventBus subscription
  anywhere in this module: U4's import ban (adapters may only import the port
  and domain.models.*) is satisfied by construction, not by hope.
"""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING, Any

from auto_apply.adapters.primary.gui.strings import get_strings
from auto_apply.domain.models.ui_contract import (
    ApprovalRequest,
    SessionEventRecord,
    activity_new,
    format_activity_line,
)

if TYPE_CHECKING:
    from auto_apply.application.services.session_controller import SessionController


class Dashboard(ttk.Frame):
    """The central UI component for real-time monitoring and control.

    This view is responsible for visualization only. It accepts status updates
    and log messages from the `SessionController` (via the application layer's
    poll loop) and from `feed_activity()`.

    Attributes:
        strings (Dict[str, str]): Localized text resources.
        progress_bar (ttk.Progressbar): Visual indicator of batch completion.
        log_viewer (ScrolledText): Read-only text area for system events.
        stats_labels (Dict[str, ttk.Label]): Dynamic labels for metrics.
    """

    def __init__(self, parent: tk.Widget, **kwargs):
        """Initializes the Dashboard UI structure.

        Args:
            parent (tk.Widget): The parent container.
            **kwargs: Configuration options passed to the Frame.
        """
        super().__init__(parent, **kwargs)

        # Load Localized Strings (Future-proofing for I18n)
        # We pass 'None' to auto-detect OS language
        self.strings = get_strings(lang_code=None)
        self._session_controller: "SessionController | None" = None

        # Activity stream diff state: the last record written to the panel,
        # so each feed writes only what's new (activity_new replays the window
        # if that record has fallen out of the bounded deque).
        self._last_activity_record: SessionEventRecord | None = None

        # Re-entry guard for the HITL modal: gui/app.py polls pending gates
        # every 500 ms, and wait_window() runs the Tk event loop while the
        # modal is open — without this flag the poll would stack a new modal
        # on top of the open one every tick.
        self._approval_modal_open: bool = False

        self._configure_layout()
        self._build_header_section()
        self._build_statistics_section()
        self._build_progress_section()
        self._build_logging_section()

    def _configure_layout(self) -> None:
        """Configures the responsive grid layout."""
        self.columnconfigure(0, weight=1)
        # Row weights allow the log viewer (row 3) to expand, keeping stats fixed
        self.rowconfigure(3, weight=1)

    def _build_header_section(self) -> None:
        """Constructs the dashboard header/title area."""
        header_frame = ttk.Frame(self, padding="10 10 10 5")
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        title_label = ttk.Label(
            header_frame,
            text=self.strings.get("dashboard_title", "AutoApply Command Center"),
            font=("Segoe UI", 16, "bold") # Font should eventually come from theme config  # noqa: E501
        )
        title_label.pack(side=tk.LEFT)

    def _build_statistics_section(self) -> None:
        """Constructs the metrics grid (Jobs Found, Applied, Failed).

        This section uses a dynamic dictionary `self.stats_labels` to allow
        easy updating via `update_metric()` without hardcoding widget references.
        """
        stats_frame = ttk.LabelFrame(
            self,
            text=self.strings.get("stats_section_title", "Session Metrics"),
            padding="10"
        )
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)

        # Define metric keys and their default labels
        metrics = [
            ("discovered", self.strings.get("metric_discovered", "Discovered")),
            ("vetted", self.strings.get("metric_vetted", "Vetted")),
            ("applied", self.strings.get("metric_applied", "Applied")),
            ("failed", self.strings.get("metric_failed", "Failed"))
        ]

        self.stats_labels: dict[str, ttk.Label] = {}

        for idx, (key, label_text) in enumerate(metrics):
            # Layout logic: 2 columns per row
            row, col = divmod(idx, 4)

            container = ttk.Frame(stats_frame)
            container.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

            # The Label (Static)
            ttk.Label(container, text=label_text, font=("Segoe UI", 9)).pack(anchor=tk.W)  # noqa: E501

            # The Value (Dynamic)
            value_label = ttk.Label(container, text="0", font=("Segoe UI", 12, "bold"))
            value_label.pack(anchor=tk.W)

            self.stats_labels[key] = value_label

    def _build_progress_section(self) -> None:
        """Constructs the progress bar and status text."""
        progress_frame = ttk.Frame(self, padding="10 5")
        progress_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))

        self.status_label = ttk.Label(
            progress_frame,
            text=self.strings.get("status_idle", "Ready to start...")
        )
        self.status_label.pack(anchor=tk.W, pady=(0, 5))

        self.progress_bar = ttk.Progressbar(
            progress_frame,
            orient="horizontal",
            mode="determinate"
        )
        self.progress_bar.pack(fill=tk.X, expand=True)

    def _build_logging_section(self) -> None:
        """Constructs the scrolled text area for real-time logs."""
        log_frame = ttk.LabelFrame(
            self,
            text=self.strings.get("log_section_title", "Live Activity Feed"),
            padding="10"
        )
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=5)  # noqa: E501

        self.log_viewer = ScrolledText(
            log_frame,
            state='disabled',
            wrap=tk.WORD,
            height=10,
            font=("Consolas", 9) # Monospace for logs
        )
        self.log_viewer.pack(fill=tk.BOTH, expand=True)

        # Tag configuration for colored logs (Future integration)
        self.log_viewer.tag_config("INFO", foreground="black")
        self.log_viewer.tag_config("WARNING", foreground="#cf6a00") # Dark Orange
        self.log_viewer.tag_config("ERROR", foreground="red")
        self.log_viewer.tag_config("SUCCESS", foreground="green")

    # --- Public API (For the Controller to use) ---

    def update_metric(self, key: str, value: Any) -> None:
        """Updates a specific statistic on the dashboard.

        Args:
            key (str): The metric identifier (e.g., 'discovered').
            value (Any): The new value to display.
        """
        if key in self.stats_labels:
            self.stats_labels[key].config(text=str(value))

    def update_progress(self, current: int, maximum: int, status_text: str | None = None) -> None:  # noqa: E501
        """Updates the progress bar and status label.

        Args:
            current (int): Current items processed.
            maximum (int): Total items to process.
            status_text (Optional[str]): Detailed status string (e.g. "Scanning Google...").
        """  # noqa: E501
        if maximum > 0:
            percentage = (current / maximum) * 100
            self.progress_bar['value'] = percentage
        else:
            self.progress_bar['mode'] = 'indeterminate'
            self.progress_bar.start(10)

        if status_text:
            self.status_label.config(text=status_text)

        # Force UI update to keep interface responsive during heavy processing
        self.update_idletasks()

    def log_message(self, message: str, level: str = "INFO") -> None:
        """Thread-safe method to append messages to the log viewer.

        Safe to call from any thread. Schedules the actual widget mutation
        on the Tk main thread via after(0, ...) to avoid cross-thread Tk
        access violations.

        This is the panel's single writer: feed_activity() calls it, and so
        may any future producer — there is exactly one path into the log
        viewer.

        Args:
            message (str): The text to log.
            level (str): The log level (INFO, WARNING, ERROR, SUCCESS) for coloring.
        """
        self.after(0, self._append_log, message, level)

    def _append_log(self, message: str, level: str) -> None:
        """Appends a log line to the viewer. Must be called on the main thread."""
        self.log_viewer.configure(state='normal')
        self.log_viewer.insert(tk.END, f"{message}\n", level)
        self.log_viewer.configure(state='disabled')
        self.log_viewer.yview(tk.END)

    # ── Activity stream feed (D2) ─────────────────────────────────────────────

    def feed_activity(self, records: tuple[SessionEventRecord, ...]) -> None:
        """Writes the stream's new records into the Activity panel.

        Called from gui/app.py's 500 ms poll with the controller's full
        recent_events() window. Diffs against the last record displayed
        (activity_new replays the window if that record fell out of the
        bounded deque or a new session started) and writes each new record
        through log_message(), formatted by the shared
        ui_contract.format_activity_line — identical to what the CLI prints
        for the same record.

        An empty tuple (no session yet) is a no-op, never an error.
        """
        for record in activity_new(records, self._last_activity_record):
            self.log_message(format_activity_line(record), record.level)
            self._last_activity_record = record

    # ── HITL approval modal ───────────────────────────────────────────────────

    def bind_session(self, controller: "SessionController") -> None:
        """Connects the dashboard to an active SessionController.

        Stores the controller so the approval modal can call
        ``provide_approval``. Nothing is subscribed and nothing is seeded:
        gui/app.py polls ``controller.pending_approvals()`` every 500 ms,
        which catches a gate opened before this dashboard was built with at
        most one tick of delay — the seed the old push-based bind needed
        (because a broadcast cannot be heard twice) is no longer needed,
        because gate state is now polled, not broadcast.

        Args:
            controller: The active SessionController for this session.
        """
        self._session_controller = controller

    def show_approval(self, approval: ApprovalRequest) -> None:
        """Shows the HITL modal for one open gate, unless one is already open.

        Called from gui/app.py's poll when pending_approvals() is non-empty.
        The re-entry flag prevents a stacked modal every poll tick while the
        user is still reading the first one.
        """
        if self._approval_modal_open or self._session_controller is None:
            return
        self._show_approval_modal(approval)

    def _show_approval_modal(self, approval: ApprovalRequest) -> None:
        """Creates and shows the HITL approval modal dialog.

        Must be called on the Tk main thread. Blocks the calling poll with
        wait_window() — which runs the Tk event loop, so stats and stream
        polls continue to fire inside it — until the user chooses an option
        or closes the window (treated as skip, same as the old modal).
        """
        if self._session_controller is None:
            return

        self._approval_modal_open = True
        try:
            modal = tk.Toplevel(self)
            modal.title("Agent Approval Required")
            modal.resizable(False, False)
            modal.grab_set()

            ttk.Label(
                modal,
                text=f"Checkpoint: {approval.checkpoint}",
                font=("Segoe UI", 9, "italic"),
            ).pack(padx=20, pady=(15, 0))

            ttk.Label(
                modal,
                text=approval.question,
                wraplength=360,
                justify=tk.LEFT,
                font=("Segoe UI", 10),
            ).pack(padx=20, pady=10)

            ttk.Separator(modal, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

            btn_frame = ttk.Frame(modal, padding="10 10 10 15")
            btn_frame.pack(fill=tk.X)

            def _choose(choice: str) -> None:
                modal.grab_release()
                modal.destroy()
                if self._session_controller is not None:
                    self._session_controller.provide_approval(
                        approval.context_id, choice
                    )

            for option in approval.options:
                ttk.Button(
                    btn_frame,
                    text=option.capitalize(),
                    command=lambda o=option: _choose(o),  # type: ignore[misc]
                ).pack(side=tk.LEFT, padx=5)

            modal.protocol("WM_DELETE_WINDOW", lambda: _choose("skip"))
            modal.wait_window()
        finally:
            # Clear even if the window is destroyed by something other than
            # _choose — otherwise the gate would never be shown again.
            self._approval_modal_open = False
