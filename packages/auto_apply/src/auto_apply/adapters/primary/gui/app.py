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
    File -> Exit triggers graceful shutdown.
    Settings is disabled until the registry is successfully built.

Profile Override:
    When ``profile_override`` is provided (from the ``--profile`` CLI flag),
    the bootstrap skips onboarding and profile selection, loading the named
    profile directly.
"""

import logging
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any

from auto_apply.adapters.primary.gui.dashboard import Dashboard as GUIDashboard
from auto_apply.adapters.primary.gui.settings_editor import SettingsEditor
from auto_apply.adapters.primary.gui.strings import get_strings
from auto_apply.adapters.primary.gui.wizard import SessionConfigWizard as GUIWizard
from auto_apply.domain.models.profile import UserProfile

if TYPE_CHECKING:
    from auto_apply.adapters.secondary.persistence.profile_repository import ProfileRepository
    from auto_apply.application.services.session_controller import SessionController
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════════════════

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
        profile_repo: ProfileRepository for loading/saving profiles.
        profile_override: Optional profile name or path to load directly,
            skipping the onboarding and profile selection flows.  Set by
            the ``--profile`` CLI flag in ``main.py``.
    """

    POLL_INTERVAL_MS: int = 500

    def __init__(
        self,
        build_registry: "Callable[[UserProfile], CapabilitiesRegistry]",
        create_controller: "Callable[[UserProfile], SessionController]",
        profile_repo: "ProfileRepository",
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
        """
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
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
            user_profiles = [p for p in profiles if p != "default_profile"]

            if not user_profiles:
                logger.info("No user profiles found — launching onboarding")
                self._show_onboarding()
            else:
                self._load_and_start(user_profiles[0])

        except Exception as exc:
            logger.critical("Bootstrap failed: %s", exc, exc_info=True)
            messagebox.showerror("Critical Error", f"Application failed to start: {exc}")  # noqa: E501
            self._on_close()

    def _show_onboarding(self) -> None:
        """Shows onboarding UI embedded in the main window (not a Toplevel)."""
        self._clear_view()
        self.title("AutoApply — Welcome")

        frame = ttk.Frame(self._main_container, padding=40)
        frame.pack(expand=True)

        ttk.Label(
            frame, text="Welcome to AutoApply",
            font=("Segoe UI", 18, "bold"),
        ).pack(pady=(0, 8))
        ttk.Label(
            frame,
            text="Create your profile to get started.",
            foreground="gray",
        ).pack(pady=(0, 24))

        ttk.Label(frame, text="Profile Name (e.g. 'John-Dev'):").pack(anchor=tk.W)
        name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=name_var, width=40).pack(anchor=tk.W, pady=(4, 16))

        ttk.Label(frame, text="Resume (PDF or DOCX):").pack(anchor=tk.W)
        file_frame = ttk.Frame(frame)
        file_frame.pack(anchor=tk.W, fill=tk.X, pady=(4, 24))
        resume_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=resume_var, width=35, state="readonly").pack(
            side=tk.LEFT
        )

        def browse():
            path = filedialog.askopenfilename(
                filetypes=[
                    ("Resume files", "*.pdf *.docx *.txt"),
                    ("All files", "*.*"),
                ]
            )
            if path:
                resume_var.set(path)

        ttk.Button(file_frame, text="Browse…", command=browse).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        status_var = tk.StringVar()
        status_label = ttk.Label(frame, textvariable=status_var, foreground="red")
        status_label.pack(pady=(0, 12))

        def submit():
            name = name_var.get().strip()
            resume = resume_var.get().strip()
            if not name:
                status_var.set("Please enter a profile name.")
                return
            if not resume:
                status_var.set("Please select your resume file.")
                return
            try:
                default = self._repo.load_profile("default_profile")
                if not default:
                    raise FileNotFoundError("Default profile template missing.")
                default.profile_name = name
                default.personal_info.resume_path = Path(resume)
                self._repo.save_profile(default)
                logger.info("Profile '%s' created via onboarding", name)
                self._load_and_start(name)
            except Exception as exc:
                logger.error("Onboarding failed: %s", exc, exc_info=True)
                status_var.set(f"Error: {exc}")

        ttk.Button(
            frame, text="Create Profile & Continue →",
            command=submit,
        ).pack(pady=8)

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

            # Pass the validated object, not a path.
            self.registry = self._build_registry(user_profile=loaded_profile)
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
        if not self.registry:
            return

        def _on_save():
            # Rebuild the registry so effective_config reflects saved changes.
            # Only the UserProfile object is needed; no file‑path is required.
            self.registry = self._build_registry(user_profile=self.profile)
            self.profile = self.registry.get_active_profile()
            logger.info("Settings saved — registry rebuilt")

        SettingsEditor(self, registry=self.registry, on_save=_on_save, profile_repo=self._repo)

    # =====================================================================
    # VIEW MANAGEMENT (display)
    # =====================================================================

    def _show_session_config(self) -> None:
        """Shows the session configuration wizard."""
        self._clear_view()
        wizard = GUIWizard(
            parent=self._main_container,
            mode="discovery",
            on_complete=self._on_session_start,
        )
        wizard.pack(fill=tk.BOTH, expand=True)

    def _show_guidashboard(self) -> None:
        """Shows the live session gui dashboard."""
        self._clear_view()
        self._guidashboard = GUIDashboard(self._main_container)
        self._guidashboard.pack(fill=tk.BOTH, expand=True)
        self._poll_guidashboard()

    def _clear_view(self) -> None:
        """Destroys all children of the main container."""
        for widget in self._main_container.winfo_children():
            widget.destroy()

    # =========================================================================
    # SESSION STARTUP
    # =========================================================================

    def _on_session_start(self, config: dict[str, Any]) -> None:
        """Callback when user clicks 'Start' in the wizard.

        This is where the UI connects to the backend:
            1. Build SessionController from the loaded profile.
            2. Translate the wizard config into WorkUnits.
            3. Start the orchestrator background thread.
            4. Switch to the guidashboard view.
        """
        logger.info("Session start requested | config=%s", config)

        try:
            # 1. Build controller (this builds CapabilitiesRegistry internally).
            self.controller = self._create_controller(self.profile)

            # 2. Seed the work queue with initial tasks.
            task_count = self.controller.initialize_session(config)
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
            self._guidashboard.update_progress(0, 0, label)

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
        stats = self.controller.get_stats()

        summary = (
            f"Jobs Discovered: {stats.get('jobs_discovered', 0)}\n"
            f"Jobs Approved: {stats.get('jobs_vetted', 0)}\n"
            f"Applications Sent: {stats.get('applications_submitted', 0)}\n"
            f"Applications Failed: {stats.get('applications_failed', 0)}\n"
            f"Duration: {stats.get('duration_str', 'N/A')}"
        )

        result = messagebox.askquestion(
            "Session Complete",
            f"{summary}\n\nWould you like to run another session?",
        )

        if result == "yes":
            self._show_session_config()
        else:
            self._on_close()