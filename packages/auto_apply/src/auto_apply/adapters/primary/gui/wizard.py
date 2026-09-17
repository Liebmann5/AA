"""Session configuration wizard for the AutoApply GUI.

Emits a typed SessionRequest — the same object
SessionController.initialize_session accepts on its preferred path. All four
EntryPoint members are offered, and the exit axis mirrors the CLI: the option
sets and every user-facing label come from domain/models/ui_contract.py, so
both adapters describe the same choice with the same words. Do not hardcode
label strings here; add them to ui_contract.py and let both surfaces read
them — the parity pin asserts both adapters import the same objects.

Layout ruling (one screen, not steps):
    The CLI is sequential because a terminal cannot show two prompts at once.
    This panel shows the whole decision at a glance in two columns — entry
    point and outcome on the left, criteria on the right — because steps
    would add navigation state to a 66-line file that had none, for no
    measured benefit. Density is bounded: four entry radios, at most three
    outcome radios, three provider checkboxes, three criteria fields — two
    columns of ≤8 rows each, inside a window whose minimum is already
    800x600 (app.py minsize). This screen therefore cannot hit the Settings
    dialog's failure mode (12+ rows at 1366x768 losing its Save button).
    Sections that do not apply to the chosen entry point are hidden, not
    disabled: pasted links do not search engines, so keywords/location/
    providers vanish for URL entries rather than being asked and ignored.

Testability: request-building is a module-level pure function
(build_session_request) that the widget calls on Start. Tests exercise it
directly — no display, no Tk construction required.

Autonomy (stage E1):
    The state line above the entry choices shows whether this session will
    submit without asking, and a "Change…" button opens the control. The
    flow honours the maintainer's ruling: enabling requires two
    differently-worded warnings (the first describes the behaviour change,
    the second names the consequence — real name and email, irreversible,
    recorded as automated); disabling needs one confirmation. The write goes
    through SessionController.set_autonomy when a controller exists, else
    the shared application-layer helper (apply_autonomy) — one
    implementation, two entry points, identical semantics. The new value
    applies to the next session built from the profile; a running session's
    policy is frozen and never changes.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from auto_apply.application.services.autonomy import (
    apply_autonomy,
    autonomy_enabled_for_profile,
)
from auto_apply.domain.models.session_plan import SessionExecutionMode
from auto_apply.domain.models.ui_contract import (
    ENTRY_POINT_LABELS,
    EntryPoint,
    SessionRequest,
    outcome_options_for_entry,
    provider_vocabulary,
)

_DEFAULT_MAX_RESULTS = 100


def build_session_request(
    *,
    entry: EntryPoint,
    execution_mode: SessionExecutionMode,
    keywords_text: str = "",
    location: str = "",
    max_results: int | None = None,
    urls_text: str = "",
    providers: tuple[str, ...] = (),
) -> SessionRequest:
    """Assembles the SessionRequest from wizard field values.

    Pure function — the widget calls it on Start, and tests call it directly
    without a display. Splitting on commas (keywords) and newlines (urls)
    happens here, not in the widget, so the request shape is testable end to
    end.

    providers is only meaningful on the search path: pasted links and company
    pages do not fan out to the SERP engines, so a non-SEARCH entry yields
    providers=() regardless of what was passed — the same rule the CLI
    enforces by not asking the question there.
    """
    keywords = tuple(t.strip() for t in keywords_text.split(",") if t.strip())
    urls = tuple(u.strip() for u in urls_text.splitlines() if u.strip())
    if entry is EntryPoint.SEARCH:
        return SessionRequest(
            entry=entry,
            execution_mode=execution_mode,
            keywords=keywords,
            location=location.strip(),
            max_results=max_results,
            providers=providers,
        )
    return SessionRequest(
        entry=entry,
        execution_mode=execution_mode,
        urls=urls,
    )


def autonomy_state_text(enabled: bool) -> str:
    """The one-line autonomy state shown above the entry choices.

    Pure function — the widget binds it to a label, and tests read it
    directly without Tk. It states the behaviour, not the mechanism: a user
    asking "is AA going to ask me?" gets a yes/no sentence, never jargon
    about checkpoints.
    """
    if enabled:
        return "Autonomy: ON — AutoApply will submit applications without asking."
    return "Autonomy: OFF — AutoApply will ask before each submission."


class SessionConfigWizard(ttk.Frame):
    """One-screen session configuration panel emitting a SessionRequest.

    The layout is two columns: entry point and outcome on the left, criteria
    (or a links box) on the right. Entry changes re-render the outcome
    options and swap which right-hand section is visible.
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_complete: Callable[[SessionRequest], None],
        profile=None,
        profile_repo=None,
        controller=None,
    ) -> None:
        super().__init__(parent)
        self.on_complete = on_complete
        self._profile = profile
        self._profile_repo = profile_repo
        self._controller = controller

        self._entry_var = tk.StringVar(value=EntryPoint.SEARCH.name)
        self._outcome_var = tk.IntVar(value=0)
        self._keywords_var = tk.StringVar(value="")
        self._location_var = tk.StringVar(value="")
        self._max_var = tk.IntVar(value=_DEFAULT_MAX_RESULTS)
        self._status_var = tk.StringVar(value="")
        self._autonomy_var = tk.StringVar(value="")
        # All engines checked by default — the GUI's presentation of "use
        # every site" (the CLI's equivalent is an empty answer → plan default).
        self._provider_vars: dict[str, tk.BooleanVar] = {
            name: tk.BooleanVar(value=True) for name in provider_vocabulary()
        }

        self._build_layout()
        self._entry_var.trace_add("write", lambda *_: self._render_for_entry())
        self._render_for_entry()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=15)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer, text="Session Setup", font=("Segoe UI", 14, "bold")
        ).pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Choose what AutoApply should do, then press Start.",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(2, 12))

        # ── Autonomy state + control (stage E1) ──────────────────────────
        if self._profile is not None:
            self._autonomy_var.set(
                autonomy_state_text(autonomy_enabled_for_profile(self._profile))
            )
        state_row = ttk.Frame(outer)
        state_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            state_row, textvariable=self._autonomy_var, foreground="#555555"
        ).pack(side=tk.LEFT)
        if self._profile_repo is not None:
            ttk.Button(
                state_row, text="Change…", command=self._change_autonomy
            ).pack(side=tk.LEFT, padx=(10, 0))

        columns = ttk.Frame(outer)
        columns.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(columns)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15))
        right = ttk.Frame(columns)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        entry_box = ttk.LabelFrame(left, text="What do you want to do?", padding=8)
        entry_box.pack(fill=tk.X, pady=(0, 10))
        for entry, label in ENTRY_POINT_LABELS.items():
            ttk.Radiobutton(
                entry_box, text=label, variable=self._entry_var, value=entry.name
            ).pack(anchor=tk.W)

        self._outcome_box = ttk.LabelFrame(
            left, text="How far should AutoApply go?", padding=8
        )
        self._outcome_box.pack(fill=tk.X)
        self._outcome_frame = ttk.Frame(self._outcome_box)
        self._outcome_frame.pack(fill=tk.X)

        # Criteria — visible for SEARCH only.
        self._criteria_box = ttk.LabelFrame(right, text="Search criteria", padding=8)
        ttk.Label(self._criteria_box, text="Job titles (comma-separated):").pack(anchor=tk.W)
        ttk.Entry(self._criteria_box, textvariable=self._keywords_var).pack(
            fill=tk.X, pady=(0, 6)
        )
        ttk.Label(self._criteria_box, text="Location:").pack(anchor=tk.W)
        ttk.Entry(self._criteria_box, textvariable=self._location_var).pack(
            fill=tk.X, pady=(0, 6)
        )
        ttk.Label(self._criteria_box, text="Max results per search:").pack(anchor=tk.W)
        ttk.Spinbox(
            self._criteria_box, from_=1, to=500, textvariable=self._max_var, width=8
        ).pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(self._criteria_box, text="Job sites:").pack(anchor=tk.W)
        for name, var in self._provider_vars.items():
            ttk.Checkbutton(self._criteria_box, text=name, variable=var).pack(anchor=tk.W)
        ttk.Label(
            self._criteria_box,
            text="Leave titles and location blank to use your profile's defaults.",
            foreground="gray",
            font=("Segoe UI", 8, "italic"),
            wraplength=280,
        ).pack(anchor=tk.W, pady=(6, 0))

        # Links — visible for the three URL entries.
        self._links_box = ttk.LabelFrame(right, text="", padding=8)
        self._links_text = tk.Text(self._links_box, height=12, wrap=tk.WORD)
        self._links_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer, textvariable=self._status_var, foreground="#B8860B"
        ).pack(anchor=tk.W, pady=(10, 2))
        ttk.Button(outer, text="Start Session 🚀", command=self._finish).pack(anchor=tk.W)

    def _render_for_entry(self) -> None:
        entry = EntryPoint[self._entry_var.get()]

        for child in self._outcome_frame.winfo_children():
            child.destroy()
        self._outcome_var.set(0)
        for i, (label, _mode) in enumerate(outcome_options_for_entry(entry)):
            ttk.Radiobutton(
                self._outcome_frame, text=label, variable=self._outcome_var, value=i
            ).pack(anchor=tk.W)

        if entry is EntryPoint.SEARCH:
            self._links_box.pack_forget()
            self._criteria_box.pack(fill=tk.BOTH, expand=True)
        else:
            self._criteria_box.pack_forget()
            self._links_box.config(
                text=(
                    "Careers page URLs (one per line)"
                    if entry is EntryPoint.COMPANY_PAGES
                    else "Job links (one per line)"
                )
            )
            self._links_box.pack(fill=tk.BOTH, expand=True)

    # ── autonomy control (stage E1) ───────────────────────────────────────────

    def _change_autonomy(self) -> None:
        """Offers the autonomy choice with the maintainer's two-warning rule.

        Enabling shows two differently-worded warnings — the first describes
        the behaviour change (no review prompt, ever), the second names the
        consequence the first did not (real name and email, irreversible,
        recorded as automated). Both must be confirmed. Disabling needs one
        confirmation — turning autonomy off is always safe.
        """
        if self._profile is None or self._profile_repo is None:
            return
        current = autonomy_enabled_for_profile(self._profile)

        if current:
            if messagebox.askyesno(
                "Turn autonomy OFF?",
                "AutoApply will ask before each submission from now on.\n\nContinue?",
            ):
                self._apply_autonomy(False, ())
            return

        if not messagebox.askyesno(
            "Turn autonomy ON? (warning 1 of 2)",
            "AutoApply will submit each application IMMEDIATELY, without asking\n"
            "you to review or confirm it first.\n\nContinue?",
        ):
            return
        if not messagebox.askyesno(
            "Turn autonomy ON? (warning 2 of 2)",
            "Applications go out under your real name and email address, cannot\n"
            "be recalled once sent, and this session is recorded as fully automated.\n\n"
            "Really turn autonomy ON?",
        ):
            return
        self._apply_autonomy(True, ("yes", "yes"))

    def _apply_autonomy(self, enabled: bool, acknowledgements: tuple[str, ...]) -> None:
        """Applies the choice through the port when possible, else the helper.

        The port (SessionController.set_autonomy) is the typed contract; the
        shared helper (apply_autonomy) is the same implementation it
        delegates to. Both write the profile and persist it; neither touches
        a running session's policy. The label updates only on success.
        """
        if self._controller is not None:
            applied = self._controller.set_autonomy(enabled, acknowledgements)
        else:
            applied = apply_autonomy(
                self._profile, self._profile_repo, enabled, acknowledgements
            )
        if applied:
            self._autonomy_var.set(autonomy_state_text(enabled))
            self._status_var.set(
                "Autonomy updated — it applies when you press Start."
            )
        else:
            self._status_var.set("Autonomy was not changed.")

    # ── finish ────────────────────────────────────────────────────────────────

    def _finish(self) -> None:
        entry = EntryPoint[self._entry_var.get()]
        options = outcome_options_for_entry(entry)
        idx = self._outcome_var.get()
        mode = options[idx][1] if 0 <= idx < len(options) else options[0][1]
        providers = (
            tuple(n for n, v in self._provider_vars.items() if v.get())
            if entry is EntryPoint.SEARCH
            else ()
        )
        request = build_session_request(
            entry=entry,
            execution_mode=mode,
            keywords_text=self._keywords_var.get(),
            location=self._location_var.get(),
            max_results=self._max_var.get() if entry is EntryPoint.SEARCH else None,
            urls_text=self._links_text.get("1.0", "end-1c"),
            providers=providers,
        )
        # URL entries with no links are the GUI's "nothing to do" case — the
        # CLI returns None there. Block Start rather than begin a zero-task
        # session that idles forever (the old GUI's failure mode).
        if not request.is_actionable():
            self._status_var.set("Paste at least one link to continue.")
            return
        self.on_complete(request)
