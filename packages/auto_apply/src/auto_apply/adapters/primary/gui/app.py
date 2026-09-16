"""The main application window and UI state orchestrator.

This module defines the AutoApplyApp class, which serves as the root Tkinter
window. It implements the "Main Controller" pattern for the GUI, managing
transitions between high-level views:

    Onboarding (First Run) -> Session Config -> GUIDashboard

Architecture:
    AutoApplyApp is the highest-level UI component. It builds the
    CapabilitiesRegistry on startup and passes it down to child views.
    This is the critical architectural shift — the registry (not a raw
    profile) is the single source of truth for what the app can do.

    The registry flows downward:
        AutoApplyApp -> SettingsEditor  (locks admin-constrained fields)
        AutoApplyApp -> SessionController (configures the orchestrator)
        AutoApplyApp -> GUIDashboard (reads session state via EventBus)

It uses SessionController as the sole bridge to the backend. The GUI
never touches the orchestrator, database, or engines directly.

Threading Safety:
    All backend communication goes through SessionController methods.
    GUIDashboard polling uses Tkinter's after() scheduler, which runs
    callbacks on the main thread, avoiding cross-thread Tkinter access.

Menu Bar:
    File -> Settings opens the SettingsEditor modal.
    File -> Export Profile writes the active profile to a chosen directory.
    File -> Session History lists past runs from the reports directory.
    File -> Exit triggers graceful shutdown.
    Settings, Export Profile, and Session History are disabled until the
    relevant objects exist (registry for Settings/Export, controller for
    History).

Onboarding Contract:
    First-run onboarding builds a profile ENTIRELY from what the user types.
    It never loads the bundled template profile — the template carries a
    placeholder identity (a stranger's name, email, phone, address, fake
    reference, fake work history and placeholder legal declarations), and the
    old flow saved that identity under the user's chosen profile name. The
    fields the wizard asks for are derived from
    build_ui_schema(UserProfile, "en") filtered to required fields, so the
    profile model — not this file — is the single source of truth for "what
    a profile needs". Legal questions (work authorization, sponsorship) are
    asked explicitly as Yes/No radios with no preselection, because the
    model's defaults are themselves consequential claims and must never be
    saved without the user declaring them.

Profile Override:
    When ``profile_override`` is provided (from the ``--profile`` CLI flag),
    the bootstrap skips onboarding and profile selection, loading the named
    profile directly.

Results View (C2):
    When a session completes, a results window shows the discovered-job list
    (from the typed SessionSummary.discovered — read from job_history, so a
    DISCOVER_ONLY run's payoff is visible), with opt-in export buttons for
    the results CSV and the active profile. Nothing is written unless the
    user asks — that is the ruling for collect runs.

Activity and gates (D2):
    The 500 ms poll loop reads everything through the PORT —
    ``pending_approvals()`` for open HITL gates and ``recent_events()`` for
    the activity stream. There is no direct EventBus subscription anywhere
    in the GUI; the modal is driven by the poll, not by a broadcast.

Autonomy (stage E1):
    The session-config wizard shows the autonomy state and offers the
    control before every Start (gui/wizard.py). The dashboard marks a fully
    automated session with an ``AUTONOMY ON —`` prefix on its status line,
    and the results window names it, so a machine-decided run is always
    visible as one.
"""

import logging
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import ValidationError

from auto_apply.adapters.primary.gui.dashboard import Dashboard as GUIDashboard
from auto_apply.adapters.primary.gui.settings_editor import SettingsEditor
from auto_apply.adapters.primary.gui.strings import get_strings
from auto_apply.adapters.primary.gui.wizard import SessionConfigWizard as GUIWizard
from auto_apply.application.services.profile_validator import TEMPLATE_PROFILE_NAME
from auto_apply.application.services.ui_schema import UIField, build_ui_schema
from auto_apply.domain.models.profile import UserProfile, make_portable_path
from auto_apply.domain.models.ui_contract import (
    SessionHistoryEntry,
    SessionRequest,
    SessionSummary,
)
from auto_apply.domain.ports.profile_repository_port import ProfileRepositoryPort

if TYPE_CHECKING:
    from auto_apply.application.services.session_controller import SessionController
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# ONBOARDING FIELD DERIVATION (pure functions — testable without Tk)
# ═════════════════════════════════════════════════════════════════════════════


def _onboarding_schema_fields() -> list[UIField]:
    """Return the profile fields the onboarding wizard collects.

    Derived from build_ui_schema(UserProfile, "en") filtered to required —
    the same schema the settings editor and CLI wizard already trust. If the
    UserProfile model grows a required field, it appears here automatically;
    there is no second list in this file free to drift out of sync.

    Returns an empty list if the schema cannot be built (worst-case
    environment); the wizard then shows nothing and cannot proceed, which is
    the correct failure — it cannot silently fall back to a template.
    """
    try:
        return [f for f in build_ui_schema(UserProfile, "en") if f.required]
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not build onboarding field schema: %s", exc)
        return []


def _build_profile_from_onboarding(
    values: dict[str, str],
    legal_answers: dict[str, bool],
) -> UserProfile:
    """Build a UserProfile entirely from wizard input.

    Args:
        values: Map of schema field key -> user-entered text. Required keys
            are exactly the keys of _onboarding_schema_fields(), plus
            "personal_info.resume_path" (optional — needed for file uploads).
        legal_answers: The user's explicit answers to the two legal
            questions, keyed "has_work_authorization" and
            "requires_sponsorship". Both must be present — the wizard blocks
            submission until each question is answered Yes or No.

    Returns:
        A validated UserProfile containing ONLY what the user declared.
        references, work_experience and education are empty lists; nothing
        is inherited from any template.

    Raises:
        pydantic.ValidationError: If any field fails model validation.
    """
    titles_raw = values.get("search_preferences.desired_job_titles", "")
    titles = [t.strip() for t in titles_raw.split(",") if t.strip()]

    resume = values.get("personal_info.resume_path", "").strip()

    data: dict[str, Any] = {
        "profile_name": values.get("profile_name", "").strip(),
        "personal_info": {
            "first_name": values.get("personal_info.first_name", "").strip(),
            "last_name": values.get("personal_info.last_name", "").strip(),
            "email": values.get("personal_info.email", "").strip(),
            "phone_number": values.get("personal_info.phone_number", "").strip(),
            "street_address": values.get("personal_info.street_address", "").strip(),
            "city": values.get("personal_info.city", "").strip(),
            "state": values.get("personal_info.state", "").strip(),
            "zip_code": values.get("personal_info.zip_code", "").strip(),
            "resume_path": resume or None,
        },
        "links": {},
        "career_summary": values.get("career_summary", "").strip(),
        "search_preferences": {
            "desired_job_titles": titles,
        },
        "legal_info": {
            "has_work_authorization": bool(
                legal_answers["has_work_authorization"]
            ),
            "requires_sponsorship": bool(
                legal_answers["requires_sponsorship"]
            ),
        },
    }
    return UserProfile(**data)


# ═════════════════════════════════════════════════════════════════════════════
# RESULTS/HISTORY FORMATTING (pure functions — testable without Tk)
# ═════════════════════════════════════════════════════════════════════════════


def format_results_lines(summary: SessionSummary, limit: int = 200) -> list[str]:
    """Format the end-of-session results view as plain lines (no Tk required).

    Counts come first, then one line per discovered job with its URL on the
    next indented line — the discovered list is the payoff of a collect run.
    A session run with autonomy on is named plainly: a machine-decided run
    is labelled data, never passed off as a human-reviewed one.
    """
    lines = [
        f"Jobs discovered:    {summary.jobs_discovered}",
        f"Jobs vetted:        {summary.jobs_vetted}",
        f"Passed vetting:     {summary.jobs_passed_vetting}",
        f"Applied:            {summary.applications_submitted}",
        f"Failed:             {summary.applications_failed}",
        f"Duration:           {summary.duration_str}",
    ]
    if summary.autonomy_enabled:
        lines.append(
            "Autonomy: ON — submissions were authorized by policy "
            "(fully automated session)."
        )
    lines.append("")
    if summary.discovered:
        lines.append("Discovered jobs:")
        for idx, job in enumerate(summary.discovered[:limit], start=1):
            lines.append(f"  {idx:>3}. {job.title} — {job.company}")
            lines.append(f"       {job.url}")
        if len(summary.discovered) > limit:
            lines.append(f"  … and {len(summary.discovered) - limit} more")
    else:
        lines.append("No discovered jobs were recorded for this session.")
    if summary.gate_block_remedy:
        lines.append("")
        lines.append(summary.gate_block_remedy)
    if summary.report_path:
        lines.append("")
        lines.append(f"Full report: {summary.report_path}")
    return lines


def format_history_lines(entries: tuple[SessionHistoryEntry, ...]) -> list[str]:
    """Format session history entries as plain lines (no Tk required)."""
    if not entries:
        return ["No past sessions found."]
    lines: list[str] = []
    for entry in entries:
        stamp = entry.started_at[:16].replace("T", " ") if entry.started_at else "?"
        duration = _format_seconds(entry.duration_seconds)
        lines.append(
            f"{stamp} · {entry.completion_state} · {entry.profile_name or 'unknown'}"
        )
        lines.append(
            f"    found {entry.jobs_found} · vetted {entry.jobs_vetted} · "
            f"applied {entry.applications_submitted} · "
            f"failed {entry.applications_failed} · {duration}"
        )
        if entry.report_path:
            lines.append(f"    {entry.report_path}")
    return lines


def _format_seconds(total: float) -> str:
    """Format a duration in seconds as a compact human string."""
    total_i = int(total)
    minutes, seconds = divmod(total_i, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


# ═════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════════════════

class _ControllerFactory(Protocol):
    """The shape of ``composition_root.build_session_controller``.

    A bare ``Callable[[UserProfile], SessionController]`` declared one
    positional argument, so mypy rejected the ``profile_repo=`` keyword the
    call site has always passed and the factory has always accepted
    (``composition_root.build_session_controller(profile, profile_repo=None)``).
    A Protocol keeps that keyword type-checked instead of erasing the
    signature with ``Callable[..., SessionController]``.
    """

    def __call__(
        self,
        profile: "UserProfile",
        profile_repo: "ProfileRepositoryPort | None" = None,
    ) -> "SessionController": ...


class AutoApplyApp(tk.Tk):
    """The root window handling the application lifecycle and view switching.

    Lifecycle:
        1. __init__      -> Window created, menu bar built.
        2. _bootstrap    -> Checks for existing profiles.
        3. Onboarding OR _load_and_start -> Registry built, views shown.
        4. Session Config ->
        5. GUIDashboard  ->
        6. Results       ->
        7. _on_close     -> Graceful shutdown.

    The only backend dependency is SessionController. All orchestrator
    interaction happens through the controller.

    Args:
        build_registry: Factory for CapabilitiesRegistry from a UserProfile.
        create_controller: Factory for SessionController from a UserProfile.
        profile_repo: ProfileRepositoryPort for loading/saving profiles.
        profile_override: Optional profile name or path to load directly,
            skipping the onboarding and profile selection flows.  Set by
            the ``--profile`` CLI flag in ``main.py``.
    """

    POLL_INTERVAL_MS: int = 500

    def __init__(
        self,
        build_registry: "Callable[[UserProfile], CapabilitiesRegistry]",
        create_controller: "_ControllerFactory",
        profile_repo: ProfileRepositoryPort,
        profile_override: str | None = None,
    ) -> None:
        super().__init__()

        self._build_registry = build_registry
        self._create_controller = create_controller
        self._repo = profile_repo
        self._profile_override = profile_override
        self._strings = get_strings()

        self.profile: UserProfile | None = None
        self.controller: SessionController | None = None
        self.registry: CapabilitiesRegistry | None = None

        self.title(self._strings.get("app_title", "AutoApply"))
        self.geometry("900x700")
        self.minsize(800, 600)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Apply a consistent cross-platform theme.
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self._build_menu_bar()

        self._main_container = ttk.Frame(self)
        self._main_container.pack(fill=tk.BOTH, expand=True)

        # Defer bootstrap to allow the window to render first.
        self.after(100, self._bootstrap)

    # =====================================================================
    # MENU BAR
    # =====================================================================

    def _build_menu_bar(self) -> None:
        """Constructs the native top menu bar.

        Settings is disabled until the registry is successfully built.
        Export Profile and Session History are disabled until the objects
        they need exist (registry / controller, respectively).
        """
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Export Profile…",
            command=self._export_profile_dialog,
            state=tk.DISABLED,
        )
        file_menu.add_command(
            label="Session History…",
            command=self._show_session_history,
            state=tk.DISABLED,
        )
        file_menu.add_command(
            label="Settings", command=self._open_settings, state=tk.DISABLED,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        menubar.add_cascade(label="File", menu=file_menu)
        self._file_menu = file_menu

    # =====================================================================
    # LIFECYCLE
    # =====================================================================

    def _bootstrap(self) -> None:
        """Determines the startup state (first run vs. returning user).

        When ``_profile_override`` is set, attempts to load that profile
        directly and skips the onboarding / selection flow entirely.
        """
        # ── Profile override path (--profile flag) ──────────────────────
        if self._profile_override:
            logger.info(
                "Profile override active — loading directly | raw=%s",
                self._profile_override,
            )
            self._load_and_start(self._profile_override)
            return

        try:
            profiles = self._repo.list_profiles()
            user_profiles = [p for p in profiles if p != TEMPLATE_PROFILE_NAME]

            if not user_profiles:
                logger.info("No user profiles found — launching onboarding")
                self._show_onboarding()
            else:
                self._load_and_start(user_profiles[0])

        except Exception as exc:
            logger.critical("Bootstrap failed: %s", exc, exc_info=True)
            messagebox.showerror("Critical Error", f"Application failed to start: {exc}")  # noqa: E501
            self._on_close()

    # =====================================================================
    # ONBOARDING (first-run profile creation — built from user input ONLY)
    # =====================================================================

    def _show_onboarding(self) -> None:
        """Shows the first-run profile creation wizard embedded in the window.

        The wizard asks for every field the schema marks required, the resume
        path (needed for file uploads), and the two legal questions as
        explicit Yes/No radios. Nothing is written to disk until the complete
        profile validates through UserProfile and saves successfully.
        """
        self._clear_view()
        self.title("AutoApply — Create your profile")

        outer = ttk.Frame(self._main_container, padding=30)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer, text="Welcome to AutoApply",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            outer,
            text=(
                "Tell us about yourself to create your profile. Fields marked "
                "* are required. Nothing is saved until everything validates."
            ),
            foreground="gray",
            wraplength=780,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 18))

        fields = _onboarding_schema_fields()
        if not fields:
            ttk.Label(
                outer,
                text=(
                    "Could not determine which fields a profile needs "
                    "(schema unavailable). Cannot create a profile safely."
                ),
                foreground="red",
                wraplength=780,
                justify=tk.LEFT,
            ).pack(anchor=tk.W)
            return

        entries: dict[str, tk.StringVar] = {}
        grid = ttk.Frame(outer)
        grid.pack(fill=tk.X, anchor=tk.N)

        summary_key = "career_summary"
        summary_widget: tk.Text | None = None

        row = 0
        col = 0
        for field in fields:
            if field.key == summary_key:
                continue  # rendered below as a multiline box
            label_text = field.label + (" *" if field.required else "")
            ttk.Label(grid, text=label_text).grid(
                row=row, column=col * 2, sticky=tk.W, padx=(0, 6), pady=3
            )
            var = tk.StringVar()
            entries[field.key] = var
            ttk.Entry(grid, textvariable=var, width=32).grid(
                row=row, column=col * 2 + 1, sticky=tk.W, pady=3
            )
            col += 1
            if col == 2:
                col = 0
                row += 1

        # ── Career summary (multiline) ──────────────────────────────────
        row += 1
        ttk.Label(
            grid,
            text="Career summary * (2–3 sentences about your background; "
            "used for open-ended form questions)",
        ).grid(row=row, column=0, columnspan=4, sticky=tk.W, pady=(10, 2))
        row += 1
        summary_widget = tk.Text(grid, width=80, height=4, wrap=tk.WORD)
        summary_widget.grid(row=row, column=0, columnspan=4, sticky=tk.W)

        # ── Resume (optional, needed for file-upload fields) ────────────
        row += 1
        ttk.Label(grid, text="Resume (PDF or DOCX):").grid(
            row=row, column=0, sticky=tk.W, pady=(12, 3)
        )
        resume_var = tk.StringVar()
        entries["personal_info.resume_path"] = resume_var
        resume_frame = ttk.Frame(grid)
        resume_frame.grid(row=row, column=1, columnspan=3, sticky=tk.W, pady=(12, 3))
        ttk.Entry(
            resume_frame, textvariable=resume_var, width=45, state="readonly"
        ).pack(side=tk.LEFT)

        def browse_resume() -> None:
            path = filedialog.askopenfilename(
                filetypes=[
                    ("Resume files", "*.pdf *.docx *.txt"),
                    ("All files", "*.*"),
                ]
            )
            if path:
                resume_var.set(path)

        ttk.Button(resume_frame, text="Browse…", command=browse_resume).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        # ── Legal declarations (asked, never assumed) ───────────────────
        row += 1
        legal_frame = ttk.LabelFrame(
            grid,
            text="Work eligibility — please answer both",
            padding=10,
        )
        legal_frame.grid(
            row=row, column=0, columnspan=4, sticky=tk.W, pady=(16, 6)
        )

        auth_var = tk.StringVar(value="")
        sponsor_var = tk.StringVar(value="")

        ttk.Label(
            legal_frame,
            text="Are you legally authorized to work in the country you are "
            "applying to?",
        ).pack(anchor=tk.W)
        auth_row = ttk.Frame(legal_frame)
        auth_row.pack(anchor=tk.W, pady=(0, 8))
        ttk.Radiobutton(
            auth_row, text="Yes", variable=auth_var, value="yes"
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(
            auth_row, text="No", variable=auth_var, value="no"
        ).pack(side=tk.LEFT)

        ttk.Label(
            legal_frame,
            text="Will you now or in the future require visa sponsorship?",
        ).pack(anchor=tk.W)
        sponsor_row = ttk.Frame(legal_frame)
        sponsor_row.pack(anchor=tk.W)
        ttk.Radiobutton(
            sponsor_row, text="Yes", variable=sponsor_var, value="yes"
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(
            sponsor_row, text="No", variable=sponsor_var, value="no"
        ).pack(side=tk.LEFT)

        # ── Status + submit ─────────────────────────────────────────────
        status_var = tk.StringVar()
        ttk.Label(
            outer, textvariable=status_var, foreground="red", wraplength=780
        ).pack(anchor=tk.W, pady=(10, 4))

        def submit() -> None:
            values: dict[str, str] = {}
            missing: list[str] = []
            for field in fields:
                if field.key == summary_key:
                    value = summary_widget.get("1.0", "end-1c").strip() if summary_widget else ""
                else:
                    value = entries[field.key].get().strip()
                values[field.key] = value
                if field.required and not value:
                    missing.append(field.label)

            if missing:
                status_var.set(
                    "Please complete: " + ", ".join(missing[:6])
                    + ("…" if len(missing) > 6 else "")
                )
                return

            if auth_var.get() not in ("yes", "no") or sponsor_var.get() not in (
                "yes",
                "no",
            ):
                status_var.set(
                    "Please answer both work-eligibility questions (Yes or No)."
                )
                return

            legal_answers = {
                "has_work_authorization": auth_var.get() == "yes",
                "requires_sponsorship": sponsor_var.get() == "yes",
            }

            try:
                profile = _build_profile_from_onboarding(values, legal_answers)
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {}
                where = " → ".join(str(p) for p in first.get("loc", ())) or "profile"
                status_var.set(f"{where}: {first.get('msg', 'invalid value')}")
                return

            name = profile.profile_name
            try:
                self._repo.save_profile(profile)
            except Exception as exc:  # noqa: BLE001
                logger.error("Onboarding save failed: %s", exc, exc_info=True)
                status_var.set(f"Could not save the profile: {exc}")
                return

            logger.info("Profile '%s' created via onboarding wizard", name)
            self._load_and_start(name)

        ttk.Button(
            outer, text="Create Profile & Continue →", command=submit
        ).pack(anchor=tk.W, pady=8)

    def _load_and_start(self, profile_name: str) -> None:
        """Builds the CapabilitiesRegistry and switches to session config.

        Loads the profile through ProfileRepository (single validation path),
        then passes the validated object to the registry. The registry never
        touches the filesystem for profile data.
        """
        logger.info("Loading registry for profile: %s", profile_name)

        try:
            # Load through the repo — this is the single validation path.
            loaded_profile = self._repo.load_profile(profile_name)
            if loaded_profile is None:
                raise ValueError(f"Profile '{profile_name}' could not be loaded.")

            # Pass the validated object, not a file‑path.
            self.registry = self._build_registry(loaded_profile)
            self.profile = self.registry.get_active_profile()

        except Exception as exc:
            logger.error("Registry build failed | error=%s", exc, exc_info=True)
            messagebox.showerror("Error", f"Failed to initialize: {exc}")
            self._on_close()
            return

        if not self.profile:
            messagebox.showerror("Error", f"Failed to load profile '{profile_name}'.")
            self._on_close()
            return

        self.title(f"{self._strings['app_title']} - {self.profile.full_name}")
        self._file_menu.entryconfig("Settings", state=tk.NORMAL)
        self._file_menu.entryconfig("Export Profile…", state=tk.NORMAL)
        self._show_session_config()

    def _on_close(self) -> None:
        """Handles window close: stops the controller and exits."""
        logger.info("Application shutdown requested")
        # Future: call SessionController.stop() here when wired.
        if self.controller:
            self.controller.stop()

        self.destroy()
        sys.exit(0)

    # =====================================================================
    # SETTINGS EDITOR
    # =====================================================================

    def _open_settings(self) -> None:
        """Opens the Settings Editor modal with the current registry."""
        # Bind profile to a local so mypy narrows it for the closure below —
        # narrowing does not survive into closures for instance attributes.
        profile = self.profile
        if not self.registry or profile is None:
            return

        def _on_save():
            # Rebuild the registry so effective_config reflects saved changes.
            # Only the UserProfile object is needed; no file‑path is required.
            self.registry = self._build_registry(profile)
            self.profile = self.registry.get_active_profile()
            logger.info("Settings saved — registry rebuilt")

        SettingsEditor(self, registry=self.registry, on_save=_on_save, profile_repo=self._repo)

    # =====================================================================
    # CUSTODY DIALOGS (C2)
    # =====================================================================

    def _export_profile_dialog(self) -> None:
        """Export the active profile to a user-chosen directory."""
        if self.controller is None or self.profile is None:
            return
        directory = filedialog.askdirectory(
            title="Choose a folder for the profile export"
        )
        if not directory:
            return
        try:
            path = self.controller.export_profile(
                self.profile.profile_name, Path(directory)
            )
            messagebox.showinfo(
                "Profile exported",
                f"Profile written to:\n{path}\n\n"
                "(plaintext JSON — readable on any machine, no password needed)",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Profile export failed: %s", exc)
            messagebox.showerror("Export failed", str(exc))

    def _export_results_dialog(self) -> None:
        """Export the current session's discovered jobs to a CSV file."""
        if self.controller is None:
            return
        directory = filedialog.askdirectory(
            title="Choose a folder for the results CSV"
        )
        if not directory:
            return
        try:
            path = self.controller.export_session_results(Path(directory))
            messagebox.showinfo("Results exported", f"Results written to:\n{path}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Results export failed: %s", exc)
            messagebox.showerror("Export failed", str(exc))

    def _show_session_history(self) -> None:
        """Opens the session history window (past runs from the reports dir)."""
        if self.controller is None:
            return
        entries = self.controller.list_session_history()
        lines = format_history_lines(entries)

        win = tk.Toplevel(self)
        win.title("Session History")
        win.geometry("760x480")
        win.transient(self)

        ttk.Label(
            win,
            text="Past sessions (newest first)",
            font=("Segoe UI", 12, "bold"),
            padding=10,
        ).pack(anchor=tk.W)

        viewer = ScrolledText(win, state="disabled", wrap=tk.WORD, font=("Consolas", 9))
        viewer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        viewer.configure(state="normal")
        viewer.insert(tk.END, "\n".join(lines))
        viewer.configure(state="disabled")

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    # =====================================================================
    # VIEW MANAGEMENT (display)
    # =====================================================================

    def _show_session_config(self) -> None:
        """Shows the session configuration wizard.

        The wizard emits a typed SessionRequest (stage U3) and calls back
        into _on_session_start with it. It also shows the autonomy state and
        offers the control before every Start (stage E1).
        """
        self._clear_view()
        wizard = GUIWizard(
            parent=self._main_container,
            on_complete=self._on_session_start,
            profile=self.profile,
            profile_repo=self._repo,
            controller=self.controller,
        )
        wizard.pack(fill=tk.BOTH, expand=True)

    def _show_guidashboard(self) -> None:
        """Shows the live session gui dashboard."""
        self._clear_view()
        self._guidashboard = GUIDashboard(self._main_container)
        # bind_session wires the dashboard to the session's controller so the
        # polled HITL modal can call provide_approval. Nothing is subscribed
        # to any bus — the poll in _poll_guidashboard drives both the modal
        # and the activity feed through the port.
        if self.controller is not None:
            self._guidashboard.bind_session(self.controller)
        self._guidashboard.pack(fill=tk.BOTH, expand=True)
        self._poll_guidashboard()

    def _clear_view(self) -> None:
        """Destroys all children of the main container."""
        for widget in self._main_container.winfo_children():
            widget.destroy()

    # =========================================================================
    # SESSION STARTUP
    # =========================================================================

    def _on_session_start(self, request: SessionRequest) -> None:
        """Callback when user clicks 'Start' in the wizard.

        This is where the UI connects to the backend:
            1. Build SessionController from the loaded profile.
            2. Translate the typed SessionRequest into WorkUnits.
            3. Start the orchestrator background thread.
            4. Switch to the guidashboard view.
        """
        logger.info("Session start requested | request=%s", request)

        if self.profile is None:
            messagebox.showerror("Session Error", "No profile is loaded.")
            return

        try:
            # 1. Build controller (this builds CapabilitiesRegistry internally).
            self.controller = self._create_controller(self.profile, profile_repo=self._repo)

            # Custody menu items become available now that a controller exists.
            self._file_menu.entryconfig("Session History…", state=tk.NORMAL)

            # 2. Seed the work queue with initial tasks.
            task_count = self.controller.initialize_session(request)
            logger.info("Queued %d initial tasks", task_count)

            # 3. Start the background orchestrator thread.
            self.controller.start()

            # 4. Switch to the live gui dashboard.
            self._show_guidashboard()

        except Exception as exc:
            logger.error("Session start failed: %s", exc, exc_info=True)
            messagebox.showerror(
                "Session Error",
                f"Failed to start session: {exc}",
            )

    # =========================================================================
    # GUIDASHBOARD POLLING
    # =========================================================================

    def _poll_guidashboard(self) -> None:
        """Periodically updates the gui dashboard with live session stats.

        Runs on the Tkinter main thread via after(). Reads stats from
        SessionController (thread-safe) and pushes them to the gui dashboard view.
        Also polls HITL gates and the activity stream through the port (D2).
        A session with autonomy on is marked plainly on the status line (E1).
        """
        if not self.controller or not hasattr(self, "_guidashboard"):
            return

        try:
            stats = self.controller.get_stats()
            state = self.controller.get_current_state()

            self._guidashboard.update_metric("discovered", stats.get("jobs_discovered", 0))  # noqa: E501
            self._guidashboard.update_metric("vetted", stats.get("jobs_vetted", 0))
            self._guidashboard.update_metric("applied", stats.get("applications_submitted", 0))  # noqa: E501
            self._guidashboard.update_metric("failed", stats.get("applications_failed", 0))  # noqa: E501

            state_labels = {
                "DISCOVERING": "Searching for jobs...",
                "VETTING": "Analyzing job fit...",
                "APPLYING": "Submitting applications...",
                "IDLE": "Waiting...",
                "PAUSED": "Paused",
                "STOPPED": "Session complete",
            }
            label = state_labels.get(state, state)
            if self.controller.autonomy():
                label = f"AUTONOMY ON — {label}"
            self._guidashboard.update_progress(0, 0, label)

            # ── HITL gates and the activity stream, polled through the port
            # (D2). No direct EventBus subscription anywhere in the GUI.
            approvals = self.controller.pending_approvals()
            if approvals:
                self._guidashboard.show_approval(approvals[0])
            self._guidashboard.feed_activity(self.controller.recent_events())

            # If the session ended, stop polling.
            if not self.controller.is_running and state in ("STOPPED", "FAILED"):
                self._on_session_complete()
                return

        except Exception as exc:
            logger.debug("GUIDashboard poll error: %s", exc)

        # Schedule next poll.
        self.after(self.POLL_INTERVAL_MS, self._poll_guidashboard)

    def _on_session_complete(self) -> None:
        """Called when the orchestrator thread exits."""
        logger.info("Session complete — showing results")
        if self.controller is None:
            logger.warning("Session complete with no controller — nothing to report")
            return
        summary = self.controller.summary()
        self._show_results_window(summary)

    def _show_results_window(self, summary: SessionSummary) -> None:
        """Shows the end-of-session results window (C2).

        Counts first, then the discovered-job list (the collect-run payoff),
        with opt-in export buttons. Run Again returns to session config;
        Close exits the application. A session run with autonomy on is named
        plainly in the results text (E1).
        """
        win = tk.Toplevel(self)
        win.title("Session Complete")
        win.geometry("820x560")
        win.transient(self)

        counts = (
            f"Jobs Discovered: {summary.jobs_discovered}    "
            f"Jobs Vetted: {summary.jobs_vetted}    "
            f"Applied: {summary.applications_submitted}    "
            f"Failed: {summary.applications_failed}    "
            f"Duration: {summary.duration_str}"
        )
        ttk.Label(win, text=counts, font=("Segoe UI", 10, "bold"), padding=10).pack(
            anchor=tk.W
        )

        viewer = ScrolledText(win, state="disabled", wrap=tk.WORD, font=("Consolas", 9))
        viewer.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        viewer.configure(state="normal")
        viewer.insert(tk.END, "\n".join(format_results_lines(summary)))
        viewer.configure(state="disabled")

        button_row = ttk.Frame(win, padding=10)
        button_row.pack(fill=tk.X)

        ttk.Button(
            button_row,
            text="Export Results (CSV)…",
            command=self._export_results_dialog,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            button_row,
            text="Export Profile…",
            command=self._export_profile_dialog,
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            button_row,
            text="Session History…",
            command=self._show_session_history,
        ).pack(side=tk.LEFT, padx=(0, 6))

        def _run_again() -> None:
            win.destroy()
            self._show_session_config()

        ttk.Button(button_row, text="Run Another Session", command=_run_again).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        def _close_and_quit() -> None:
            win.destroy()
            self._on_close()

        ttk.Button(
            button_row,
            text="Close",
            command=_close_and_quit,
        ).pack(side=tk.RIGHT)
