"""DriverRegistry — typed registry for DriverProvider instances.

Providers are registered once at startup (during composition_root wiring) and
then read-only for the rest of the session.  This write-at-startup /
read-at-runtime pattern is inherently thread-safe: no locking is required
because no mutations occur after the initial registration pass.

Usage::

    registry = DriverRegistry()
    registry.register(SeleniumProvider())
    registry.register(PlaywrightProvider())

    provider = registry.get("selenium")   # → SeleniumProvider or None
"""

import logging

from auto_apply.infrastructure.providers.base import DriverProvider

logger = logging.getLogger(__name__)


class DriverRegistry:
    """Registry that maps provider names to registered DriverProvider instances."""

    def __init__(self) -> None:
        self._providers: list[DriverProvider] = []

    def register(self, provider: DriverProvider) -> None:
        """Register a provider.

        If the provider reports itself as unavailable (e.g. the framework
        package is not installed), registration is skipped with a logged
        warning rather than raising an exception — this ensures AA starts
        even when optional frameworks are absent.

        Args:
            provider: A DriverProvider implementation to register.
        """
        if not provider.available:
            logger.warning(
                "DriverRegistry: provider %r not available — skipping registration",
                provider.name,
            )
            return
        self._providers.append(provider)
        logger.info("DriverRegistry: registered provider %r", provider.name)

    def get_providers(self) -> list[DriverProvider]:
        """Return a copy of all registered providers in registration order."""
        return list(self._providers)

    def get_providers_for_browser(self, browser_type: str) -> list[DriverProvider]:
        """Return all providers that support *browser_type*.

        Args:
            browser_type: Lowercase browser identifier (e.g. 'chrome', 'chromium').

        Returns:
            Providers whose supports(browser_type) returns True, in
            registration order.
        """
        return [p for p in self._providers if p.supports(browser_type)]

    def get(self, name: str) -> DriverProvider | None:
        """Return the first registered provider whose .name matches *name*.

        Args:
            name: Canonical framework name (e.g. 'selenium', 'playwright').

        Returns:
            The matching DriverProvider, or None if not registered.
        """
        return next((p for p in self._providers if p.name == name), None)
