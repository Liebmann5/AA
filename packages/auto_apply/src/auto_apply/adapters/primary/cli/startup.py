"""Command Line Interface startup sequence.

This module orchestrates the CLI workflow from profile selection through
session execution and results display:

    1. Profile Selection — load local, import external, or create new.
    2. Session Configuration — via CLIWizard interactive prompts.
    3. Session Execution — via SessionController + background orchestrator.
    4. Live Monitoring — via CLIDashboard polling loop.
    5. Results Display — session summary on completion, plus opt-in
       custody exports (results CSV, profile JSON) and session history.

The CLI is designed for terminal environments (SSH, library computers,
headless servers) where Tkinter may not be available.

A ``profile_override`` (name or path) may be passed at construction to skip
the interactive profile selection menu entirely. This is wired from the
``--profile`` CLI flag in ``main.py``.

Profile failure handling:
    When a profile fails to load, the user is told which profile, which
    field, and what pydantic objected to — that information previously went
    only to the log file. The menu then offers a repair path ( the profile
    wizard re-run pre-filled from the broken file), an explicit confirmed
    delete, or a return to selection. Nothing is repaired silently and
    nothing is deleted automatically.

    Honest limitation: ProfileRepository surfaces validation errors only to
    the log, so this module re-validates through the SAME UserProfile model
    (mirroring the repository's vault-then-JSON read order) to obtain the
    field-level errors for display. The proper fix — a
    ``load_profile_errors()`` method on ProfileRepository — belongs to a
    file outside this change.

Profile persistence:
    Every wizard call site passes ``self.repo.save_profile`` as the save
    callable, so persistence goes through the repository — which owns atomic
    writes and vault encryption. A wizard writing bytes itself would, under
    an active master password, overwrite an encrypted profile with plaintext
    and tell nobody. The callable is typed against the port's declared
    return (``object``); the wizard narrows the result itself rather than
    assuming the implementation's ``Path``.

Results display (C2):
    The end-of-session view reads from the controller's typed summary(),
    which includes the discovered-job list read from job_history — so a
    DISCOVER_ONLY run's payoff actually prints. Exports are opt-in prompts:
    nothing is written to disk unless the user asks (the ruling for collect
    runs — the results already survive in job_history, so the export is a
    custody act, never a survival mechanism).

Autonomy (stage E1):
    The autonomy state is printed on the home screen right after profile
    load, and the control (``_ask_autonomy``) runs after the wizard returns
    and BEFORE ``build_session_controller`` — deliberately in that order,
    because building the controller launches a browser (the cascade in
    build_orchestrator), which must not happen before the user has chosen
    what to do. Enabling requires two differently-worded confirmations:
    one describes the behaviour change, the other names the consequence
    (real name and email, irreversible, recorded as automated). The write
    goes through the shared application-layer helper
    (application/services/autonomy.apply_autonomy), the same implementation
    SessionController.set_autonomy delegates to.

Example:
    $ python -m auto_apply --cli
    $ python -m auto_apply --cli --profile nick_engineer
    $ python -m auto_apply --cli --profile /path/to/profile.json
"""

import getpass
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from auto_apply.application.services.session_controller import SessionController
import sys
from pathlib import Path
from collections.abc import Callable

from pydantic import ValidationError

from auto_apply.adapters.primary.cli.dashboard import CLIDashboard
from auto_apply.adapters.primary.cli.wizard import CLIWizard
from auto_apply.application.services.autonomy import (
    apply_autonomy,
    autonomy_enabled_for_profile,
)
from auto_apply.infrastructure.composition_root import build_session_controller
from auto_apply.domain.models.profile import UserProfile, make_portable_path
from auto_apply.domain.ports.profile_repository_port import ProfileRepositoryPort

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
        profile_repo_factory: Callable[..., ProfileRepositoryPort],
        profile_override: str | None = None,
    ) -> None:
        self._repo_factory = profile_repo_factory
        self._profile_override = profile_override
        self.repo: ProfileRepositoryPort = profile_repo_factory()

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

        # Autonomy state on the home screen — shown before any session work
        # starts (stage E1). The control itself runs after the wizard, below.
        if autonomy_enabled_for_profile(profile):
            print("  Autonomy: ON — AutoApply will submit applications without asking.")  # noqa: T201
        else:
            print("  Autonomy: OFF — AutoApply will ask before each submission.")  # noqa: T201

        # 2. Session Configuration
        wizard = CLIWizard()
        session_config = wizard.run()

        # The wizard returns a typed SessionRequest (stage U3); None means the
        # user pasted no links and there is nothing to do.
        if session_config is None:
            sys.exit(0)

        # Autonomy control — offered only when the chosen session applies to
        # jobs, applied before the controller (and its browser) is built.
        if session_config.execution_mode.includes_application:
            self._ask_autonomy(profile)

        # 3. Initialize Session — use the composition‑root factory
        controller = build_session_controller(profile, profile_repo=self.repo)

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
    # AUTONOMY CONTROL (stage E1)
    # =========================================================================

    def _ask_autonomy(self, profile: UserProfile) -> None:
        """Offers the autonomy choice and applies it before the controller is built.

        Called only when the chosen session applies to jobs. The current state
        is shown and is the default (Enter keeps it). Enabling requires two
        differently-worded confirmations: WARNING 1 describes the behaviour
        change (no review prompt, ever), WARNING 2 names the consequence the
        first did not (real name and email, irreversible, recorded as
        automated). Two identically-worded confirmations would be one
        confirmation with an extra click, so the texts differ on purpose.
        Disabling needs one confirmation — turning autonomy off is always safe.

        The write goes through the shared application-layer helper, the same
        implementation SessionController.set_autonomy delegates to, and it
        lands BEFORE build_session_controller — so the imminent run reflects
        the choice, while the policy for the run is then frozen.
        """
        currently_on = autonomy_enabled_for_profile(profile)

        if currently_on:
            print("\n  AutoApply will submit applications WITHOUT asking (autonomy ON).")  # noqa: T201
            try:
                answer = input(
                    "  Turn autonomy OFF and review each submission first? [y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()  # noqa: T201
                return
            if answer in ("y", "yes"):
                apply_autonomy(profile, self.repo, enabled=False)
                print("  Autonomy OFF — AutoApply will ask before each submission.")  # noqa: T201
            return

        print("\n  AutoApply will ASK before each submission (autonomy OFF).")  # noqa: T201
        try:
            answer = input(
                "  Turn autonomy ON and submit without asking? [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return
        if answer not in ("y", "yes"):
            return

        print("\n  WARNING 1 of 2 — the behaviour change:")  # noqa: T201
        print("    AutoApply will submit each application IMMEDIATELY when the form")  # noqa: T201
        print("    is complete. You will NOT be asked to review or confirm any submission.")  # noqa: T201
        try:
            ack1 = input("    Type YES to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Autonomy stays OFF — nothing was changed.")  # noqa: T201
            return
        if ack1 != "YES":
            print("  Autonomy stays OFF — nothing was changed.")  # noqa: T201
            return

        print("\n  WARNING 2 of 2 — the consequence:")  # noqa: T201
        print("    Applications go out under your real name and email, cannot be")  # noqa: T201
        print("    recalled once sent, and this session is recorded as fully automated.")  # noqa: T201
        try:
            ack2 = input("    Type YES again to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Autonomy stays OFF — nothing was changed.")  # noqa: T201
            return
        if ack2 != "YES":
            print("  Autonomy stays OFF — nothing was changed.")  # noqa: T201
            return

        if apply_autonomy(profile, self.repo, enabled=True, acknowledgements=(ack1, ack2)):
            print("  Autonomy ON — AutoApply will submit without asking during this run.")  # noqa: T201
        else:
            print("  Autonomy was NOT enabled (the write was refused).")  # noqa: T201

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

        # The only caller guards on ``if self._profile_override``, but that
        # guard lives in run() and cannot be seen from here. Re-stating it
        # makes the precondition local and true independently of the caller.
        if not override:
            return None

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
        print(f"\n  ✗ Could not load profile '{override}'.")  # noqa: T201
        print(f"    {self._describe_profile_load_failure(override)}")  # noqa: T201
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

                # Persistence goes through the repository, so a first-run
                # profile created under a master password is encrypted from
                # the start rather than written as plaintext.
                new_path = run_profile_wizard(
                    self.repo.storage_dir,
                    save=self.repo.save_profile,
                )
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
                    # Load failed — say why and offer a way out that does not
                    # require leaving AA or hand-editing JSON.
                    repaired = self._offer_profile_repair(profile_name)
                    if repaired is not None:
                        return repaired
                else:
                    print(f"  There is no option {choice} on the list.")  # noqa: T201
            except ValueError:
                print(f"  '{choice}' is not a number. Enter a number from the list, or q to quit.")  # noqa: T201

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
            print(f"\n  ✗ No file found at: {source_path}")  # noqa: T201
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
            print(f"\n  ✗ The file was copied but still does not load.")  # noqa: T201
            print(f"    {self._describe_profile_load_failure(profile_name)}")  # noqa: T201
            return None
        except FileNotFoundError:
            print(f"\n  ✗ No file found at: {source_path}")  # noqa: T201
            return None
        except ValueError as exc:
            print(f"\n  ✗ That file is not a valid profile.")  # noqa: T201
            print(f"    {exc}")  # noqa: T201
            return None
        except Exception as exc:
            logger.error("External profile import failed: %s", exc)
            print(f"\n  ✗ The profile could not be imported: {exc}")  # noqa: T201
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
                    # Warn, do not block: the file may legitimately be copied
                    # later — the same contract as the wizard's resume prompt.
                    print(f"\n  ⚠ No file found at: {resume}")  # noqa: T201
                    print("    The profile will still be created. Copy the file to")  # noqa: T201
                    print("    that path later, or update it in Settings > Documents.")  # noqa: T201
                if hasattr(default, "personal_info") and hasattr(default.personal_info, "resume_path"):  # noqa: E501
                    # Store a portable string, never a raw Path: relative to
                    # PROFILES_DIR when possible so the profile survives
                    # drive-letter changes on a USB stick.
                    default.personal_info.resume_path = make_portable_path(resume)
            else:
                print("  No resume set — you can add one later in Settings > Documents.")  # noqa: T201

            # save_profile returns the path it actually wrote (storage_dir /
            # <profile_name>.json). Reporting it is what the dead statement
            # that previously computed this path and discarded it was meant
            # to do.
            saved_path = self.repo.save_profile(default)
            print(f"  ✓ Profile saved: {saved_path}")  # noqa: T201
            return default

        except Exception as exc:
            logger.error("Profile creation failed: %s", exc)
            print(f"\n  ✗ Profile could not be created: {exc}")  # noqa: T201
            return None

    def _display_select_menu(self) -> None:
        """Print the profiles Selection Menu to the console"""
        print("\n--- Profile Selection ---")  # noqa: T201
        print("  1. Create new profile")  # noqa: T201
        print("  2. Load profile from file")  # noqa: T201
        print("  q. Quit")  # noqa: T201

    # =========================================================================
    # PROFILE FAILURE HANDLING (detect → inform → ask; never silent)
    # =========================================================================

    def _read_profile_raw(self, name_or_path: str) -> tuple[Path | None, dict | None, str | None]:
        """Reads a profile file the same way ProfileRepository does.

        Mirrors ProfileRepository._deserialise: vault decryption first (when
        a master password is active), then plain JSON. The repository exposes
        errors only to the log; this duplicate read exists so the user can
        see them on screen.

        Returns:
            (path, data, error_text). ``data`` is the parsed dict on success;
            ``error_text`` explains the read failure when data is None.
        """
        candidate = Path(name_or_path)
        if candidate.is_absolute() and candidate.suffix == ".json":
            path = candidate
        elif candidate.suffix != ".json":
            path = self.repo.storage_dir / f"{name_or_path}.json"
        else:
            path = self.repo.storage_dir / candidate

        if not path.exists():
            return None, None, f"no file found at {path}"

        try:
            raw = path.read_bytes()
        except OSError as exc:
            return path, None, f"the file could not be read: {exc}"

        vault = getattr(self.repo, "vault", None)
        if vault is not None:
            try:
                return path, vault.decrypt_dict(raw), None
            except Exception:
                pass  # fall through to plain JSON, same as the repository

        try:
            return path, json.loads(raw.decode("utf-8")), None
        except Exception:
            return path, None, (
                "the file could not be read — it may be encrypted with a "
                "different password, or it is corrupted (not valid JSON)"
            )

    def _describe_profile_load_failure(self, name_or_path: str) -> str:
        """Returns a human-readable explanation of why a profile failed to load.

        Re-validates through the SAME UserProfile model the repository used,
        so the field names and messages match exactly what was logged.
        """
        _path, data, read_error = self._read_profile_raw(name_or_path)
        if data is None:
            return read_error or "the file could not be read"
        try:
            UserProfile(**data)
        except ValidationError as exc:
            lines = []
            for err in exc.errors():
                loc = " → ".join(str(part) for part in err["loc"]) or "(top of file)"
                lines.append(f"    - {loc}: {err['msg']}")
            return "the file does not match the profile format:\n" + "\n".join(lines)
        return (
            "the file could not be loaded for an unknown reason "
            "(details were written to the application log)"
        )

    def _offer_profile_repair(self, profile_name: str) -> UserProfile | None:
        """Informs the user why a profile failed and offers ways forward.

        Options: repair via the pre-filled wizard, an explicitly confirmed
        delete, or a return to the selection menu. Nothing is automatic.
        """
        print(f"\n  ✗ Profile '{profile_name}' could not be loaded.")  # noqa: T201
        reason = self._describe_profile_load_failure(profile_name)
        print(f"  Reason: {reason}")  # noqa: T201
        print()  # noqa: T201
        print("  What would you like to do?")  # noqa: T201
        print("    [1] Repair it — re-run the setup wizard with your existing")  # noqa: T201
        print("        answers pre-filled (you only fix the bad field)")  # noqa: T201
        print("    [2] Delete it permanently (you will be asked to confirm)")  # noqa: T201
        print("    [3] Go back to profile selection")  # noqa: T201

        try:
            choice = input("\n  Select [3]: ").strip() or "3"
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return None

        if choice == "1":
            return self._repair_profile_with_wizard(profile_name)
        if choice == "2":
            self._delete_profile_confirmed(profile_name)
            return None
        return None

    def _repair_profile_with_wizard(self, profile_name: str) -> UserProfile | None:
        """Re-runs the profile wizard pre-filled from the broken file.

        The user fixes the one bad field and the wizard re-validates and
        re-saves to the SAME filename — through the repository, so an
        encrypted profile is re-encrypted, never downgraded to plaintext.
        Returns the repaired profile, or None if the user cancelled or
        repair was not possible.
        """
        path, data, read_error = self._read_profile_raw(profile_name)
        if data is None:
            print(f"\n  The file cannot be pre-filled: {read_error}")  # noqa: T201
            print("  Delete it from the previous menu and create a fresh profile,")  # noqa: T201
            print("  or fix the JSON by hand and try again.")  # noqa: T201
            return None

        from auto_apply.adapters.primary.cli.profile_wizard import (  # noqa: PLC0415
            run_profile_wizard,
        )

        new_path = run_profile_wizard(
            self.repo.storage_dir,
            prefill=data,
            target_path=path,
            save=self.repo.save_profile,
        )
        if new_path is None:
            return None

        profile = self.repo.load_profile(new_path.stem)
        if profile is None:
            print("\n  ✗ The repaired profile still does not load.")  # noqa: T201
            print(f"    {self._describe_profile_load_failure(new_path.stem)}")  # noqa: T201
            return None
        return profile

    def _delete_profile_confirmed(self, profile_name: str) -> None:
        """Deletes a profile only after the user types DELETE to confirm.

        AA does not destroy a user's data to resolve its own error — the
        confirmation is always explicit and the default answer is cancel.
        """
        print(f"\n  Deleting '{profile_name}' is permanent and cannot be undone.")  # noqa: T201
        try:
            confirm = input("  Type DELETE to confirm (anything else cancels): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled — nothing was deleted.")  # noqa: T201
            return

        if confirm != "DELETE":
            print("  Cancelled — nothing was deleted.")  # noqa: T201
            return

        if self.repo.delete_profile(profile_name):
            print(f"  Deleted: {profile_name}")  # noqa: T201
        else:
            print(f"  Nothing was deleted ({profile_name} not found or protected).")  # noqa: T201

    # =========================================================================
    # RESULTS DISPLAY
    # =========================================================================

    def _print_results(self, controller: "SessionController") -> None:
        """Displays a full session summary after execution completes.

        Reads from the controller's typed summary() — which now includes the
        discovered-job list read from job_history, so a collect-only run
        actually shows its payoff. After printing, offers the two opt-in
        custody exports (results CSV, profile JSON) and shows recent session
        history.
        """
        print("\n" + "\u2550" * 60)  # noqa: T201
        print("  SESSION COMPLETE")  # noqa: T201
        print("\u2550" * 60)  # noqa: T201

        try:
            summary = controller.summary()

            jobs_found      = summary.jobs_discovered
            jobs_vetted     = summary.jobs_vetted
            jobs_passed     = summary.jobs_passed_vetting
            apps_tried      = summary.applications_attempted
            apps_submitted  = summary.applications_submitted
            apps_failed     = summary.applications_failed
            apps_blocked    = summary.submissions_blocked_by_gate
            gate_remedy     = summary.gate_block_remedy
            duration_s      = summary.duration_seconds
            submitted       = summary.submitted
            discovered      = summary.discovered

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

            if summary.autonomy_enabled:
                print("  Autonomy: ON — this session submitted without review (fully automated).")  # noqa: T201

            if gate_remedy:
                print(f"\n  {gate_remedy}")  # noqa: T201

            # ── Discovered jobs — the collect-run payoff (C2) ────────────
            if discovered:
                print(f"\n  Discovered jobs ({len(discovered)}):")  # noqa: T201
                for idx, job in enumerate(discovered[:10], start=1):
                    print(f"    {idx:>2}. {job.title} — {job.company}")  # noqa: T201
                    print(f"        {job.url}")  # noqa: T201
                if len(discovered) > 10:
                    print(f"    ... and {len(discovered) - 10} more (export to keep them all)")  # noqa: T201

            if submitted:
                print(f"\n  Submitted applications:")  # noqa: T201
                for record in submitted[:10]:  # cap at 10 for readability
                    label = f" ({record.company})" if record.company else ""
                    print(f"    \u2192 {record.url[:70]}{label}")  # noqa: T201
                if len(submitted) > 10:
                    print(f"    ... and {len(submitted) - 10} more (see session report)")  # noqa: T201

            # Session report file location
            if summary.report_path:
                print(f"\n  \U0001f4c1  Full report: {summary.report_path}")  # noqa: T201

        except Exception as exc:
            logger.error("Could not retrieve session stats: %s", exc)
            print("  (Session stats unavailable — check logs for details)")  # noqa: T201

        print("\n" + "\u2550" * 60)  # noqa: T201

        # ── Recent session history (C2) ───────────────────────────────────
        self._print_history(controller)

        # ── Opt-in custody exports (C2) ───────────────────────────────────
        self._offer_results_export(controller)
        self._offer_profile_export(controller)

        try:
            again = input("\nRun another session? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if again == "y":
            self.run()

    def _print_history(self, controller: "SessionController", limit: int = 5) -> None:
        """Prints the most recent past sessions with their outcomes."""
        try:
            entries = controller.list_session_history()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not list session history: %s", exc)
            return
        if not entries:
            return

        print("\n  Recent sessions:")  # noqa: T201
        for entry in entries[:limit]:
            stamp = entry.started_at[:16].replace("T", " ") if entry.started_at else "?"
            duration = _format_seconds(entry.duration_seconds)
            print(  # noqa: T201
                f"    {stamp} · {entry.completion_state} · "
                f"found {entry.jobs_found} · applied {entry.applications_submitted} · "
                f"failed {entry.applications_failed} · {duration}"
            )

    def _offer_results_export(self, controller: "SessionController") -> None:
        """Offers to write the session's discovered jobs to a CSV file.

        Opt-in only: nothing is written unless the user says yes and names a
        directory. The results already survive in job_history, so this is a
        custody act, never a survival mechanism.
        """
        try:
            answer = input("\nExport these results to a CSV file? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return
        if answer != "y":
            return

        try:
            destination = input("  Destination directory: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return
        if not destination:
            return

        try:
            path = controller.export_session_results(Path(destination))
            print(f"  \u2713 Results exported: {path}")  # noqa: T201
        except (ValueError, FileExistsError, OSError, RuntimeError) as exc:
            print(f"  \u2717 Could not export: {exc}")  # noqa: T201

    def _offer_profile_export(self, controller: "SessionController") -> None:
        """Offers to export the active profile to a user-chosen directory.

        The custody complement of importing: a person who can bring a profile
        into AA on a borrowed machine can take one away. Plaintext JSON by
        design — the stored profile and its encryption are never touched.
        """
        try:
            answer = input("Export your profile to a file? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return
        if answer != "y":
            return

        profile = controller.registry.get_active_profile()
        profile_name = getattr(profile, "profile_name", "") if profile is not None else ""
        if not profile_name:
            print("  \u2717 No active profile to export.")  # noqa: T201
            return

        try:
            destination = input("  Destination directory: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()  # noqa: T201
            return
        if not destination:
            return

        try:
            path = controller.export_profile(profile_name, Path(destination))
            print(f"  \u2713 Profile exported: {path}")  # noqa: T201
            print("    (plaintext JSON — readable on any machine, no password needed)")  # noqa: T201
        except (ValueError, FileExistsError, OSError, RuntimeError) as exc:
            print(f"  \u2717 Could not export: {exc}")  # noqa: T201


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
