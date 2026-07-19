"""Provides a text-based configuration wizard.

This module prompts the user for session parameters and generates a config
dict compatible with the SessionController.

When a UserProfile is injected, prompts are pre-filled with the user's saved
preferences (desired titles, preferred locations) and labels are resolved from
the Pydantic model's JSON schema via build_ui_schema. All inputs fall back to
hardcoded defaults when no profile is available so the wizard runs cleanly on
first-run before any profile exists.
"""

from typing import TYPE_CHECKING, Any

from auto_apply.application.services.ui_schema import UIField, build_ui_schema
from auto_apply.domain.models.profile import UserProfile

if TYPE_CHECKING:
    from auto_apply.domain.models.profile import JobSearchPreferences


class CLIWizard:
    """Interactively gathers session configuration from the user.

    Args:
        profile: Optional pre-loaded profile. When provided, prompt defaults are
            populated from the user's saved search preferences.
    """

    def __init__(self, profile: UserProfile | None = None) -> None:
        self._profile = profile
        try:
            self._ui_schema: list[UIField] = build_ui_schema(UserProfile, "en")
        except Exception:
            self._ui_schema = []

    # ─────────────────────────────────────────────────────────────────────────
    # Public
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> dict[str, Any]:
        """Executes the questionnaire steps and returns a session config dict."""
        config: dict[str, Any] = {}

        # --- Step 1: Mode Selection ---

        mode_choice = input("Select Mode [1]: ").strip()

        if mode_choice == "2":
            config["mode"] = "direct_links"
            config["links"] = self._get_multiline_input(
                "Paste Links (Empty line to finish):"
            )
            if not config["links"]:
                return {}
        else:
            config["mode"] = "discovery"
            self._fill_discovery_params(config)

        # --- Step 2: Strategy ---

        strat_choice = input("Select Strategy [1]: ").strip()
        strat_map = {"1": "adaptive", "2": "stream", "3": "collect_first"}
        config["strategy"] = strat_map.get(strat_choice, "adaptive")

        return config

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fill_discovery_params(self, config: dict[str, Any]) -> None:
        """Prompts for job titles, location, and result cap."""
        prefs: "JobSearchPreferences | None" = (
            getattr(self._profile, "search_preferences", None)
            if self._profile else None
        )

        # Defaults — pulled from the saved profile when available.
        default_titles = (
            ", ".join(prefs.desired_job_titles)
            if prefs and prefs.desired_job_titles
            else "Software Engineer"
        )
        default_location = (
            prefs.preferred_locations[0]
            if prefs and prefs.preferred_locations
            else "Remote"
        )
        default_max = 100

        # Labels — resolved from the model schema; fall back to plain strings.
        titles_label = self._schema_label(
            "search_preferences.desired_job_titles", "Job Titles"
        )
        loc_label = self._schema_label(
            "search_preferences.preferred_locations", "Location"
        )

        config["keywords"] = (
            input(f"{titles_label} (comma-separated) [{default_titles}]: ").strip()
            or default_titles
        )
        config["location"] = (
            input(f"{loc_label} [{default_location}]: ").strip()
            or default_location
        )

        try:
            raw_max = input(f"Max Results [{default_max}]: ").strip()
            config["max_results"] = int(raw_max) if raw_max else default_max
        except ValueError:
            config["max_results"] = default_max

    def _schema_label(self, key: str, fallback: str) -> str:
        """Returns the i18n-resolved label for *key*, or *fallback* on miss."""
        field = next((f for f in self._ui_schema if f.key == key), None)
        return field.label if field else fallback

    def _get_multiline_input(self, prompt: str) -> list[str]:
        print(prompt)
        lines = []
        while True:
            line = input("> ").strip()
            if not line:
                break
            lines.append(line)
        return lines