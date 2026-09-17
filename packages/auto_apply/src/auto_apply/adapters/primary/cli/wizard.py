"""Provides a text-based session configuration wizard for the CLI.

This module prompts the user for session parameters and returns a typed
:class:`SessionRequest` — the same object
:meth:`SessionController.initialize_session` accepts on its preferred (UIPort)
path. The untyped dict the wizard used to emit is gone, and with it the
translation shim's job on the CLI path.

When a UserProfile is injected, prompts are pre-filled with the user's saved
preferences (desired titles, preferred locations) and labels are resolved from
the Pydantic model's JSON schema via build_ui_schema. All inputs fall back to
hardcoded defaults when no profile is available so the wizard runs cleanly on
first-run before any profile exists.

Exit axis and engine selection (stage U3, turn 2):
    After the entry choice the wizard asks how far AutoApply should go. The
    options shown depend on the entry point — the ruling recorded here:

      * SEARCH (discovery): collect links only / collect and check / collect,
        check, and apply (default). All three are meaningful because the
        pipeline is about to discover the jobs itself.
      * DIRECT_URLS (pasted links): apply now / check first then apply.
        "Collect" options are impossible — the user supplied the links — so
        they are not shown. Showing them would ask a nonsense question.

    The collapse-into-named-outcomes alternative (one menu of "find me links",
    "find and check", "find and apply", "apply to these", "check these") was
    rejected: it is kinder on screen but destroys the entry × exit
    orthogonality the type system just gained, and forces the GUI (turn 3)
    to render two vocabularies — the exact divergence the port arc exists to
    prevent.

    Three of the eight SessionExecutionMode members appear in these menus
    for search (DISCOVER_ONLY, DISCOVER_AND_VET, FULL_PIPELINE) and two for
    pasted links (APPLY_ONLY, VET_AND_APPLY). VET_ONLY's entry point is not
    offered by this wizard; HUMAN_ASSIST and RESEARCH_AUDIT are not
    user-facing concepts. Do not "complete" these menus without deciding
    what the remaining modes should mean to a user.

    The engine question (which job sites to search) is asked on the search
    path only — pasted links do not search engines, so asking would be
    meaningless there. Unknown names are dropped with a printed note, never
    silently; an empty or all-unknown answer falls back to the plan default
    with the note shown.

Shared labels (stage U3, turn 3):
    The outcome option sets and the provider vocabulary come from
    domain/models/ui_contract.py — the ONE source both this wizard and the
    GUI wizard read. A label hardcoded here would drift from the GUI's
    rendering of the same choice; the parity pin asserts both adapters
    import the same objects.

Removed at stage U3: the "strategy" prompt (adaptive / stream / collect_first).
Nothing in the codebase ever consumed it — session_controller's shim names it
a dead key and schedules its removal here, and runtime_defaults.yaml's
discovery_strategy is a different concept (live_browser vs static_fetch), not
these three values. A question whose answer is never read costs a user time
and teaches them the tool is unreliable, so it is gone; the four tests that
asserted on it are gone with it.
"""

from typing import TYPE_CHECKING

# The EntryPoint→ExecutionMode mapping is read from the controller's private
# table rather than re-invented here: it is the codebase's single answer to
# "what does legacy 'direct' mean" (APPLY_ONLY, per the label-mapping fix's
# documented history). A second table in this file is exactly the drift that
# table exists to prevent. It is expected to move to
# domain/models/ui_contract.py in a later stage; only this import changes then.
from auto_apply.application.services.session_controller import (
    _LEGACY_ENTRY_TO_EXECUTION_MODE,
)
from auto_apply.application.services.ui_schema import UIField, build_ui_schema
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.session_plan import SessionExecutionMode
from auto_apply.domain.models.ui_contract import (
    EntryPoint,
    SessionRequest,
    outcome_options_for_entry,
    provider_vocabulary,
)

if TYPE_CHECKING:
    from auto_apply.domain.models.profile import JobSearchPreferences


class CLIWizard:
    """Interactively gathers a typed session request from the user.

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

    def run(self) -> SessionRequest | None:
        """Executes the questionnaire and returns a typed SessionRequest.

        Returns None only when the user chose the paste-links mode and pasted
        nothing — the sole "nothing to do" outcome. Accepting every default
        still returns a complete request.
        """
        # --- Step 1: Mode Selection ---
        mode_choice = input("Select Mode [1]: ").strip()

        if mode_choice == "2":
            execution_mode = self._ask_outcome_for_urls()
            urls = tuple(
                self._get_multiline_input("Paste Links (Empty line to finish):")
            )
            if not urls:
                return None
            return SessionRequest(
                entry=EntryPoint.DIRECT_URLS,
                execution_mode=execution_mode,
                urls=urls,
            )

        execution_mode = self._ask_outcome_for_search()
        providers = self._ask_providers()
        keywords, location, max_results = self._fill_discovery_params()
        return SessionRequest(
            entry=EntryPoint.SEARCH,
            execution_mode=execution_mode,
            keywords=keywords,
            location=location,
            max_results=max_results,
            providers=providers,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Exit axis (per entry point — see the module docstring for the ruling)
    # ─────────────────────────────────────────────────────────────────────────

    def _ask_outcome_for_search(self) -> SessionExecutionMode:
        """Offers the exit axis for a discovery run, in the user's language.

        Options come from ui_contract.outcome_options_for_entry — the same
        source the GUI renders — never a hardcoded list here.
        """
        options = outcome_options_for_entry(EntryPoint.SEARCH)
        print("  How far should AutoApply go?")  # noqa: T201
        for i, (label, _mode) in enumerate(options, start=1):
            print(f"    [{i}] {label}")  # noqa: T201
        choice = input("  Select [1]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][1]
        return _LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.SEARCH]

    def _ask_outcome_for_urls(self) -> SessionExecutionMode:
        """Offers the exit axis for pasted links.

        "Collect" options are impossible here — the user supplied the links —
        so they are not shown. The default preserves the legacy paste-links
        behavior (apply immediately).
        """
        options = outcome_options_for_entry(EntryPoint.DIRECT_URLS)
        print("  What should AutoApply do with those links?")  # noqa: T201
        for i, (label, _mode) in enumerate(options, start=1):
            print(f"    [{i}] {label}")  # noqa: T201
        choice = input("  Select [1]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][1]
        return _LEGACY_ENTRY_TO_EXECUTION_MODE[EntryPoint.DIRECT_URLS]

    # ─────────────────────────────────────────────────────────────────────────
    # Engine selection (search path only)
    # ─────────────────────────────────────────────────────────────────────────

    def _ask_providers(self) -> tuple[str, ...]:
        """Asks which job sites to search. Empty answer means the plan default.

        The vocabulary comes from ui_contract.provider_vocabulary() — the same
        source the GUI reads — never a hardcoded list here. Unknown names are
        dropped with a printed note, never silently.
        """
        vocabulary = provider_vocabulary()
        print("  Which job sites should AutoApply use? (comma-separated)")  # noqa: T201
        print(f"    Available: {', '.join(vocabulary)}    [all, default]")  # noqa: T201
        raw = input("  Select [all]: ").strip().lower()
        if not raw:
            return ()
        chosen: list[str] = []
        dropped: list[str] = []
        for part in raw.split(","):
            name = part.strip()
            if not name:
                continue
            if name in vocabulary:
                chosen.append(name)
            else:
                dropped.append(name)
        for name in dropped:
            print(f"    Not a known job site, skipped: {name}")  # noqa: T201
        return tuple(chosen)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fill_discovery_params(self) -> tuple[tuple[str, ...], str, int]:
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

        titles_raw = (
            input(f"{titles_label} (comma-separated) [{default_titles}]: ").strip()
            or default_titles
        )
        location = (
            input(f"{loc_label} [{default_location}]: ").strip()
            or default_location
        )

        try:
            raw_max = input(f"Max Results [{default_max}]: ").strip()
            max_results = int(raw_max) if raw_max else default_max
        except ValueError:
            max_results = default_max

        # The prompt collects a comma-separated string; the request carries a tuple.
        keywords = tuple(t.strip() for t in titles_raw.split(",") if t.strip())
        return keywords, location, max_results

    def _schema_label(self, key: str, fallback: str) -> str:
        """Returns the i18n-resolved label for *key*, or *fallback* on miss."""
        field = next((f for f in self._ui_schema if f.key == key), None)
        return field.label if field else fallback

    def _get_multiline_input(self, prompt: str) -> list[str]:
        print(prompt)  # noqa: T201
        lines = []
        while True:
            line = input("> ").strip()
            if not line:
                break
            lines.append(line)
        return lines
