"""Provides a graphical editor for User Profile and Application Settings.

This module implements a Toplevel dialog that allows users to modify their
configuration (ApplicationConfig, SearchPreferences, Politeness). It reads
the CapabilitiesRegistry to determine if any settings are locked by an
AdminPolicy (Library Mode) and disables those UI elements accordingly,
providing clear visual feedback with a lock icon (🔒).

Admin Lock Behavior:
    When a field is locked by admin policy, the UI element is disabled (greyed
    out), the label shows a lock icon, and the save logic skips that field
    entirely — the user's base profile is never overwritten with the admin's
    temporary enforcement value.

    Lockable fields (all in the Safety & Throttling and Browser tabs):
        - force_headless          -> Headless mode checkbox
        - max_applications_per_session -> Daily limit spinbox
        - force_humanization      -> Humanization checkbox
        - force_respect_robots_txt -> Robots.txt checkbox
        - min_action_delay_seconds -> Action delay spinbox
        - allowed_browsers        -> Browser dropdown (filtered, not disabled)
"""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from auto_apply.adapters.primary.gui.strings import get_strings
from auto_apply.application.services.ui_schema import UIField, build_ui_schema
from auto_apply.domain.models.policy import AdminPolicy
from auto_apply.domain.models.profile import UserProfile

if TYPE_CHECKING:
    from auto_apply.adapters.secondary.persistence.profile_repository import ProfileRepository
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry


class SettingsEditor(tk.Toplevel):
    """A modal window for editing user settings using a tabbed interface.

    Injects CapabilitiesRegistry instead of a raw profile so the UI can
    dynamically grey out fields locked by admin policy.
    """

    def __init__(
        self,
        parent: tk.Widget,
        registry: "CapabilitiesRegistry",
        on_save: Callable[[], None],
        profile_repo: "ProfileRepository",
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.profile = registry.get_active_profile()
        self.admin_policy = registry.get_admin_policy() or AdminPolicy.empty()
        self.on_save_callback = on_save
        self.strings = get_strings()
        self.repo = profile_repo

        self.title(f"Settings - {self.profile.profile_name}")
        self.geometry("700x650")
        self.transient(parent)
        self.grab_set()

        self._vars = {}

        try:
            self._ui_schema: list[UIField] = build_ui_schema(UserProfile, "en")
        except Exception:
            self._ui_schema = []

        self._build_ui()

    # =====================================================================
    # UI CONSTRUCTION
    # =====================================================================

    def _build_ui(self) -> None:
        """Constructs the tabbed interface."""
        container = ttk.Frame(self, padding="15")
        container.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        self._build_browser_tab(notebook)
        self._build_search_tab(notebook)
        self._build_safety_tab(notebook)
        self._build_documents_tab(notebook)

        # Admin banner (shown only when constraints are active)
        if self.admin_policy.has_any_constraint():
            banner = ttk.Label(
                container,
                text="Some settings are locked by your System Administrator.",
                font=("Segoe UI", 9, "italic"),
                foreground="#B8860B",
            )
            banner.pack(anchor=tk.W, pady=(10, 0))

        # Footer buttons
        btn_frame = ttk.Frame(container, padding="0 10 0 0")
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btn_frame, text="Save Changes", command=self._save_changes).pack(
            side=tk.RIGHT, padx=5
        )

    def _build_browser_tab(self, notebook: ttk.Notebook) -> None:
        """Tab 1: Browser Configuration."""
        frame = ttk.Frame(notebook, padding="20")
        notebook.add(frame, text="Browser Engine")

        config = self.profile.app_config

        # 1. Headless Mode (Admin Lockable)
        headless_locked = self.admin_policy.force_headless is not None
        headless_state = tk.DISABLED if headless_locked else tk.NORMAL
        headless_label = self._lock_label("Run Headless (Invisible)", headless_locked)
        headless_val = self.admin_policy.force_headless if headless_locked else config.run_headless  # noqa: E501

        self._add_checkbox(frame, headless_label, "run_headless", headless_val, state=headless_state)  # noqa: E501
        self._add_note(frame, "Faster, but you cannot see the browser actions.")

        # 2. Preferred Browser (Admin Filterable)
        ttk.Label(frame, text="Preferred Browser:").pack(anchor=tk.W, pady=(15, 5))

        browser_var = tk.StringVar(value=config.preferred_browser)
        self._vars["preferred_browser"] = browser_var

        combo = ttk.Combobox(frame, textvariable=browser_var, state="readonly", width=30)  # noqa: E501
        allowed_browsers = self.registry.get_allowed_browsers()
        combo["values"] = tuple(allowed_browsers)

        if config.preferred_browser not in allowed_browsers and allowed_browsers:
            combo.set(allowed_browsers[0])

        combo.pack(anchor=tk.W)
        if self.admin_policy.allowed_browsers:
            self._add_note(frame, "Options restricted by System Administrator.")

        # 3. Humanization (Admin Lockable)
        humanize_locked = self.admin_policy.force_humanization is not None
        humanize_state = tk.DISABLED if humanize_locked else tk.NORMAL
        humanize_label = self._lock_label("Enable Human Behavior Simulation", humanize_locked)  # noqa: E501
        humanize_val = True if humanize_locked else config.enable_behavior_humanization

        self._add_checkbox(frame, humanize_label, "humanize", humanize_val, state=humanize_state)  # noqa: E501
        self._add_note(frame, "Adds random pauses and mouse movements to avoid detection.")  # noqa: E501

    def _build_search_tab(self, notebook: ttk.Notebook) -> None:
        """Tab 2: Job Search Preferences."""
        frame = ttk.Frame(notebook, padding="20")
        notebook.add(frame, text="Search Criteria")

        prefs = self.profile.search_preferences

        # Salary
        ttk.Label(frame, text="Minimum Expected Salary ($):").pack(anchor=tk.W, pady=(0, 5))  # noqa: E501
        current_salary = prefs.expected_salary if prefs.expected_salary else 0
        self._add_spinbox(frame, "expected_salary", current_salary, 0, 1_000_000, 5000)

        # Workplace Types — options read from ui_schema so adding a new
        # WorkplaceType to the domain model automatically appears here.
        ttk.Label(frame, text="Workplace Types:").pack(anchor=tk.W, pady=(15, 5))
        current_types = set(prefs.workplace_types or [])
        wp_field = self._schema_field("search_preferences.workplace_types")
        wp_options = wp_field.options if wp_field else ("in-office", "hybrid", "remote")
        for opt in wp_options:
            self._add_checkbox(
                frame,
                opt.replace("-", " ").title(),
                f"wp_{opt}",
                opt in current_types,
            )

        # Employment Types — driven by ui_schema; absent from editor before.
        ttk.Label(frame, text="Employment Types:").pack(anchor=tk.W, pady=(15, 5))
        current_et = set(prefs.employment_types or [])
        et_field = self._schema_field("search_preferences.employment_types")
        et_options = et_field.options if et_field else (
            "full-time", "part-time", "contract", "temporary", "internship"
        )
        for opt in et_options:
            self._add_checkbox(
                frame,
                opt.replace("-", " ").title(),
                f"et_{opt}",
                opt in current_et,
            )

    def _build_safety_tab(self, notebook: ttk.Notebook) -> None:
        """Tab 3: Rate Limiting & Safety.

        All fields in this tab are candidates for admin locking because they
        govern device compliance and internet conduct.
        """
        frame = ttk.Frame(notebook, padding="20")
        notebook.add(frame, text="Safety & Throttling")

        config = self.profile.app_config
        politeness = self.profile.politeness

        # 1. Daily Limit (Admin Lockable)
        limit_locked = self.admin_policy.max_applications_per_session is not None
        limit_state = tk.DISABLED if limit_locked else tk.NORMAL
        limit_label = self._lock_label("Max Applications per Day:", limit_locked)

        ttk.Label(frame, text=limit_label).pack(anchor=tk.W, pady=(0, 5))
        admin_cap = self.admin_policy.max_applications_per_session or 1000
        current_limit = min(config.daily_application_limit, admin_cap)
        self._add_spinbox(frame, "daily_limit", current_limit, 1, admin_cap, 10, state=limit_state)  # noqa: E501

        # 2. Action Delay (Admin Lockable — min floor)
        delay_locked = self.admin_policy.min_action_delay_seconds is not None
        delay_state = tk.DISABLED if delay_locked else tk.NORMAL
        delay_label = self._lock_label("Delay Between Actions (Seconds):", delay_locked)

        ttk.Label(frame, text=delay_label).pack(anchor=tk.W, pady=(15, 5))

        if delay_locked:
            delay_val = self.admin_policy.min_action_delay_seconds
        else:
            delay_val = politeness.default_delay

        self._add_spinbox(frame, "default_delay", delay_val, 1.0, 60.0, 0.5, state=delay_state)  # noqa: E501

        # 3. Robots.txt Compliance (Admin Lockable)
        robots_locked = self.admin_policy.force_respect_robots_txt is not None
        robots_state = tk.DISABLED if robots_locked else tk.NORMAL
        robots_label = self._lock_label("Respect Robots.txt (Recommended)", robots_locked)  # noqa: E501
        robots_val = True if robots_locked else politeness.respect_robots_txt

        self._add_checkbox(frame, robots_label, "robots_txt", robots_val, state=robots_state)  # noqa: E501

    def _build_documents_tab(self, notebook: ttk.Notebook) -> None:
        """Tab 4: Resume & Cover Letter Management."""
        frame = ttk.Frame(notebook, padding="20")
        notebook.add(frame, text="Documents")

        personal = self.profile.personal_info

        # Resume path
        ttk.Label(frame, text="Resume (PDF):").pack(anchor=tk.W, pady=(0, 5))
        resume_frame = ttk.Frame(frame)
        resume_frame.pack(fill=tk.X, pady=(0, 10))

        resume_var = tk.StringVar(
            value=str(personal.resume_path) if personal.resume_path else ""
        )
        self._vars["resume_path"] = resume_var
        ttk.Entry(resume_frame, textvariable=resume_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(
            resume_frame,
            text="Browse...",
            command=lambda: self._browse_file(resume_var, [("PDF Documents", "*.pdf")]),
        ).pack(side=tk.RIGHT, padx=(5, 0))

        # Cover letter path
        ttk.Label(frame, text="Cover Letter (PDF, optional):").pack(
            anchor=tk.W, pady=(10, 5)
        )
        cl_frame = ttk.Frame(frame)
        cl_frame.pack(fill=tk.X, pady=(0, 10))

        cover_letter = getattr(personal, "cover_letter", None)
        cl_var = tk.StringVar(
            value=str(cover_letter) if cover_letter else ""
        )
        self._vars["cover_letter"] = cl_var
        ttk.Entry(cl_frame, textvariable=cl_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(
            cl_frame,
            text="Browse...",
            command=lambda: self._browse_file(cl_var, [("PDF Documents", "*.pdf")]),
        ).pack(side=tk.RIGHT, padx=(5, 0))

        # Clear buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            btn_frame,
            text="Clear Resume",
            command=lambda: resume_var.set(""),
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(
            btn_frame,
            text="Clear Cover Letter",
            command=lambda: cl_var.set(""),
        ).pack(side=tk.LEFT)

        self._add_note(frame, "Your resume is required. Cover letters are sent when the form supports them.")  # noqa: E501

    # =====================================================================
    # UI HELPERS
    # =====================================================================

    def _schema_field(self, key: str) -> UIField | None:
        """Returns the UIField for *key*, or None if the schema is unavailable."""
        return next((f for f in self._ui_schema if f.key == key), None)

    @staticmethod
    def _lock_label(text: str, locked: bool) -> str:
        """Appends a lock icon to a label if the field is admin-locked."""
        return f"{text} \U0001F512" if locked else text

    def _add_checkbox(
        self, parent, text: str, key: str, initial_value: bool, state=tk.NORMAL
    ) -> None:
        var = tk.BooleanVar(value=initial_value)
        self._vars[key] = var
        chk = ttk.Checkbutton(parent, text=text, variable=var, state=state)
        chk.pack(anchor=tk.W, pady=2)

    def _add_spinbox(
        self, parent, key: str, initial_value, min_val, max_val, step, state=tk.NORMAL
    ) -> None:
        if isinstance(initial_value, float):
            var = tk.DoubleVar(value=initial_value)
        else:
            var = tk.IntVar(value=initial_value)
        self._vars[key] = var
        spin = ttk.Spinbox(
            parent, from_=min_val, to=max_val, increment=step,
            textvariable=var, width=10, state=state,
        )
        spin.pack(anchor=tk.W)

    def _add_note(self, parent, text: str) -> None:
        ttk.Label(
            parent, text=text,
            font=("Segoe UI", 8, "italic"), foreground="gray",
        ).pack(anchor=tk.W, padx=20, pady=(0, 10))

    def _browse_file(self, var: tk.StringVar, filetypes: list) -> None:
        """Opens a file dialog and sets the result into the given StringVar."""
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    # =====================================================================
    # SAVE LOGIC
    # =====================================================================

    def _save_changes(self) -> None:
        """Validates and persists changes to the profile.

        Admin-locked fields are skipped entirely during save. This prevents
        the user's base profile from being overwritten with the admin's
        enforced temporary value. When the policy file is removed, the user's
        original preference is restored automatically.
        """
        try:
            # -- Browser tab (skip admin-locked fields) --------------------
            if not self.admin_policy.is_field_locked("force_headless"):
                self.profile.app_config.run_headless = self._vars["run_headless"].get()

            self.profile.app_config.preferred_browser = self._vars["preferred_browser"].get()  # noqa: E501

            if not self.admin_policy.is_field_locked("force_humanization"):
                self.profile.app_config.enable_behavior_humanization = self._vars["humanize"].get()  # noqa: E501

            # -- Safety tab (skip admin-locked fields) ---------------------
            if not self.admin_policy.is_field_locked("max_applications_per_session"):
                self.profile.app_config.daily_application_limit = self._vars["daily_limit"].get()  # noqa: E501

            if not self.admin_policy.is_field_locked("min_action_delay_seconds"):
                self.profile.politeness.default_delay = self._vars["default_delay"].get()  # noqa: E501

            if not self.admin_policy.is_field_locked("force_respect_robots_txt"):
                self.profile.politeness.respect_robots_txt = self._vars["robots_txt"].get()  # noqa: E501

            # -- Search tab (no admin locks currently) ---------------------
            self.profile.search_preferences.expected_salary = self._vars["expected_salary"].get()  # noqa: E501

            # Workplace types — iterate the same options used to build checkboxes.
            wp_field = self._schema_field("search_preferences.workplace_types")
            wp_options = wp_field.options if wp_field else ("in-office", "hybrid", "remote")
            self.profile.search_preferences.workplace_types = [
                opt for opt in wp_options
                if self._vars.get(f"wp_{opt}") is not None
                and self._vars[f"wp_{opt}"].get()
            ]

            # Employment types — same pattern.
            et_field = self._schema_field("search_preferences.employment_types")
            et_options = et_field.options if et_field else (
                "full-time", "part-time", "contract", "temporary", "internship"
            )
            self.profile.search_preferences.employment_types = [
                opt for opt in et_options
                if self._vars.get(f"et_{opt}") is not None
                and self._vars[f"et_{opt}"].get()
            ]

            # -- Documents tab ---------------------------------------------
            resume_path = self._vars["resume_path"].get().strip()
            if resume_path:
                self.profile.personal_info.resume_path = Path(resume_path)
            else:
                self.profile.personal_info.resume_path = None

            cl_path = self._vars["cover_letter"].get().strip()
            if cl_path:
                self.profile.personal_info.cover_letter = Path(cl_path)
            else:
                self.profile.personal_info.cover_letter = None

            # -- Persist to disk -------------------------------------------
            self.repo.save_profile(self.profile)

            messagebox.showinfo("Saved", "Settings updated successfully.")
            self.on_save_callback()
            self.destroy()

        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save settings: {exc}")
