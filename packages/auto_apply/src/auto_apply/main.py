"""The entry point for the AutoApply application.

This script bootstraps the environment and launches the appropriate
user interface (GUI or CLI). It is the ONLY file that should be called
directly by the user or by __main__.py.

Startup Sequence:
    1. Configure structured logging.
    2. Parse command-line arguments (--cli, --debug, --check-config).
    3. Initialize infrastructure (SQLite database with WAL mode).
    4. Launch the selected interface or print configuration summary.

The GUI is imported lazily to avoid requiring Tkinter on headless systems
where only CLI mode is used.

Usage:
    python -m auto_apply              # Launches GUI (default)
    python -m auto_apply --cli        # Launches CLI
    python -m auto_apply --debug      # Enables verbose logging
    python -m auto_apply --check-config  # Prints environment summary and exits
"""

import argparse
import logging
import signal
import sys

from auto_apply.domain.logging import setup_logging
from auto_apply.infrastructure.composition_root import build_session


def launch_gui(profile_repo) -> None:
    """Imports and launches the graphical interface.

    Tkinter is imported lazily here so that CLI-only users on headless
    systems don't need it installed.
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
        )
        app.mainloop()
    except ImportError as exc:
        logging.error("GUI dependencies missing: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logging.critical("GUI crashed: %s", exc, exc_info=True)
        sys.exit(1)


def launch_cli(profile_repo_factory) -> None:
    """Launches the command-line interface."""
    try:
        from auto_apply.adapters.primary.cli.startup import CLIStartup  # noqa: PLC0415

        cli = CLIStartup(profile_repo_factory=profile_repo_factory)
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


def main() -> None:
    """Parses arguments and executes the selected run mode."""
    def _sigint_handler(sig, frame):
        print("\nInterrupted — exiting.")  # noqa: T201
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint_handler)

    # 1. Configure Logging
    setup_logging()
    logger = logging.getLogger("Main")

    # 2. Parse Arguments
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
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Logging - DEBUG ENABLED")

    logger.info("Bootstrapping AutoApply...")

    # 3. Initialize Infrastructure
    try:
        profile_repo = build_session()
    except Exception as exc:
        logger.critical("Infrastructure initialization failed: %s", exc, exc_info=True)
        sys.exit(1)

    # 4. Check-config mode
    if args.check_config:
        _print_check_config(profile_repo)
        return

    # 5. Launch Interface
    if args.cli:
        logger.info("Initializing CLI startup sequence...")
        launch_cli(profile_repo_factory=build_session)
    else:
        logger.info("Launching GUI")
        launch_gui(profile_repo=profile_repo)


if __name__ == "__main__":
    main()