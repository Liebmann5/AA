"""
A utility to detect which supported web browsers are installed on the user's OS.
This is a critical part of the browser factory's fallback mechanism.
"""
import logging
import os
import shutil
import platform
from typing import List

logger = logging.getLogger(__name__)

BROWSER_PRIORITY = ["chrome", "firefox", "edge", "safari"]

def get_installed_browsers() -> List[str]:
    """
    Detects installed browsers based on the operating system and returns them
    in the order of preference defined by BROWSER_PRIORITY.
    """
    os_name = platform.system().lower()
    installed_browsers = set()

    if os_name == "windows":
        installed_browsers = _get_windows_browsers()
    elif os_name == "darwin":
        installed_browsers = _get_macos_browsers()
    elif os_name == "linux":
        installed_browsers = _get_linux_browsers()
    else:
        logger.warning("Unsupported operating system '%s'. Browser detection may be unreliable.", os_name)

    sorted_installed = sorted(
        list(installed_browsers),
        key=lambda browser: BROWSER_PRIORITY.index(browser)
    )

    if not sorted_installed:
        logger.error("Could not detect any of the supported browsers: %s", BROWSER_PRIORITY)
    else:
        logger.info("Detected installed browsers: %s", sorted_installed)

    return sorted_installed

def _get_windows_browsers() -> set:
    """Checks for browsers on Windows using common installation paths."""
    browsers = set()
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")

    browser_paths = {
        "chrome": os.path.join(program_files, "Google\\Chrome\\Application\\chrome.exe"),
        "firefox": os.path.join(program_files, "Mozilla Firefox\\firefox.exe"),
        "edge": os.path.join(program_files, "Microsoft\\Edge\\Application\\msedge.exe"),
    }

    for browser, path in browser_paths.items():
        if os.path.exists(path):
            browsers.add(browser)

    browser_paths_x86 = {
        "chrome": os.path.join(program_files_x86, "Google\\Chrome\\Application\\chrome.exe"),
        "firefox": os.path.join(program_files_x86, "Mozilla Firefox\\firefox.exe"),
    }

    for browser, path in browser_paths_x86.items():
        if os.path.exists(path):
            browsers.add(browser)
    return browsers

def _get_macos_browsers() -> set:
    """Checks for browsers on macOS in the /Applications directory."""
    browsers = set()
    app_dir = "/Applications"

    browser_apps = {
        "chrome": "Google Chrome.app",
        "firefox": "Firefox.app",
        "edge": "Microsoft Edge.app",
        "safari": "Safari.app",
    }

    for browser, app_name in browser_apps.items():
        if os.path.exists(os.path.join(app_dir, app_name)):
            browsers.add(browser)
    return browsers

def _get_linux_browsers() -> set:
    """Checks for browsers on Linux by looking for their executables in PATH."""
    browsers = set()

    browser_commands = {
        "chrome": "google-chrome",
        "firefox": "firefox",
    }

    for browser, command in browser_commands.items():
        if shutil.which(command):
            browsers.add(browser)
    return browsers