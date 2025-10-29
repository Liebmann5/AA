"""
Manages the just-in-time installation of Playwright browsers.
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_playwright_cache_dir() -> Path:
    """Gets the default cache directory for Playwright browsers."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local" / "ms-playwright"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        return Path.home() / ".cache" / "ms-playwright"

def are_browsers_installed() -> bool:
    """
    Checks if the Playwright browser binaries appear to be installed.
    This is a simple check for the existence of the cache directory.
    """
    cache_dir = _get_playwright_cache_dir()
    if cache_dir.exists() and any(cache_dir.iterdir()):
        logger.info("Playwright browser cache found at '%s'.", cache_dir)
        return True
    logger.info("Playwright browser cache not found or is empty.")
    return False

def install_browsers() -> bool:
    """
    Runs the 'playwright install' command to download browser binaries.
    Provides real-time feedback to the console.

    Returns:
        True if the installation was successful, False otherwise.
    """
    if are_browsers_installed():
        return True

    logger.warning("--- Playwright Browsers Not Found ---")
    logger.warning("Attempting to download and install them now. This may take a few minutes...")

    command = [sys.executable, "-m", "playwright", "install"]

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        for line in iter(process.stdout.readline, ''):
            logger.info(line.strip())
        process.wait()
        if process.returncode == 0:
            logger.info("Playwright browsers installed successfully.")
            return True
        else:
            logger.error("Playwright browser installation failed with exit code %d.", process.returncode)
            return False

    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.critical("An error occurred while trying to run 'playwright install': %s", e)
        return False