"""A drop-down for a multiple-choice setting (``application/services/choice_field``).

Read-only: the person picks one of the listed choices, so a value the
profile would refuse ("Jr" for "Jr.") can never be typed, and an optional
field offers "(none)" first. ``get()`` returns the stored value — None for
"(none)".
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from tkinter import ttk
from typing import Any

from auto_apply.application.services.choice_field import Choice, choice_index


class ChoiceBox:
    """A labelled read-only combobox over ``choices``."""

    def __init__(self, parent: tk.Misc, choices: Sequence[Choice], value: Any = None,
                 *, width: int = 48) -> None:
        self.choices = tuple(choices)
        self.var = tk.StringVar(value=self.choices[choice_index(self.choices, value)].label
                                if self.choices else "")
        self.widget = ttk.Combobox(parent, textvariable=self.var, state="readonly",
                                   values=[c.label for c in self.choices], width=width)

    def get(self) -> str | None:
        shown = self.var.get()
        for c in self.choices:
            if c.label == shown:
                return c.value
        return self.choices[0].value if self.choices else None

    def set_value(self, value: Any) -> None:
        """Show the choice whose stored value is ``value`` (the first when
        it is not listed, as when the window opens)."""
        if self.choices:
            self.var.set(self.choices[choice_index(self.choices, value)].label)

    def pack(self, **kw: Any) -> ChoiceBox:
        self.widget.pack(**kw)
        return self

    def grid(self, **kw: Any) -> ChoiceBox:
        self.widget.grid(**kw)
        return self


__all__ = ["ChoiceBox"]
