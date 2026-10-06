"""The GUI lifecycle window (File → Install / Repair… and File → Uninstall…).

The second lifecycle surface; the CLI screen is the first, and the parity
pin holds them together: every word, choice, default and token comes from
application/services/lifecycle_wording.py, and both surfaces drive the
same engines. Mirrors the research-window precedent: pure, widget-free
helpers carry what the pins need; the class below only wires widgets.

Accessibility (WCAG 2.1 AA, keyboard-only): the text area takes focus and
receives it on every step change; every action is a labelled button reached
by Tab and activated by Space/Enter; the destructive confirmations are
ordinary Entry fields with focus (never a default-ringed "Yes"); radio
buttons carry full text labels; Escape cancels; nothing is conveyed by
colour alone (errors are text prefixed "Error:").

What the pins CANNOT check headless: real Tab traversal and screen-reader
behaviour. The source-level guarantees above are pinned; the rest is
manual testing, said plainly.
"""
from __future__ import annotations

import tkinter as tk
from enum import Enum, auto
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from auto_apply.infrastructure.composition_root import (
    InstallEngine,
    InstallEnvironment,
    InstallError,
    ResearchDecision,
    UninstallDecision,
    UninstallEngine,
    UninstallEnvironment,
    UninstallRefused,
    UninstallReport,
    lifecycle_wording as _w,
)

__all__ = ["LifecycleMode", "LifecycleWindow", "research_choice_labels"]


class LifecycleMode(Enum):
    INSTALL = auto()
    UNINSTALL = auto()


def research_choice_labels(choices: tuple[_w.ResearchChoice, ...]) -> list[str]:
    """Pure: the labels the radio column shows — straight from the wording."""
    return [_w.CHOICE_LABELS[c] for c in choices]


class LifecycleWindow(tk.Toplevel):
    """One window, two modes. Steps: plan/consent → confirm → work → report."""

    def __init__(
        self,
        parent: tk.Misc,
        mode: LifecycleMode,
        *,
        uninstall_env: UninstallEnvironment | None = None,
        install_env: InstallEnvironment | None = None,
        on_close_app=None,
    ) -> None:
        super().__init__(parent)
        if mode is LifecycleMode.UNINSTALL and uninstall_env is None:
            raise ValueError("uninstall_env is required for UNINSTALL mode")
        if mode is LifecycleMode.INSTALL and install_env is None:
            raise ValueError("install_env is required for INSTALL mode")
        self._mode = mode
        self._uninstall_env = uninstall_env
        self._install_env = install_env
        self._on_close_app = on_close_app
        self._report: UninstallReport | None = None  # set after a successful uninstall

        self._choice_var = tk.StringVar()
        self._dest_var = tk.StringVar()
        self._token_var = tk.StringVar()
        self._delete_token_var = tk.StringVar()
        self._error_var = tk.StringVar()
        self._status_var = tk.StringVar()
        self._extra_vars: dict[str, tk.BooleanVar] = {}

        self.title("Install AutoApply" if mode is LifecycleMode.INSTALL else "Uninstall AutoApply")
        self.geometry("780x620")
        self.minsize(640, 480)
        self.transient(parent)  # type: ignore[call-overload]
        # Closing and Escape are the decline path — never a confirmation.
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())

        ttk.Label(
            self, textvariable=self._status_var, justify=tk.LEFT, wraplength=740, padding=(12, 10)
        ).pack(fill=tk.X)

        # Buttons pack side=BOTTOM BEFORE the text area so they reserve
        # their height (the Settings dialog's load-bearing layout lesson).
        self._buttons = ttk.Frame(self, padding=12)
        self._buttons.pack(fill=tk.X, side=tk.BOTTOM)
        self._form = ttk.Frame(self, padding=(12, 0))
        self._form.pack(fill=tk.X, side=tk.BOTTOM)

        self._text = ScrolledText(self, state="disabled", wrap=tk.WORD, takefocus=True,
                                  font=("Segoe UI", 10))
        self._text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))

        if mode is LifecycleMode.UNINSTALL:
            self._u_show_plan()
        else:
            self._i_show_consent()

    # ── view plumbing ────────────────────────────────────────────────────

    def _set_text(self, text: str) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, text)
        self._text.configure(state="disabled")
        self._text.yview_moveto(0.0)
        self._text.focus_set()

    def _clear_buttons(self) -> None:
        for child in self._buttons.winfo_children():
            child.destroy()

    def _add_button(self, label: str, command) -> None:
        count = len(self._buttons.winfo_children())
        ttk.Button(self._buttons, text=label, command=command).grid(
            row=count // 3, column=count % 3, sticky="ew", padx=(0, 8), pady=(0, 6)
        )

    def _clear_form(self) -> None:
        for child in self._form.winfo_children():
            child.destroy()

    def _progress(self, message: str) -> None:
        self._status_var.set(message)
        self.update_idletasks()

    def _fatal(self, message: str) -> None:
        self._set_text(message)
        self._status_var.set("Error — nothing was changed beyond this point.")
        self._clear_form()
        self._clear_buttons()
        self._add_button("Close", self._cancel)

    def _cancel(self) -> None:
        self.destroy()

    def _save_report(self) -> None:
        if self._report is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".json", initialfile="aa_uninstall_report.json"
        )
        if path:
            Path(path).write_bytes(self._report.to_json_bytes())

    def _show_report(self, lines: list[str], *, close_app: bool) -> None:
        self._set_text("\n".join(lines))
        self._status_var.set("Finished.")
        self._clear_form()
        self._clear_buttons()
        if self._report is not None:
            self._add_button("Save report (JSON)…", self._save_report)
        if close_app and self._on_close_app is not None:
            self._add_button("Close AutoApply", self._on_close_app)
        else:
            self._add_button("Close", self._cancel)

    # ── uninstall ────────────────────────────────────────────────────────

    def _u_show_plan(self) -> None:
        env = self._uninstall_env
        assert env is not None  # enforced by __init__ for UNINSTALL mode
        engine = UninstallEngine(env)
        self._u_engine = engine
        plan = engine.build_plan()
        self._u_plan = plan
        lines = _w.format_plan_lines(plan)
        if plan.research_items:
            lines += [""] + _w.format_research_notice_lines(plan)
        self._set_text("\n".join(lines))
        self._status_var.set("Review the plan. Nothing has been stopped, moved or deleted yet.")
        self._clear_form()
        self._clear_buttons()
        self._add_button("Continue…", self._u_show_confirm)
        self._add_button("Cancel", self._cancel)

    def _u_show_confirm(self) -> None:
        plan = self._u_plan
        self._set_text(
            f"Confirmation is typed, never a one-click Yes: type {_w.CONFIRM_UNINSTALL}.\n"
            "Uninstall stops every AA process, follows your research choice,\n"
            "removes everything AA created, and prints a report. AutoApply\n"
            "closes at the end; removal of the program folder finishes after\n"
            "it closes."
        )
        self._clear_form()
        row = 0
        self._choices = _w.research_choices(plan.hold is not None) if plan.research_items else ()
        if self._choices:
            ttk.Label(self._form, text="Research data on this device:").grid(
                row=row, column=0, sticky=tk.W
            )
            row += 1
            self._choice_var.set(self._choices[0].name)  # default = KEEP_IN_PLACE, as the CLI
            for choice in self._choices:
                ttk.Radiobutton(
                    self._form,
                    text=_w.CHOICE_LABELS[choice],
                    value=choice.name,
                    variable=self._choice_var,
                    command=self._u_choice_changed,
                ).grid(row=row, column=0, sticky=tk.W)
                row += 1
            self._dest_row = ttk.Frame(self._form)
            ttk.Button(self._dest_row, text="Choose folder…", command=self._pick_dest).pack(side=tk.LEFT)
            ttk.Label(self._dest_row, textvariable=self._dest_var).pack(side=tk.LEFT, padx=8)
            self._dest_row.grid(row=row, column=0, sticky=tk.W, pady=4)
            row += 1
        ttk.Label(self._form, text=f"Type {_w.CONFIRM_UNINSTALL} to confirm:").grid(
            row=row, column=0, sticky=tk.W, pady=(8, 0)
        )
        row += 1
        entry = ttk.Entry(self._form, textvariable=self._token_var, width=24)
        entry.grid(row=row, column=0, sticky=tk.W)
        row += 1
        self._delete_label = ttk.Label(
            self._form, text=f"Also type {_w.CONFIRM_DELETE} to delete all research data:"
        )
        self._delete_entry = ttk.Entry(self._form, textvariable=self._delete_token_var, width=24)
        ttk.Label(self._form, textvariable=self._error_var).grid(row=row, column=0, sticky=tk.W)
        entry.focus_set()
        entry.bind("<Return>", lambda _event: self._u_run())
        self._clear_buttons()
        self._add_button("Uninstall", self._u_run)
        self._add_button("Back", self._u_show_plan)
        self._add_button("Cancel", self._cancel)
        self._u_choice_changed()

    def _u_choice_changed(self) -> None:
        choice = self._choice_var.get()
        if hasattr(self, "_dest_row"):
            if choice in (_w.ResearchChoice.MOVE.name, _w.ResearchChoice.EXPORT.name):
                self._dest_row.grid()
            else:
                self._dest_row.grid_remove()
        if choice == _w.ResearchChoice.DELETE.name:
            self._delete_label.grid(row=98, column=0, sticky=tk.W, pady=(8, 0))
            self._delete_entry.grid(row=99, column=0, sticky=tk.W)
        else:
            self._delete_label.grid_remove()
            self._delete_entry.grid_remove()

    def _pick_dest(self) -> None:
        directory = filedialog.askdirectory(parent=self)
        if directory:
            self._dest_var.set(directory)

    def _u_run(self) -> None:
        plan = self._u_plan
        if self._token_var.get().strip() != _w.CONFIRM_UNINSTALL:
            self._error_var.set(f"Error: type {_w.CONFIRM_UNINSTALL} exactly to proceed.")
            return
        action: str | None = None
        dest: Path | None = None
        if plan.research_items and self._choices:
            choice = _w.ResearchChoice[self._choice_var.get()]
            if choice in (_w.ResearchChoice.MOVE, _w.ResearchChoice.EXPORT):
                if not self._dest_var.get():
                    self._error_var.set("Error: choose a folder first.")
                    return
                dest = Path(self._dest_var.get())
            if choice is _w.ResearchChoice.DELETE:
                if self._delete_token_var.get().strip() != _w.CONFIRM_DELETE:
                    self._error_var.set(
                        f"Error: type {_w.CONFIRM_DELETE} exactly to delete research data."
                    )
                    return
            action = _w.CHOICE_TO_ACTION[choice]
        self._error_var.set("")
        self._clear_form()
        self._clear_buttons()
        self._set_text("Working…\n")
        env = self._uninstall_env
        assert env is not None  # enforced by __init__ for UNINSTALL mode
        env.progress = self._progress
        try:
            report = self._u_engine.execute(
                plan,
                UninstallDecision(
                    confirm=True, research=ResearchDecision(action=action, dest=dest)
                ),
            )
        except UninstallRefused as exc:
            self._fatal(f"Uninstall refused: {exc}")
            return
        self._report = report
        self._show_report(_w.format_report_lines(report), close_app=True)

    # ── install ──────────────────────────────────────────────────────────

    def _i_show_consent(self) -> None:
        env = self._install_env
        assert env is not None  # enforced by __init__ for INSTALL mode
        engine = InstallEngine(env)
        self._i_engine = engine
        try:
            plan = engine.build_plan()
        except InstallError as exc:
            self._fatal(f"Install failed: {exc}")
            return
        self._i_plan = plan
        self._set_text("\n".join(_w.format_install_plan_lines(plan)))
        self._status_var.set(
            "Review what will be downloaded and where it will go. Nothing is "
            "installed system-wide; your browser is detected, never installed."
        )
        self._clear_form()
        extras = _w.extras_for_display(env.system, env.machine, _w.current_macos_version())
        row = 0
        ttk.Label(self._form, text="Optional extras (only what this machine can install):").grid(
            row=row, column=0, sticky=tk.W
        )
        row += 1
        self._extra_vars = {}
        for name, ok, reason in extras:
            var = tk.BooleanVar(value=False)
            self._extra_vars[name] = var
            button = ttk.Checkbutton(
                self._form,
                text=name if ok else f"{name} — {reason}",
                variable=var,
            )
            if not ok:
                button.state(["disabled"])
            button.grid(row=row, column=0, sticky=tk.W)
            row += 1
        self._clear_buttons()
        self._add_button(_w.install_action_label(plan.needs_download), self._i_run)
        self._add_button("Cancel", self._cancel)

    def _i_run(self) -> None:
        env = self._install_env
        assert env is not None  # enforced by __init__ for INSTALL mode
        env.extras = tuple(name for name, var in self._extra_vars.items() if var.get())
        # The explicit "Download and install" click IS the consent the
        # engine's structural gate requires — the screen just showed exactly
        # what execute() will download.
        env.assume_yes = True
        env.progress = self._progress
        self._clear_form()
        self._clear_buttons()
        self._set_text("Working…\n")
        try:
            report = self._i_engine.execute(self._i_plan)
        except InstallError as exc:
            self._fatal(f"Install failed: {exc}")
            return
        self._report = None
        self._show_report(_w.format_install_report_lines(report), close_app=False)
