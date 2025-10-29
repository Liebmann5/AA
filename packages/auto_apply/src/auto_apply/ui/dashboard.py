"""Defines the main dashboard widget for the AutoApply UI.

This module contains the `Dashboard` class, a reusable `ttk.Frame` that serves
as the central component for providing real-time feedback to the user during an
active job application session.
"""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

class Dashboard(ttk.Frame):
    """The central UI component for displaying real-time progress and logs.

    This frame contains two main widgets:
    1.  A `Progressbar` to show the overall progress of the application session.
    2.  A `ScrolledText` widget that acts as a read-only log viewer, displaying
        detailed, real-time status messages from the application's backend.
    """

    def __init__(self, parent, **kwargs):
        """Initializes the Dashboard frame and its child widgets.

        Args:
            parent: The parent tkinter widget that this frame will be placed in.
            **kwargs: Additional keyword arguments to pass to the `ttk.Frame` constructor.
        """
        super().__init__(parent, **kwargs)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        progress_label = ttk.Label(self, text="Overall Progress:")
        progress_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.progress_bar = ttk.Progressbar(self, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)

        log_label = ttk.Label(self, text="Activity Log:")
        log_label.grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.log_viewer = ScrolledText(self, state='disabled', wrap=tk.WORD, height=15)
        self.log_viewer.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=2)

    def log(self, message: str) -> None:
        """Appends a message to the log viewer widget in a thread-safe way.

        This method provides a safe way to update the text widget. It temporarily
        enables the widget, inserts the new message at the end, auto-scrolls
        to the bottom, and then disables the widget again to keep it read-only
        for the user.

        Args:
            message: The string message to be added to the log.
        """
        self.log_viewer.configure(state='normal')
        self.log_viewer.insert(tk.END, message + '\n')
        self.log_viewer.configure(state='disabled')
        self.log_viewer.yview(tk.END)

    def update_progress(self, current: int, maximum: int) -> None:
        """Updates the value of the progress bar.

        This method calculates the percentage completion based on the current
        and maximum values and updates the progress bar accordingly.

        Args:
            current: The current progress value (e.g., number of jobs applied to).
            maximum: The total value that represents 100% completion (e.g.,
                total number of jobs to apply for).
        """
        if maximum > 0:
            self.progress_bar['value'] = ((current / maximum) * 100)
        else:
            self.progress_bar['value'] = 0
        self.update_idletasks()