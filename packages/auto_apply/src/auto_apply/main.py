"""
The main entry point for the AutoApply application.
Orchestrates the entire workflow from setup to completion.

This script is the primary executable for the project. It is responsible for:
1.  Parsing command-line arguments to determine the application's run mode.
2.  Setting up the global logging configuration.
3.  Launching the appropriate user interface (CLI or GUI).
"""
import argparse
import logging
from auto_apply.utils.logger import setup_logging
from auto_apply.agent.agent_orchestrator import AgentOrchestrator
from auto_apply.core.first_run_setup import check_and_run_setup
from auto_apply.core.startup_checks import perform_security_check

def main_cli() -> None:
    """Initializes and runs the application in Command-Line Interface (CLI) mode.

    This function instantiates the `AgentOrchestrator` and calls its `run`
    method, which contains the core application logic. All feedback and logging
    will be directed to the console.
    """
    logger = logging.getLogger(__name__)
    logger.info("Application starting in CLI mode.")

    # Perform initial setup and security checks before starting the agent
    if not check_and_run_setup():
        logger.warning("Setup was not completed. Exiting.")
        return
    perform_security_check(is_gui=False)

    orchestrator = AgentOrchestrator()
    orchestrator.run()

def main_gui() -> None:
    """Launches the Graphical User Interface (GUI) for the application.

    This function imports the main Tkinter application class and starts its
    event loop. This will open the main application window.
    """
    logger = logging.getLogger(__name__)
    logger.info("Application starting in GUI mode.")
    try:
        from auto_apply.ui.app import AutoApplyApp
        app = AutoApplyApp()
        app.mainloop()
    except ImportError as e:
        logger.critical(
            "GUI dependencies are not installed. Please run 'pip install .[gui]' to install them. Error: %s", e
        )
    except Exception as e:
        logger.critical("Failed to launch the GUI. Error: %s", e, exc_info=True)

def main() -> None:
    """Parses command-line arguments and launches the appropriate application mode."""
    parser = argparse.ArgumentParser(
        description="AutoApply: An autonomous agent for discovering, vetting, and applying for jobs."
    )
    parser.add_argument(
        '--cli',
        action='store_true',
        help='Run the application in Command-Line Interface (CLI) mode instead of the default GUI.'
    )
    args = parser.parse_args()

    setup_logging(console_level=logging.INFO)

    if args.cli:
        main_cli()
    else:
        main_gui()

if __name__ == "__main__":
    main()