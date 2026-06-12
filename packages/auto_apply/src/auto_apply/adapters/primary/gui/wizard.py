"""Provides the Session Configuration Wizard for the AutoApply GUI.

This module implements a tabbed `ttk.Frame` wizard that guides the user
through configuring a new automation session. It adheres to the MVP (Model-View-Presenter)
principles by collecting configuration data and returning it, rather than executing
logic directly.
"""  # noqa: E501

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any


class SessionConfigWizard(ttk.Frame):
    """A tabbed wizard for configuring run parameters."""

    def __init__(self, parent: tk.Widget, mode: str, on_complete: Callable[[dict[str, Any]], None]):  # noqa: E501
        """Initializes the wizard.

        Args:
            parent (tk.Widget): Parent container.
            mode (str): The execution mode ('discovery' or 'direct_links').
            on_complete (Callable): Callback triggered when "Start" is clicked.
                Receives the final config dictionary.
        """
        super().__init__(parent)
        self.mode = mode
        self.on_complete = on_complete
        self.config_data: dict[str, Any] = {}
        self._widgets: dict[str, Any] = {}
        self._build_layout()

    def _build_layout(self):
        """Constructs the tabbed interface for configuration."""
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Mode
        mode_frame = ttk.Frame(notebook, padding=20)
        notebook.add(mode_frame, text="1. Input Mode")

        self.mode_var = tk.StringVar(value="discovery")
        ttk.Radiobutton(mode_frame, text="Discovery Mode (Keywords)", variable=self.mode_var, value="discovery").pack(anchor=tk.W)  # noqa: E501
        ttk.Radiobutton(mode_frame, text="Direct Links (Paste URLs)", variable=self.mode_var, value="direct").pack(anchor=tk.W)  # noqa: E501

        # Tab 2: Parameters
        param_frame = ttk.Frame(notebook, padding=20)
        notebook.add(param_frame, text="2. Criteria")

        ttk.Label(param_frame, text="Keywords / Links:").pack(anchor=tk.W)
        self.input_text = tk.Text(param_frame, height=10)
        self.input_text.pack(fill=tk.X)

        # Footer
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="Start Session 🚀", command=self._finish).pack(side=tk.RIGHT)  # noqa: E501

    def _finish(self):
        """Compiles data and triggers callback."""
        self.config_data['mode'] = self.mode_var.get()
        self.config_data['input'] = self.input_text.get("1.0", tk.END).strip()
        self.on_complete(self.config_data)
