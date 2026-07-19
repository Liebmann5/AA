"""Inspects host hardware resources for runtime optimization.

This module provides HardwareInspector, which queries CPU, RAM, and disk
availability to help AA decide how aggressively it can operate. The results
are consumed by CapabilitiesRegistry during the boot sequence.

Graceful Degradation:
    psutil is an optional dependency. If it is not installed, the inspector
    falls back to os.cpu_count() and conservative RAM/disk estimates. AA
    will run in low-resource mode but will not crash.

    This is critical for the worst-case user scenario: a library computer
    where pip install may not have included psutil, or a flash drive
    deployment where the Python environment is minimal.

Example:
    >>> from auto_apply.adapters.secondary.os.hardware import HardwareInfoInspector
    >>>
    >>> hw = HardwareInspector.inspect()
    >>> print(hw.ram_mb, hw.cpu_cores, hw.disk_free_mb)
    8192 4 51200
    >>> print(hw.is_low_resource)
    False
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class HardwareSnapshot:
    """A point-in-time snapshot of host hardware resources.

    All values are set once during boot. They do not update dynamically
    during a session — hardware doesn't change while AA is running.

    Attributes:
        cpu_cores: Number of logical CPU cores (os.cpu_count fallback: 1).
        ram_mb: Total physical RAM in megabytes. 0 if detection failed.
        disk_free_mb: Free disk space in megabytes at the storage root.
            0 if detection failed.
    """
    cpu_cores: int = 1
    ram_mb: int = 0
    disk_free_mb: int = 0


class HardwareInspector:
    """Queries host hardware capabilities for the CapabilitiesRegistry.

    All methods are classmethods — no instance state is needed.

    The inspector tries psutil first for accurate readings. If psutil
    is not available, it falls back to os.cpu_count() and conservative
    defaults. RAM and disk default to 0, which causes the registry to
    treat the environment as low-resource (safe conservative behavior).
    """

    @classmethod
    def inspect(cls) -> HardwareSnapshot:
        """Performs a full hardware inspection.

        Returns:
            A HardwareSnapshot with detected values. Values that could
            not be determined are left at their defaults (cpu=1, ram=0,
            disk=0), which triggers low-resource mode in the registry.
        """
        snapshot = HardwareSnapshot(
            cpu_cores=cls._detect_cpu_cores(),
            ram_mb=cls._detect_ram_mb(),
            disk_free_mb=cls._detect_disk_free_mb(),
        )

        logger.info(
            "Hardware inspection | cpu_cores=%d ram_mb=%d disk_free_mb=%d",
            snapshot.cpu_cores,
            snapshot.ram_mb,
            snapshot.disk_free_mb,
        )

        return snapshot

    @classmethod
    def _detect_cpu_cores(cls) -> int:
        """Detects the number of logical CPU cores.

        Returns:
            CPU core count, minimum 1.
        """
        return os.cpu_count() or 1

    @classmethod
    def _detect_ram_mb(cls) -> int:
        """Detects total physical RAM in megabytes.

        Uses psutil if available. Falls back to 0 (triggers low-resource
        mode in the registry, which is the safe default).

        Returns:
            RAM in megabytes, or 0 if detection failed.
        """
        try:
            import psutil  # noqa: PLC0415
            mem = psutil.virtual_memory()
            ram_mb = int(mem.total / (1024 * 1024))
            return ram_mb
        except ImportError:
            logger.debug(
                "psutil not installed — RAM detection unavailable. "
                "Install psutil for accurate hardware detection."
            )
            return 0
        except Exception as exc:
            logger.warning("RAM detection failed: %s", exc)
            return 0

    @classmethod
    def _detect_disk_free_mb(cls) -> int:
        """Detects free disk space at the user's home directory.

        Uses shutil.disk_usage() which is available on all platforms
        without psutil.

        Returns:
            Free disk space in megabytes, or 0 if detection failed.
        """
        try:
            import shutil  # noqa: PLC0415
            usage = shutil.disk_usage(os.path.expanduser("~"))
            free_mb = int(usage.free / (1024 * 1024))
            return free_mb
        except Exception as exc:
            logger.warning("Disk space detection failed: %s", exc)
            return 0