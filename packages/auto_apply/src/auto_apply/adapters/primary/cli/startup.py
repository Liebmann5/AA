"""Command Line Interface startup sequence.

This module orchestrates the CLI workflow from profile selection through
session execution and results display:

    1. Profile Selection — load local, import external, or create new.
    2. Session Configuration — via CLIWizard interactive prompts.
    3. Session Execution — via SessionController + background orchestrator.
    4. Live Monitoring — via CLIDashboard polling loop.
    5. Results Display — session summary on completion.

The CLI is designed for terminal environments (SSH, library computers,
headless servers) where Tkinter may not be available.

A ``profile_override`` (name or path) may be passed at construction to skip
the interactive profile selection menu entirely. This is wired from the
``--profile`` CLI flag in ``main.py``.

Example:
    $ python -m auto_apply --cli
    $ python -m auto_apply --cli --profile nick_engineer
    $ python -m auto_apply --cli --profile /path/to/profile.json
"""

import getpass
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from auto_apply.application.services.session_controller import SessionController
import sys
from pathlib import Path
from collections.abc import Callable

from auto_apply.adapters.primary.cli.dashboard import CLIDashboard
from auto_apply.adapters.primary.cli.wizard import CLIWizard
from auto_apply.infrastructure.composition_root import build_session_controller
from auto_apply.domain.models.profile import UserProfile

logger = logging.getLogger(__name__)


class CLIStartup:
    """Orchestrates the terminal‑based user workflow.

    Handles the full CLI lifecycle: profile selection, session configuration,
    agent execution with live monitoring, and results display.

    This class never touches the orchestrator or database directly — it
    works exclusively through SessionController.

    Args:
        profile_repo_factory: Callable that returns a ProfileRepository.
        profile_override: Optional profile name or absolute path. When
            provided, the interactive profile selection menu is skipped
            and this profile is loaded directly.
    """

    def __init__(
        self,
        profile_repo_factory: Callable[..., object],
        profile_override: str | None = None,
    ) -> None:
        self._repo_factory = profile_repo_factory
        self._profile_override = profile_override
        self.repo = profile_repo_factory()

    def run(self) -> None:
        """Runs the full CLI lifecycle: profile → config → execute → results."""
        sys.stdout.flush()

        # Prompt for password safely (keystrokes are hidden)
        try:
            password = getpass.getpass("Enter Master Password (or press Enter to run unencrypted): ").strip()  # noqa: E501
        except (EOFError, KeyboardInterrupt):
            print("\nNo input available — exiting.")  # noqa: T201
            sys.exit(0)

        self.repo = self._repo_factory(master_password=password if password else None)

        # 1. Profile Selection
        if self._profile_override:
            profile = self._load_profile_override()
        else:
            profile = self._select_profile_loop()

        if not profile:
            sys.exit(0)

        # 2. Session Configuration
        wizard = CLIWizard()
        session_config = wizard.run()

        if not session_config:
            sys.exit(0)

        # 3. Initialize Session — use the composition‑root factory
        controller = build_session_controller(profile)

        task_count = controller.initialize_session(session_config)

        if task_count == 0:
            sys.exit(0)

        # 4. Execute
        controller.start()

        try:
            dashboard = CLIDashboard(controller)
            dashboard.run_monitor_loop()
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()

        # 5. Results
        self._print_results(controller)

    # =========================================================================
    # PROFILE SELECTION
    # =========================================================================

    def _load_profile_override(self) -> UserProfile | None:
        """Loads the profile specified by ``--profile`` on the command line.

        Tries two strategies in order:
            1. Treat the value as a profile name (look up in storage_dir).
            2. Treat the value as an absolute path to a ``.json`` file.

        Returns:
            A loaded UserProfile, or None if neither strategy succeeded.
        """
        override = self._profile_override
        logger.info("Loading profile override | raw=%s", override)

        # ── Strategy 1: profile name ──────────────────────────────────────
        profile = self.repo.load_profile(override)
        if profile is not None:
            logger.info("Loaded profile by name | name=%s", override)
            return profile

        # ── Strategy 2: absolute or relative path ─────────────────────────
        candidate = Path(override)
        if candidate.suffix != ".json":
            candidate = candidate.with_suffix(".json")

        if candidate.exists():
            try:
                saved_path = self.repo.import_profile(candidate)
                profile_name = saved_path.stem
                profile = self.repo.load_profile(profile_name)
                if profile is not None:
                    logger.info("Loaded profile from path | path=%s", candidate)
                    return profile
            except Exception as exc:
                logger.error("Profile override load from path failed | path=%s error=%s", candidate, exc)

        logger.error("Profile override not found | raw=%s", override)
        return None

    def _select_profile_loop(self) -> UserProfile | None:
        """Loops until a valid profile is loaded or user quits.

        When no user profiles exist, launches the first‑run profile
        creation wizard before falling back to the selection menu.

        Returns:
            A loaded UserProfile, or None if the user chose to quit.
        """
        # ── First‑run: launch the profile creation wizard ──────────────────
        profiles = self.repo.list_profiles()
        user_profiles = [p for p in profiles if p != "default_profile"]

        if not user_profiles:
            print("\n  No user profiles found.")  # noqa: T201
            try:
                choice = input("  Create one now? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  No input available — exiting.")  # noqa: T201
                sys.exit(0)

            if choice in ("", "y", "yes"):
                from auto_apply.adapters.primary.cli.profile_wizard import (  # noqa: PLC0415
                    run_profile_wizard,
                )
                from auto_apply.domain.config import PROFILES_DIR  # noqa: PLC0415

                new_path = run_profile_wizard(PROFILES_DIR)
                if new_path is not None:
                    # Load the newly created profile immediately
                    profile_name = new_path.stem
                    profile = self.repo.load_profile(profile_name)
                    if profile is not None:
                        return profile

                # Wizard was cancelled — fall through to the regular menu
                print("  Profile creation cancelled.")  # noqa: T201

        return self._select_profile_menu()

    def _select_profile_menu(self) -> UserProfile | None:
        """Renders the profile selection menu and handles user input.

        Returns:
            A loaded UserProfile, or None if the user chose to quit.
        """
        while True:
            profiles = self.repo.list_profiles()
            user_profiles = [p for p in profiles if p != "default_profile"]

            if not user_profiles:

                try:
                    self._display_select_menu()
                    choice = input("\nSelect option: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nNo input available — exiting.")  # noqa: T201
                    sys.exit(0)

                if choice == "q":
                    return None
                if choice == "1":
                    profile = self._create_new_profile()
                    if profile:
                        return profile
                    continue
                if choice == "2":
                    profile = self._load_external_profile()
                    if profile:
                        return profile
                    continue
                continue

            print("\n--- Profile Selection ---")  # noqa: T201
            for idx, name in enumerate(user_profiles, 1):
                print(f"  [{idx}] {name}")  # noqa: T201
            print(f"  [{len(user_profiles) + 1}] Load profile from file")  # noqa: T201
            print("  [q]  Quit")  # noqa: T201

            try:
                choice = input("\nSelect option: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nNo input available — exiting.")  # noqa: T201
                sys.exit(0)

            if choice == "q":
                return None

            if choice == str(len(user_profiles) + 1):
                profile = self._load_external_profile()
                if profile:
                    return profile
                continue

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(user_profiles):
                    profile_name = user_profiles[idx]
                    profile = self.repo.load_profile(profile_name)
                    if profile:
                        return profile
                else:
                    pass
            except ValueError:
                pass

    def _load_external_profile(self) -> UserProfile | None:
        """Prompts the user for a file path and imports the profile.

        ProfileRepository.import_profile() validates the JSON, copies it
        into local storage, and returns the destination Path. We then
        load the validated profile from that path.

        Returns:
            The loaded UserProfile, or None on failure.
        """
        try:
            path_str = input("  Enter full path to profile JSON: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not path_str:
            return None

        source_path = Path(path_str)
        if not source_path.exists():
            return None

        try:
            # import_profile validates and copies to local storage,
            # returning the destination Path (not a UserProfile).
            saved_path = self.repo.import_profile(source_path)
            # Now load the profile from the saved location.
            profile_name = saved_path.stem
            profile = self.repo.load_profile(profile_name)
            if profile:
                return profile
            return None
        except FileNotFoundError:
            return None
        except ValueError:
            return None
        except Exception as exc:
            logger.error("External profile import failed: %s", exc)
            return None

    def _create_new_profile(self) -> UserProfile | None:
        """Guides the user through creating a minimal new profile.

        Returns:
            The created UserProfile, or None if the user cancels.
        """
        try:
            name = input("  Profile name (e.g., 'John-Dev'): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not name:
            return None

        try:
            resume_path = input("  Path to your resume (PDF/DOCX): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        try:
            default = self.repo.load_profile("default_profile")
            if not default:
                return None

            default.profile_name = name

            if resume_path:
                resume = Path(resume_path)
                if not resume.exists():
                    pass
                if hasattr(default, "personal_info") and hasattr(default.personal_info, "resume_path"):  # noqa: E501
                    default.personal_info.resume_path = resume

            self.repo.save_profile(default)
            self.repo.storage_dir / f"{name}.json"
            return default

        except Exception as exc:
            logger.error("Profile creation failed: %s", exc)
            return None

    def _display_select_menu(self) -> None:
        """Print the profiles Selection Menu to the console"""
        print("\n--- Profile Selection ---")
        print("  1. Use existing profile")
        print("  2. Create new profile")
        print("  3. Exit")

    # =========================================================================
    # RESULTS DISPLAY
    # =========================================================================

    def _print_results(self, controller: "SessionController") -> None:
        """Displays a full session summary after execution completes."""
        print("\n" + "\u2550" * 60)  # noqa: T201
        print("  SESSION COMPLETE")  # noqa: T201
        print("\u2550" * 60)  # noqa: T201

        try:
            stats = controller.get_stats()

            jobs_found      = stats.get("jobs_found", 0)
            jobs_vetted     = stats.get("jobs_vetted", 0)
            jobs_passed     = stats.get("jobs_passed_vetting", 0)
            apps_tried      = stats.get("applications_attempted", 0)
            apps_submitted  = stats.get("applications_submitted", 0)
            apps_failed     = stats.get("applications_failed", 0)
            apps_blocked    = stats.get("submissions_blocked_by_gate", 0)
            gate_remedy     = stats.get("gate_block_remedy", "")
            duration_s      = stats.get("session_duration_seconds", 0)
            submitted_urls  = stats.get("submitted_job_urls", [])
            submitted_companies = stats.get("submitted_companies", {})

            minutes = int(duration_s // 60)
            seconds = int(duration_s % 60)

            print(f"\n  \U0001f4cb  Jobs discovered:          {jobs_found}")  # noqa: T201
            print(f"  \U0001f50d  Jobs vetted:              {jobs_vetted}")  # noqa: T201
            print(f"  \u2705  Passed vetting:           {jobs_passed}")  # noqa: T201
            print(f"  \U0001f4e4  Applications attempted:   {apps_tried}")  # noqa: T201
            print(f"  \U0001f3af  Applications submitted:   {apps_submitted}")  # noqa: T201
            if apps_failed > 0:
                print(f"  \u274c  Applications failed:      {apps_failed}")  # noqa: T201
            if apps_blocked > 0:
                # Blocked is not failed: the gate held and is waiting for a
                # human. Printed with the remedy so a correct run cannot be
                # mistaken for a broken one.
                print(f"  \u26d4  Blocked (awaiting review): {apps_blocked}")  # noqa: T201
            print(f"\n  \u23f1   Session duration:         {minutes}m {seconds}s")  # noqa: T201

            if gate_remedy:
                print(f"\n  {gate_remedy}")  # noqa: T201

            if submitted_urls:
                print(f"\n  Submitted applications:")  # noqa: T201
                for url in submitted_urls[:10]:  # cap at 10 for readability
                    company = submitted_companies.get(url, "")
                    label = f" ({company})" if company else ""
                    print(f"    \u2192 {url[:70]}{label}")  # noqa: T201
                if len(submitted_urls) > 10:
                    print(f"    ... and {len(submitted_urls) - 10} more (see session report)")  # noqa: T201

            # Session report file location
            report_path = stats.get("report_path")
            if report_path:
                print(f"\n  \U0001f4c1  Full report: {report_path}")  # noqa: T201

        except Exception as exc:
            logger.error("Could not retrieve session stats: %s", exc)
            print("  (Session stats unavailable — check logs for details)")  # noqa: T201

        print("\n" + "\u2550" * 60)  # noqa: T201

        try:
            again = input("\nRun another session? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if again == "y":
            self.run()