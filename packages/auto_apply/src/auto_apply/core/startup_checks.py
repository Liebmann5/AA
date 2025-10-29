"""
Performs critical checks every time the application starts.
"""
import os
import stat
import logging
from tkinter import messagebox
from .first_run_setup import DEFAULT_PROFILE_PATH

logger = logging.getLogger(__name__)

def perform_security_check(is_gui: bool):
    """
    Performs critical security checks on the user's profile file.
    Presents a UI warning in GUI mode or a console warning in CLI mode.
    """
    if not DEFAULT_PROFILE_PATH.exists() or os.name == 'nt':
        return

    try:
        permissions = os.stat(DEFAULT_PROFILE_PATH).st_mode
        if permissions & (stat.S_IRWXG | stat.S_IRWXO):
            message = (
                f"Your profile file is not secure!\n\n"
                f"It can be read by other users on this computer.\n\n"
                f"To protect your data, please open a terminal and run:\n"
                f"chmod 600 '{DEFAULT_PROFILE_PATH.resolve()}'"
            )
            if is_gui:
                messagebox.showwarning("CRITICAL SECURITY WARNING", message)
            else:
                logger.critical("--- CRITICAL SECURITY WARNING ---")
                logger.critical(message)
                input("Press Enter to acknowledge and continue at your own risk...")
    except Exception as e:
        logger.error("Could not perform security check on profile file. Error: %s", e)