"""What the host machine can actually do, as detected at startup.

Moved here from ``infrastructure.registry`` so that ``RegistryPort`` can
name it. ``PolicyEnforcement`` needs this snapshot in order to purge
admin-blocked tools from it, and was reaching into the concrete registry's
private ``_capabilities`` attribute to get it. Putting the accessor on the
port required the type to be visible from the domain.

It belongs here on its own merits: it is detected hardware and OS facts
with no infrastructure behaviour attached — the same kind of thing as
``RuntimeProfile`` next door. ``infrastructure.registry`` re-exports it, so
existing importers are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EnvironmentCapabilities:
    """A snapshot of what AA can do in the current runtime environment.

    This is computed once during CapabilitiesRegistry.build() and cached.
    It represents detected (not configured) capabilities — what the hardware
    and OS actually support, independent of any policy or preference.

    Attributes:
        available_browsers: Browser names detected as installed and launchable.
        available_tools: Optional tool names (e.g., "undetected_chromedriver").
        os_name: Normalized OS name: "windows", "macos", or "linux".
        os_version: OS version string as reported by the platform module.
        cpu_cores: Number of logical CPU cores available.
        ram_mb: Total available RAM in megabytes.
        disk_free_mb: Free disk space in megabytes.
        is_low_resource: True if hardware is below the recommended minimum.
            When True, the registry automatically applies conservative config
            overrides to protect session stability.
    """

    available_browsers: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    os_name: str = "unknown"
    os_version: str = "unknown"
    cpu_cores: int = 1
    ram_mb: int = 512
    disk_free_mb: int = 1024
    is_low_resource: bool = False
