"""DriverProvider protocol — the contract every browser driver factory must satisfy.

Every concrete provider (SeleniumProvider, PlaywrightProvider, …) must implement
this protocol.  DriverRegistry uses it to type-check registrations at runtime.

Design notes:
    cleanup() is REQUIRED (not optional with a no-op default).  If create()
    succeeds but adapter wrapping fails, BrowserCascade must call cleanup() on
    the raw driver to release the browser process.  A silently absent cleanup
    would leak that process.

    Providers are checked for availability at registration time
    (DriverRegistry.register skips unavailable providers).  The available
    property must therefore be stable and side-effect-free.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DriverProvider(Protocol):
    """Contract for objects that can create and destroy a single browser driver type."""

    @property
    def name(self) -> str:
        """Canonical framework identifier (e.g. 'selenium', 'playwright')."""
        ...

    @property
    def available(self) -> bool:
        """True if the underlying framework package is importable on this machine."""
        ...

    def supports(self, browser_type: str) -> bool:
        """Return True if this provider can drive *browser_type*.

        Args:
            browser_type: Lowercase browser identifier (e.g. 'chrome', 'chromium').

        Returns:
            True when the provider knows how to launch that browser.
        """
        ...

    def create(self, config: dict) -> Any:
        """Launch a browser and return the raw driver object.

        The caller owns the returned driver.  On success the caller is
        responsible for eventually calling cleanup() or passing the driver to
        an adapter whose close() performs equivalent teardown.

        Args:
            config: Launch parameters.  Expected keys vary by provider; each
                provider's docstring lists the keys it recognises.

        Returns:
            A raw driver object (e.g. selenium WebDriver, playwright Page).

        Raises:
            RuntimeError: If the browser cannot be launched.
        """
        ...

    def cleanup(self, driver: Any) -> None:
        """Release all OS and network resources held by *driver*.

        Must succeed silently even if the driver is already dead.  Called by
        BrowserCascade when create() succeeded but a subsequent step (adapter
        wrapping, health check) failed.

        Args:
            driver: The raw driver object previously returned by create().
        """
        ...
