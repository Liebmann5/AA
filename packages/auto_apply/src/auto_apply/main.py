"""The entry point for the AutoApply application.

This script bootstraps the environment and launches the appropriate
user interface (GUI or CLI). It is the ONLY file that should be called
directly by the user or by __main__.py.

Startup Sequence:
    1. Pre-import argument parsing (--portable, --seed) — must run before
       any auto_apply import because domain/config.py resolves paths at
       import time.
    2. Configure structured logging.
    3. Parse command-line arguments (--cli, --debug, --check-config,
       --seed, --profile, --portable, --export-research, --encrypt-profile).
    4. Initialize infrastructure (SQLite database with WAL mode).
    5. Launch the selected interface or print configuration summary.

The GUI is imported lazily to avoid requiring Tkinter on headless systems
where only CLI mode is used.

Usage:
    python -m auto_apply                  # Launches GUI (default)
    python -m auto_apply --cli            # Launches CLI
    python -m auto_apply --debug          # Enables verbose logging
    python -m auto_apply --check-config   # Prints environment summary and exits
    python -m auto_apply --seed 42        # Deterministic mode (research reproducibility)
    python -m auto_apply --profile nick   # Load a specific profile, skip selection
    python -m auto_apply --portable       # Force portable mode (data in ./data/)
    python -m auto_apply --export-research          # Export research signals and exit
    python -m auto_apply --export-research --export-format parquet
    python -m auto_apply --encrypt-profile          # Encrypt the current profile
"""

import argparse
import logging
import os
import signal
import sys
from pathlib import Path


# ═════════════════════════════════════════════════════════════════════════════
# Pre-import argument parsing — must run BEFORE any auto_apply imports.
# domain/config.py resolves paths at import time, so the AA_DATA_DIR and
# AA_RANDOM_SEED env vars must be set before the first import of any
# auto_apply module.
# ═════════════════════════════════════════════════════════════════════════════

def _pre_import_parse() -> None:
    """Parse --portable and --seed before importing auto_apply modules.

    domain/config.py computes USER_DATA_DIR and friends at import time.
    Setting AA_DATA_DIR via env var before that import is the only way
    to redirect all data paths for portable mode.  Similarly, the random
    seed must be set before any component reads it.
    """
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--portable",
        action="store_true",
        default=False,
        help=(
            "Force portable mode: store all data in ./data/ relative to the "
            "current working directory.  Equivalent to setting AA_DATA_DIR=./data."
        ),
    )
    pre_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Deterministic mode with random seed N.",
    )
    pre_args, _ = pre_parser.parse_known_args()

    if pre_args.portable:
        portable_data = Path.cwd() / "data"
        os.environ["AA_DATA_DIR"] = str(portable_data)
        print(f"[Portable mode] Data directory: {portable_data}")  # noqa: T201

    if pre_args.seed is not None:
        os.environ["AA_RANDOM_SEED"] = str(pre_args.seed)


_pre_import_parse()

# ═════════════════════════════════════════════════════════════════════════════
# Now it's safe to import auto_apply modules — config paths are resolved.
# ═════════════════════════════════════════════════════════════════════════════

from auto_apply.infrastructure.logging_setup import setup_logging
from auto_apply.infrastructure.composition_root import build_session


def launch_gui(profile_repo, profile_override=None) -> None:
    """Imports and launches the graphical interface.

    Tkinter is imported lazily here so that CLI-only users on headless
    systems don't need it installed.

    Args:
        profile_repo: An initialized ProfileRepository.
        profile_override: Optional profile name or path from ``--profile``.
    """
    try:
        from auto_apply.adapters.primary.gui.app import AutoApplyApp  # noqa: PLC0415
        from auto_apply.infrastructure.composition_root import (  # noqa: PLC0415
            CapabilitiesRegistry,
            build_session_controller,
        )

        app = AutoApplyApp(
            build_registry=CapabilitiesRegistry.build,
            create_controller=build_session_controller,
            profile_repo=profile_repo,
            profile_override=profile_override,
        )
        app.mainloop()
    except ImportError as exc:
        logging.error("GUI dependencies missing: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logging.critical("GUI crashed: %s", exc, exc_info=True)
        sys.exit(1)


def launch_cli(profile_repo_factory, profile_override=None) -> None:
    """Launches the command-line interface.

    Args:
        profile_repo_factory: Callable that returns a ProfileRepository.
        profile_override: Optional profile name or path from ``--profile``.
    """
    try:
        from auto_apply.adapters.primary.cli.startup import CLIStartup  # noqa: PLC0415

        cli = CLIStartup(
            profile_repo_factory=profile_repo_factory,
            profile_override=profile_override,
        )
        cli.run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        logging.critical("CLI crashed: %s", exc, exc_info=True)
        sys.exit(1)


def _print_check_config(profile_repo) -> None:
    """Prints the current runtime configuration summary and exits."""
    from auto_apply.infrastructure.registry import (  # noqa: PLC0415
        CapabilitiesRegistry,
    )
    from auto_apply.adapters.secondary.os.detectors import (  # noqa: PLC0415
        BrowserDetector,
        ToolDetector,
    )
    from auto_apply.adapters.secondary.os.hardware import (  # noqa: PLC0415
        HardwareInspector,
    )
    from auto_apply.adapters.secondary.os.platform_inspector import (  # noqa: PLC0415
        PlatformInspector,
    )

    # Load default profile if available, otherwise use a minimal placeholder.
    default_profile = profile_repo.load_profile("default_profile")
    if default_profile is None:
        print("No default profile found — using minimal profile for check.")
        # Create a minimal profile just for CapabilitiesRegistry build.
        from auto_apply.domain.models.profile import UserProfile  # noqa: PLC0415
        default_profile = UserProfile.model_validate({
            "profile_name": "minimal-check",
            "personal_info": {
                "first_name": "Check",
                "last_name": "User",
                "email": "check@example.com",
                "phone_number": "000-000-0000",
                "street_address": "",
                "city": "",
                "state": "",
                "zip_code": "",
            },
            "links": {},
            "career_summary": "Check profile for environment verification.",
            "search_preferences": {
                "desired_job_titles": ["Software Engineer"],
            },
            "politeness_settings": {},
        })

    registry = CapabilitiesRegistry.build(user_profile=default_profile)
    env = registry.get_environment_capabilities()
    admin = registry.get_admin_policy()

    print("\nAutoApply — Environment Configuration Check\n")
    print(f" Platform          : {env.os_name} ({env.os_version})")
    print(f" Python version    : {PlatformInspector.inspect().python_version}")
    print(f" CPU cores         : {env.cpu_cores}")
    print(f" RAM (MB)          : {env.ram_mb}")
    print(f" Free disk (MB)    : {env.disk_free_mb}")
    print(f" Low-resource mode : {env.is_low_resource}")
    print(f" Browsers detected : {env.available_browsers or 'none'}")
    print(f" Tools available   : {env.available_tools or 'none'}")
    if admin and admin.has_any_constraint():
        print(f" Admin policy      : active ({admin.policy_version})")
    else:
        print(" Admin policy      : none")
    print("")


def _handle_export_research(args) -> None:
    """Export all collected research signals and exit.

    Does not start a job search session.
    """
    from auto_apply.adapters.secondary.research.parquet_exporter import (
        ParquetExporter,
    )
    from auto_apply.domain.config import REPORTS_DIR, RESEARCH_DIR

    exporter = ParquetExporter(
        db_path=RESEARCH_DIR / "research_signals.db",
        export_dir=REPORTS_DIR,
    )

    fmt = args.export_format or "csv"
    print(f"Exporting research signals as {fmt.upper()}...")

    try:
        signals_path = exporter.export_signals(fmt=fmt)
        print(f"  ✓ Signals exported:        {signals_path}")

        salary_path = exporter.export_salary_corpus(fmt=fmt)
        print(f"  ✓ Salary corpus exported:  {salary_path}")

        forms_path = exporter.export_form_observations(fmt=fmt)
        print(f"  ✓ Form observations:       {forms_path}")

        print(f"\n  All files written to: {REPORTS_DIR}")

    except ImportError as exc:
        print(f"  ✗ Missing dependency: {exc}")
        print("    Install with: pip install pyarrow")
        sys.exit(1)
    except Exception as exc:
        print(f"  ✗ Export failed: {exc}")
        sys.exit(1)

    sys.exit(0)


def _handle_encrypt_profile(profile_repo) -> None:
    """Encrypt the current plaintext profile into a .vault file.

    The plaintext .json is deleted after successful encryption.
    """
    import getpass

    try:
        profile = profile_repo.load_profile("default_profile")
        if profile is None:
            # Try to list profiles and load the first one
            profiles = profile_repo.list_profiles()
            user_profiles = [p for p in profiles if p != "default_profile"]
            if not user_profiles:
                print("No profiles found to encrypt.")
                sys.exit(1)
            profile = profile_repo.load_profile(user_profiles[0])

        if profile is None:
            print("Could not load any profile for encryption.")
            sys.exit(1)

        print(f"\n  Encrypting profile: {profile.profile_name}")
        print("  Choose a master password to protect your profile.")
        print("  You will need this password every time you launch AA.\n")

        password = getpass.getpass("  Master password: ")
        if not password:
            print("  Password cannot be empty.")
            sys.exit(1)

        confirm = getpass.getpass("  Confirm password: ")
        if password != confirm:
            print("  Passwords do not match.")
            sys.exit(1)

        # Rebuild the repo with the vault password
        from auto_apply.adapters.secondary.persistence.profile_repository import (
            ProfileRepository,
        )
        vault_repo = ProfileRepository(master_password=password)
        vault_path = vault_repo.save_profile(profile)

        print(f"\n  ✓ Profile encrypted: {vault_path}")
        print("  Set AA_VAULT_PASSWORD env var to skip the password prompt")
        print("  in future sessions.\n")

    except KeyboardInterrupt:
        print("\n  Encryption cancelled.")
        sys.exit(0)
    except Exception as exc:
        print(f"  ✗ Encryption failed: {exc}")
        sys.exit(1)

    sys.exit(0)


def main() -> None:
    """Parses arguments and executes the selected run mode."""
    def _sigint_handler(sig, frame):
        print("\nInterrupted — exiting.")  # noqa: T201
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint_handler)

    # 1. Parse Arguments — BEFORE logging setup. setup_logging's
    # console_level and debug_mode parameters always existed but were never
    # passed; calling it bare here meant --debug arrived after the console
    # handler was capped at INFO, and the old post-parse root setLevel was a
    # no-op (the root logger was already DEBUG). The handler is the
    # bottleneck; the flag now reaches it.
    parser = argparse.ArgumentParser(
        description="AutoApply: Autonomous Agent (Secret) Job"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in Command Line Interface (Terminal)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Print environment/capability summary and exit",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Run in deterministic mode with random seed N. "
            "Produces identical execution traces for the same configuration. "
            "Required for research reproducibility and benchmarking. "
            "Example: --seed 42"
        ),
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        metavar="NAME_OR_PATH",
        help=(
            "Profile name or path to use for this session. "
            "Overrides the default profile selection. "
            "Example: --profile nick_engineer or --profile /path/to/profile.json"
        ),
    )
    parser.add_argument(
        "--portable",
        action="store_true",
        default=False,
        help=(
            "Force portable mode: store all data in ./data/ relative to the "
            "current working directory.  Equivalent to setting AA_DATA_DIR=./data."
        ),
    )
    parser.add_argument(
        "--export-research",
        action="store_true",
        help=(
            "Export all collected research signals to a file and exit. "
            "Does not start a job search session. "
            "Use --export-format to choose output format."
        ),
    )
    parser.add_argument(
        "--export-format",
        choices=["csv", "json", "parquet"],
        default="csv",
        help="Output format for --export-research (default: csv).",
    )
    parser.add_argument(
        "--encrypt-profile",
        action="store_true",
        help=(
            "Encrypt the current plaintext profile into a .vault file "
            "protected by a master password. "
            "The plaintext .json is deleted after successful encryption. "
            "Example: python -m auto_apply --encrypt-profile"
        ),
    )
    args = parser.parse_args()

    # 2. Configure Logging — with the parsed flag.
    setup_logging(
        console_level=logging.DEBUG if args.debug else logging.INFO,
        debug_mode=args.debug,
    )
    logger = logging.getLogger("Main")

    if args.debug:
        logger.debug("Logging - DEBUG ENABLED")

    # ── Deterministic mode — set env var before any component reads config ──
    if args.seed is not None:
        os.environ["AA_RANDOM_SEED"] = str(args.seed)
        logger.info("Deterministic mode | seed=%d", args.seed)

    # ── Portable mode — AA_DATA_DIR already set by _pre_import_parse if
    # --portable was passed; the main parser recognises it for help text.
    if args.portable:
        logger.info(
            "Portable mode | data=%s",
            os.environ.get("AA_DATA_DIR", "./data"),
        )

    logger.info("Bootstrapping AutoApply...")

    # 3. Initialize Infrastructure
    try:
        profile_repo = build_session()
    except Exception as exc:
        logger.critical(
            "Infrastructure initialization failed: %s", exc, exc_info=True
        )
        sys.exit(1)

    # 4. Research export mode (exits after export — no session started)
    if args.export_research:
        _handle_export_research(args)

    # 5. Profile encryption mode (exits after encryption)
    if args.encrypt_profile:
        _handle_encrypt_profile(profile_repo)

    # 6. Check-config mode
    if args.check_config:
        _print_check_config(profile_repo)
        return

    # 7. Launch Interface
    profile_override = args.profile

    if args.cli:
        logger.info("Initializing CLI startup sequence...")
        launch_cli(
            profile_repo_factory=build_session,
            profile_override=profile_override,
        )
    else:
        logger.info("Launching GUI")
        launch_gui(
            profile_repo=profile_repo,
            profile_override=profile_override,
        )


if __name__ == "__main__":
    main()