"""
Handles the first-run setup wizard for the application.

This module is responsible for detecting if the application has been configured,
and if not, guiding the user through creating their initial profile.
"""
import json
import shutil
from pathlib import Path

import os
import stat
import logging

from ..exceptions import ProfileConfigurationError

from importlib import resources

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(str(resources.files('auto_apply') / 'profiles'))
DEFAULT_PROFILE_PATH = PROFILES_DIR / "default_profile.json"
TEMPLATE_PROFILE_PATH = PROFILES_DIR / "template_profile.json"

def _check_file_permissions():
    """Checks if the profile file has overly permissive permissions."""
    if os.name == 'nt':
        return

    st = os.stat(DEFAULT_PROFILE_PATH)
    permissions = st.st_mode

    if permissions & stat.S_IRWXO or permissions & stat.S_IRWXG:
        logger.warning("--- SECURITY WARNING ---")
        logger.warning("Your profile file '%s' is readable by other users on this system.", DEFAULT_PROFILE_PATH)
        logger.warning("It is highly recommended to restrict permissions by running: chmod 600 '%s'", DEFAULT_PROFILE_PATH)

def check_and_run_setup() -> bool:
    """
    Checks if the default profile exists. If not, runs the setup wizard.
    Returns True if the app is configured and ready, False otherwise.
    """
    if DEFAULT_PROFILE_PATH.exists():
        try:
            with open(DEFAULT_PROFILE_PATH, "r") as f:
                data = json.load(f)
                if not data:
                    print("⚠️ Warning: Default profile is empty. Re-running setup.")
                    return run_setup_wizard()
            _check_file_permissions()
            return True
        except (json.JSONDecodeError, IOError):
            print("⚠️ Warning: Default profile is corrupted. Re-running setup.")
            return run_setup_wizard()
    else:
        return run_setup_wizard()

def run_setup_wizard() -> bool:
    """
    Guides the user through creating their first profile.
    For now, this is a simplified version.
    """
    print("\n--- Welcome to AutoApply First-Time Setup ---")
    print("It looks like this is your first time running the application.")
    print("Let's create a default profile for you.")

    if not TEMPLATE_PROFILE_PATH.exists():
        raise ProfileConfigurationError(
            f"Critical error: The profile template is missing at {TEMPLATE_PROFILE_PATH}. "
            "Please restore it from the source repository."
        )

    try:
        print(f"\nCreating your 'default_profile.json' from the template...")
        PROFILES_DIR.mkdir(exist_ok=True)
        shutil.copy(TEMPLATE_PROFILE_PATH, DEFAULT_PROFILE_PATH)

        logger.info("\n--- A basic profile has been created! ---")
        logger.info("ACTION REQUIRED: Please open this file and fill in your personal information:")
        logger.info("'%s'", DEFAULT_PROFILE_PATH)
        print("For now, the application will continue with the default template data.")
        input("Press Enter to continue...")
        return True

    except Exception as e:
        logger.error("An error occurred during setup: %s", e, exc_info=True)
        return False