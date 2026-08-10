"""Detects installed browsers and optional tools on the host system.

This module provides two class-based detectors that scan the operating system
for available software. They are consumed by CapabilitiesRegistry during the
boot sequence and never called directly by domain engines or services.

Architecture:
    Detection (this module) answers: "What is physically installed?"
    CapabilitiesRegistry answers:    "What is available AND allowed?"
    BrowserCascade answers:          "Which one should we actually use?"

    These are three separate concerns. Detection is pure I/O — it reads the
    Windows Registry, scans /Applications on macOS, checks PATH on Linux.
    It has no knowledge of admin policy, user preferences, or session state.

Platform Support:
    - Windows: Reads HKLM\\SOFTWARE\\...\\Uninstall registry keys.
    - macOS: Scans /Applications for .app bundles with Info.plist.
    - Linux: Checks PATH via shutil.which() and runs --version commands.

Graceful Degradation:
    Every detection method is wrapped in try/except. If a platform-specific
    API is unavailable (e.g., winreg on Linux, plistlib failures), the
    detector returns an empty list rather than crashing. The boot sequence
    continues and logs a warning.

Example:
    >>> from auto_apply.adapters.secondary.os.detectors import BrowserDetector, ToolDetector
    >>>
    >>> browsers = BrowserDetector.detect_installed_browsers()
    >>> # ['chrome', 'firefox', 'edge']
    >>>
    >>> tools = ToolDetector.detect_optional_tools()
    >>> # ['playwright', 'undetected_chromedriver']
"""  # noqa: E501

import logging
import os
import platform
from typing import Any
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Import plistlib only where available (all platforms ship it, but guard anyway).
try:
    import plistlib
except ImportError:
    plistlib = None  # type: ignore[assignment]

# winreg is Windows-only.
_winreg: Any = None
if platform.system() == "Windows":
    try:
        import winreg as _winreg  # type: ignore[no-redef]
    except ImportError:
        pass


# Priority order for browser selection. BrowserCascade uses this as the
# default preference when the user hasn't specified their own order.
BROWSER_PRIORITY: list[str] = ["chrome", "firefox", "edge", "safari", "brave"]


# ═════════════════════════════════════════════════════════════════════════════
# BROWSER DETECTOR
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class DetectedBrowser:
    """Information about a single detected browser.

    Attributes:
        name: Normalized lowercase name (e.g., "chrome", "firefox").
        version: Major version string (e.g., "120"), or None if unknown.
        version_full: Full version string (e.g., "120.0.6099.130"), or None.
        path: Filesystem path to the executable, or None if not determined.
    """
    name: str
    version: str | None = None
    version_full: str | None = None
    path: str | None = None


class BrowserDetector:
    """Detects installed web browsers on the host system.

    All methods are classmethods — no instance state is needed. Detection
    is a pure function of the OS environment.

    The primary method is detect_installed_browsers() which returns a list
    of normalized browser name strings in priority order. For richer data,
    use detect_browser_details() which returns DetectedBrowser objects.
    """

    @classmethod
    def detect_installed_browsers(cls) -> list[str]:
        """Returns a list of installed browser names in priority order.

        This is the method consumed by CapabilitiesRegistry.build().

        Returns:
            Ordered list of lowercase browser names, e.g. ["chrome", "firefox"].
            May be empty if no supported browsers are found.
        """
        details = cls.detect_browser_details()
        return [b.name for b in details]

    @classmethod
    def detect_browser_details(cls) -> list[DetectedBrowser]:
        """Returns detailed info about each detected browser.

        Detects browsers using OS-specific methods, deduplicates, and
        returns them sorted by BROWSER_PRIORITY order.

        Returns:
            Ordered list of DetectedBrowser objects.
        """
        os_name = platform.system().lower()

        raw: list[DetectedBrowser] = []
        try:
            if os_name == "windows":
                raw = cls._detect_windows()
            elif os_name == "darwin":
                raw = cls._detect_macos()
            elif os_name == "linux":
                raw = cls._detect_linux()
            else:
                logger.warning(
                    "Unsupported OS '%s' — browser detection may be incomplete",
                    os_name,
                )
        except Exception as exc:
            logger.error("Browser detection failed: %s", exc, exc_info=True)

        # Deduplicate and sort by priority order.
        seen: set[str] = set()
        ordered: list[DetectedBrowser] = []

        for priority_name in BROWSER_PRIORITY:
            for browser in raw:
                if browser.name == priority_name and browser.name not in seen:
                    ordered.append(browser)
                    seen.add(browser.name)
                    break

        # Append any detected browsers not in the priority list.
        for browser in raw:
            if browser.name not in seen:
                ordered.append(browser)
                seen.add(browser.name)

        if ordered:
            logger.info(
                "Detected browsers: %s",
                [f"{b.name} v{b.version or '?'}" for b in ordered],
            )
        else:
            logger.error(
                "No supported browsers detected. Checked: %s",
                BROWSER_PRIORITY,
            )

        return ordered

    # ── Windows ───────────────────────────────────────────────────────────

    @classmethod
    def _detect_windows(cls) -> list[DetectedBrowser]:
        """Detects browsers on Windows via the Uninstall registry keys."""
        if _winreg is None:
            return []

        browsers: list[DetectedBrowser] = []
        seen_names: set[str] = set()

        uninstall_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]

        # Map display name prefixes to normalized names.
        prefixes: dict[str, str] = {
            "Google Chrome": "chrome",
            "Mozilla Firefox": "firefox",
            "Microsoft Edge": "edge",
            "Brave": "brave",
        }

        for reg_path in uninstall_paths:
            try:
                with _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                    subkey_count = _winreg.QueryInfoKey(key)[0]
                    for i in range(subkey_count):
                        try:
                            subkey_name = _winreg.EnumKey(key, i)
                            with _winreg.OpenKey(key, subkey_name) as subkey:
                                display_name = _winreg.QueryValueEx(subkey, "DisplayName")[0]  # noqa: E501
                                display_version = _winreg.QueryValueEx(subkey, "DisplayVersion")[0]  # noqa: E501

                                for prefix, normalized in prefixes.items():
                                    if display_name.startswith(prefix) and normalized not in seen_names:  # noqa: E501
                                        major = display_version.split(".")[0] if display_version else None  # noqa: E501
                                        browsers.append(DetectedBrowser(
                                            name=normalized,
                                            version=major,
                                            version_full=display_version,
                                        ))
                                        seen_names.add(normalized)
                                        break

                        except (OSError, FileNotFoundError):
                            continue
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.warning("Registry read error: %s", exc)

        return browsers

    # ── macOS ─────────────────────────────────────────────────────────────

    @classmethod
    def _detect_macos(cls) -> list[DetectedBrowser]:
        """Detects browsers on macOS via /Applications and Info.plist."""
        if plistlib is None:
            return []

        browsers: list[DetectedBrowser] = []
        app_dir = "/Applications"

        app_map: dict[str, str] = {
            "chrome": "Google Chrome.app",
            "firefox": "Firefox.app",
            "edge": "Microsoft Edge.app",
            "safari": "Safari.app",
            "brave": "Brave Browser.app",
        }

        for name, app_name in app_map.items():
            app_path = os.path.join(app_dir, app_name)
            if not os.path.exists(app_path):
                continue

            version = None
            version_full = None
            try:
                plist_path = os.path.join(app_path, "Contents", "Info.plist")
                with open(plist_path, "rb") as f:
                    plist_data = plistlib.load(f)
                    version_full = (
                        plist_data.get("CFBundleShortVersionString")
                        or plist_data.get("CFBundleVersion")
                    )
                    if version_full:
                        version = version_full.split(".")[0]
            except Exception:
                logger.debug("Could not read Info.plist for %s", name)

            browsers.append(DetectedBrowser(
                name=name,
                version=version,
                version_full=version_full,
                path=app_path,
            ))

        return browsers

    # ── Linux ─────────────────────────────────────────────────────────────

    @classmethod
    def _detect_linux(cls) -> list[DetectedBrowser]:
        """Detects browsers on Linux via PATH lookup and --version flags."""
        browsers: list[DetectedBrowser] = []

        commands: dict[str, str] = {
            "chrome": "google-chrome",
            "firefox": "firefox",
            "edge": "microsoft-edge",
            "brave": "brave-browser",
        }

        for name, command in commands.items():
            executable = shutil.which(command)
            if executable is None:
                continue

            version = None
            version_full = None
            try:
                result = subprocess.run(
                    [command, "--version"],
                    capture_output=True, text=True, check=False,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout:
                    version_full = result.stdout.strip()
                    # Extract first dotted number.
                    for part in version_full.replace("(", " ").replace(")", " ").split():  # noqa: E501
                        if "." in part and part.split(".")[0].isdigit():
                            version = part.split(".")[0]
                            break
            except Exception:
                logger.debug("Could not get version for %s", command)

            browsers.append(DetectedBrowser(
                name=name,
                version=version,
                version_full=version_full,
                path=executable,
            ))

        return browsers


# ═════════════════════════════════════════════════════════════════════════════
# TOOL DETECTOR
# ═════════════════════════════════════════════════════════════════════════════

class ToolDetector:
    """Detects optional Python packages and tools that enhance AA.

    AA runs without any of these. When they are available, specific
    components can upgrade their behavior:
        - playwright: Alternative browser automation (PlaywrightAdapter).
        - undetected_chromedriver: Evasion-hardened Chrome driver.
        - nodriver: Ultra-lightweight Chrome automation.
        - spacy: NLP-based location extraction in vetting filters.
        - pgeocode: Offline postal code → city resolution.
        - clingo: ASP solver for form reasoning.
        - psutil: Hardware inspection and process management.

    Detection is pure import-checking — no tool is actually loaded or
    initialized. That happens lazily when the component that needs it
    first runs.
    """

    # Map of tool name → Python import path.
    # The key is the canonical name used throughout AA.
    # The value is the module to attempt importing.
    _TOOL_REGISTRY: dict[str, str] = {
        "selenium":                 "selenium",
        "playwright":               "playwright",
        "camoufox":                 "camoufox",
        "undetected_chromedriver":  "undetected_chromedriver",
        "nodriver":                 "nodriver",
        "botright":                 "botright",
        "zendriver":                "zendriver",
        "spacy":                    "spacy",
        "pgeocode":                 "pgeocode",
        "clingo":                   "clingo",
        "psutil":                   "psutil",
        "beautifulsoup4":           "bs4",
        "httpx":                    "httpx",
        "mechanicalsoup":           "mechanicalsoup",
        "pydub":                    "pydub",
        "vosk":                     "vosk",
        "speech_recognition":       "speech_recognition",
    }

    @classmethod
    def detect_optional_tools(cls) -> list[str]:
        """Returns a list of optional tools that are importable.

        Does not actually import the tools into the running process — it
        uses importlib.util.find_spec() which checks if the module exists
        without executing it.

        Returns:
            List of canonical tool names that are available, e.g.
            ["playwright", "psutil", "clingo"].
        """
        import importlib.util  # noqa: PLC0415

        available: list[str] = []

        for tool_name, import_path in cls._TOOL_REGISTRY.items():
            try:
                spec = importlib.util.find_spec(import_path)
                if spec is not None:
                    available.append(tool_name)
                    logger.debug("Optional tool available: %s", tool_name)
                else:
                    logger.debug("Optional tool not found: %s", tool_name)
            except (ModuleNotFoundError, ValueError):
                logger.debug("Optional tool not importable: %s", tool_name)

        logger.info(
            "Optional tools detected: %d/%d available — %s",
            len(available),
            len(cls._TOOL_REGISTRY),
            available or "none",
        )
        return available

    @classmethod
    def is_tool_importable(cls, tool_name: str) -> bool:
        """Checks if a specific tool is importable without importing it.

        Args:
            tool_name: The canonical tool name (e.g., "playwright").

        Returns:
            True if the tool's Python package can be found.
        """
        import importlib.util  # noqa: PLC0415

        import_path = cls._TOOL_REGISTRY.get(tool_name, tool_name)
        try:
            return importlib.util.find_spec(import_path) is not None
        except (ModuleNotFoundError, ValueError):
            return False