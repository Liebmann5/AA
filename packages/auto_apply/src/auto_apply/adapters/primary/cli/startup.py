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

Example:
    $ python -m auto_apply --cli
"""

import getpass
import logging
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
    """

    def __init__(self, profile_repo_factory: Callable[..., object]) -> None:
        self._repo_factory = profile_repo_factory
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

    def _select_profile_loop(self) -> UserProfile | None:
        """Loops until a valid profile is loaded or user quits.

        Returns:
            A loaded UserProfile, or None if the user chose to quit.
        """
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
        """Displays the session summary after execution completes.

        Args:
            controller: The SessionController with session stats.
        """

        try:
            stats = controller.get_stats()

            stats.get("success_rate", 0)

        except Exception as exc:
            logger.error("Could not retrieve session stats: %s", exc)

        try:
            again = input("\nRun another session? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if again == "y":
            self.run()