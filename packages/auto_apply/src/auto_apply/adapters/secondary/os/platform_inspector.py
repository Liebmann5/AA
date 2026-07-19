"""Detects the host operating system and platform characteristics.

This module provides PlatformInspector, which determines OS type, version,
and platform-specific details. The results are consumed by
CapabilitiesRegistry during the boot sequence and by infrastructure
components that need to make OS-specific decisions (file paths, browser
binary locations, process management strategies).

No External Dependencies:
    This module uses only Python standard library (platform, sys, os).
    It will never fail to import on any platform.

Example:
    >>> from auto_apply.adapters.secondary.os.platform_inspector import PlatformInspector
    >>>
    >>> plat = PlatformInspector.inspect()
    >>> print(plat.os_name, plat.os_version)
    windows 10.0.19041
    >>> print(plat.is_mobile)
    False
"""  # noqa: E501

import logging
import os
import platform
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PlatformSnapshot:
    """A snapshot of the host platform characteristics.

    Attributes:
        os_name: Normalized OS name: "windows", "macos", "linux", or "unknown".
            Note: macOS is normalized from Python's "darwin" to "macos" for
            consistency with user-facing strings throughout AA.
        os_version: OS version string (e.g., "10.0.19041", "14.2.1", "6.5.0").
        platform_string: Full platform identifier (e.g., "Windows-10-10.0.19041-SP0").
        python_version: Running Python version (e.g., "3.11.5").
        is_mobile: True if the environment appears to be mobile (Termux, etc.).
        is_frozen: True if running from a compiled executable (PyInstaller, etc.).
        is_removable_media: True if the working directory appears to be on
            removable media (USB drive). Heuristic, not guaranteed.
    """
    os_name: str = "unknown"
    os_version: str = "unknown"
    platform_string: str = "unknown"
    python_version: str = "unknown"
    is_mobile: bool = False
    is_frozen: bool = False
    is_removable_media: bool = False


class PlatformInspector:
    """Detects host platform characteristics for the CapabilitiesRegistry.

    All methods are classmethods — no instance state is needed.
    """

    @classmethod
    def inspect(cls) -> PlatformSnapshot:
        """Performs a full platform inspection.

        Returns:
            A PlatformSnapshot with detected values.
        """
        os_name = cls._normalize_os_name()

        snapshot = PlatformSnapshot(
            os_name=os_name,
            os_version=cls._detect_os_version(),
            platform_string=platform.platform(),
            python_version=platform.python_version(),
            is_mobile=cls._detect_mobile(),
            is_frozen=cls._detect_frozen(),
            is_removable_media=cls._detect_removable_media(),
        )

        logger.info(
            "Platform inspection | os=%s version=%s python=%s frozen=%s removable=%s",
            snapshot.os_name,
            snapshot.os_version,
            snapshot.python_version,
            snapshot.is_frozen,
            snapshot.is_removable_media,
        )

        return snapshot

    @classmethod
    def _normalize_os_name(cls) -> str:
        """Returns a normalized OS name string.

        Python's platform.system() returns "Darwin" for macOS. We normalize
        this to "macos" for consistency throughout AA.

        Returns:
            One of: "windows", "macos", "linux", or "unknown".
        """
        raw = platform.system().lower()
        normalization_map = {
            "windows": "windows",
            "darwin": "macos",
            "linux": "linux",
        }
        return normalization_map.get(raw, "unknown")

    @classmethod
    def _detect_os_version(cls) -> str:
        """Returns the OS version string.

        Returns:
            Version string, or "unknown" if detection fails.
        """
        try:
            return platform.version() or "unknown"
        except Exception:
            return "unknown"

    @classmethod
    def _detect_mobile(cls) -> bool:
        """Heuristic: is this a mobile-like environment?

        Checks for Android (Termux) or iOS signals. Python rarely runs
        on actual mobile, but Termux users exist.

        Returns:
            True if mobile signals are detected.
        """
        try:
            details = platform.platform().lower()
            return "android" in details or "ios" in details
        except Exception:
            return False

    @classmethod
    def _detect_frozen(cls) -> bool:
        """Checks if AA is running from a compiled executable.

        PyInstaller, Nuitka, and cx_Freeze set specific attributes on
        sys when the application is running from a compiled bundle.

        Returns:
            True if running from a frozen/compiled executable.
        """
        return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")

    @classmethod
    def _detect_removable_media(cls) -> bool:
        """Heuristic: is the working directory on removable media?

        Checks common USB drive indicators:
        - Windows: Drive letter other than C:
        - Linux/macOS: Path under /media/, /mnt/, or /Volumes/

        This is a best-effort heuristic, not a guarantee. False negatives
        are safe (AA will store data normally). False positives are also
        safe (AA will use the flash drive storage pattern, which works
        fine on local disks too).

        Returns:
            True if the working directory appears to be on removable media.
        """
        try:
            cwd = os.getcwd()
            system = platform.system().lower()

            if system == "windows":
                # Drive letter check: anything other than C: is likely USB.
                drive = os.path.splitdrive(cwd)[0].upper()
                if drive and drive != "C:":
                    return True

            elif system in ("linux", "darwin"):
                # Common mount points for removable media.
                removable_prefixes = ("/media/", "/mnt/", "/Volumes/")
                if any(cwd.startswith(prefix) for prefix in removable_prefixes):
                    return True

        except Exception:
            pass

        return False