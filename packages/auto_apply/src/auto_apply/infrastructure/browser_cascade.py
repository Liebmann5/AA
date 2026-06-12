"""Ordered fallback browser selection for reliable session initialization.

This module provides BrowserCascade, which is the single place responsible
for deciding which browser to use and recovering from browser failures by
trying the next available option.

Separation of Responsibilities:
    BrowserCascade       — decides WHICH browser to use (selection + fallback)
    DriverProvider       — decides HOW to construct a given browser (instantiation)
    CapabilitiesRegistry — provides WHAT is available and allowed (authority)

Cascade Behavior:
    On acquire_driver(), BrowserCascade iterates each candidate from
    CapabilitiesRegistry.get_viable_candidates(). For each candidate it:
        1. Looks up the provider via DriverRegistry.get(framework)
        2. Calls provider.create(config) to get a raw driver
        3. Wraps the raw driver using the adapter_map callable
        4. Wraps the adapter in ResilientDriver and returns it

    If create() succeeds but a subsequent step fails, provider.cleanup() is
    called on the raw driver before moving to the next candidate — no leaks.

    If all candidates fail, returns None.  The orchestrator treats None as a
    terminal error and publishes BROWSER_CASCADE_EXHAUSTED before aborting.

Mid-Session Switching:
    BrowserCascade does NOT support mid-session browser switching. This is
    intentional. Browser session state (cookies, authenticated sessions,
    current page context) cannot be reliably transferred between drivers.
    The cascade runs at session startup only. If a browser dies mid-session,
    the ResilientDriver handles recovery within the same driver type. If
    even that fails, the orchestrator tears down and calls acquire_driver()
    again for the next task, which will cascade from the top.

Thread Safety:
    acquire_driver() is not thread-safe by design. It is called only from
    the orchestrator's main loop, never from a concurrent thread.
"""

import logging
from typing import Any, Callable

from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.infrastructure.driver_registry import DriverRegistry
from auto_apply.infrastructure.registry import CapabilitiesRegistry
from auto_apply.infrastructure.resilient_driver import ResilientDriver

logger = logging.getLogger(__name__)


class BrowserCascade:
    """Selects and initializes a browser using an ordered fallback strategy.

    Queries CapabilitiesRegistry for the ordered list of viable candidates,
    then attempts each one using the registered DriverProvider + adapter_map
    until one succeeds or all fail.

    Args:
        registry:        The active CapabilitiesRegistry.
        driver_registry: Registry of available DriverProvider instances.
        adapter_map:     Maps framework name to a callable that wraps a raw
                         driver in the corresponding BrowserInterface adapter.
    """

    def __init__(
        self,
        registry: CapabilitiesRegistry,
        driver_registry: DriverRegistry,
        adapter_map: dict[str, Callable[[Any], BrowserInterface]],
    ) -> None:
        self._registry = registry
        self._driver_registry = driver_registry
        self._adapter_map = adapter_map
        self._attempt_log: list[tuple] = []

    # =========================================================================
    # PRIMARY INTERFACE
    # =========================================================================

    def acquire_driver(self) -> ResilientDriver | None:
        """Acquire a working browser driver using the ordered fallback cascade.

        Iterates through the viable candidates and attempts to initialize each.
        Returns the first successful ResilientDriver.

        If all options fail, returns None and logs the full attempt history
        so the caller can publish an appropriate event and inform the user
        which browsers were tried and why each failed.

        Returns:
            A ready-to-use ResilientDriver, or None if all options failed.
        """
        candidates = self._registry.get_viable_candidates()

        if not candidates:
            logger.error(
                "BrowserCascade: no candidates available. "
                "Check that at least one supported browser or framework is installed "
                "and not blocked by admin policy."
            )
            return None

        logger.info(
            "BrowserCascade starting | candidates=%s",
            [(c["framework"], c["browser_type"], c["source"]) for c in candidates],
        )

        for candidate in candidates:
            driver = self._attempt_browser(candidate)
            if driver is not None:
                logger.info(
                    "BrowserCascade: acquired driver | framework=%s browser=%s",
                    candidate["framework"],
                    candidate["browser_type"],
                )
                return driver

        attempted = [entry[0] for entry in self._attempt_log]
        logger.error("BrowserCascade exhausted | tried=%s", attempted)
        self._log_failure_summary()
        return None

    def get_attempt_log(self) -> list[tuple]:
        """Return the full attempt history for this cascade instance.

        Each entry is a (browser_name, succeeded: bool, error: str | None) tuple.
        Used by the orchestrator to build the BROWSER_CASCADE_EXHAUSTED payload.
        """
        return list(self._attempt_log)

    # =========================================================================
    # INTERNAL ATTEMPT LOGIC
    # =========================================================================

    def _attempt_browser(self, candidate: dict) -> ResilientDriver | None:
        """Attempt to initialize one candidate and wrap it in ResilientDriver.

        Ownership protocol:
            - provider.create() → raw_driver  (cascade owns raw_driver)
            - adapter_factory(raw_driver) → adapter
            - ResilientDriver(adapter)     (ResilientDriver takes ownership)
            If any step after create() raises, provider.cleanup(raw_driver) is
            called before returning None so no browser process is leaked.

        Args:
            candidate: Dict with keys "framework", "browser_type", "source".

        Returns:
            A ResilientDriver on success, or None on any failure.
        """
        framework = candidate["framework"]
        browser = candidate["browser_type"]
        source = candidate["source"]

        if framework == "static":
            logger.info("BrowserCascade: static candidate — no browser driver will be used")
            self._attempt_log.append(("static", False, "Static fallback"))
            return None

        provider = self._driver_registry.get(framework)
        if provider is None:
            msg = f"No registered provider for framework={framework!r}"
            logger.warning("BrowserCascade: %s — skipping", msg)
            self._attempt_log.append((browser, False, msg))
            return None

        adapter_factory = self._adapter_map.get(framework)
        if adapter_factory is None:
            msg = f"No adapter registered for framework={framework!r}"
            logger.warning("BrowserCascade: %s — skipping", msg)
            self._attempt_log.append((browser, False, msg))
            return None

        logger.info(
            "BrowserCascade: trying candidate | framework=%s browser=%s source=%s",
            framework, browser, source,
        )

        raw_driver = None
        try:
            config = self._build_config(browser)
            raw_driver = provider.create(config)
            adapter = adapter_factory(raw_driver)
            resilient = ResilientDriver(adapter)
            self._attempt_log.append((browser, True, None))
            return resilient

        except Exception as exc:
            if raw_driver is not None:
                provider.cleanup(raw_driver)
            error_msg = str(exc)
            self._attempt_log.append((browser, False, error_msg))
            logger.warning(
                "BrowserCascade: candidate failed | framework=%s browser=%s "
                "source=%s error=%s",
                framework, browser, source, error_msg,
            )
            return None

    def _build_config(self, browser_type: str) -> dict:
        """Assemble the provider config dict from the active profile and resources."""
        profile = self._registry.get_active_profile()
        resources = self._registry.get_runtime_profile()
        app_config = getattr(profile, "app_config", None)
        return {
            "browser_type": browser_type,
            "headless": resources.headless,
            "use_undetected_chromedriver": resources.use_stealth_driver,
            "proxy": getattr(app_config, "proxy_server", None),
            "width": 1920,
            "height": 1080,
            "rotate_user_agent": bool(getattr(app_config, "rotate_user_agent", False)),
            "user_agent": getattr(app_config, "user_agent", None),
        }

    def _log_failure_summary(self) -> None:
        """Log a formatted summary of all failed attempts for diagnostics."""
        logger.error("=" * 60)
        logger.error("BrowserCascade: ALL BROWSERS FAILED")
        logger.error("Attempt summary:")
        for browser_name, succeeded, error in self._attempt_log:
            status = "OK" if succeeded else "FAILED"
            logger.error("  [%s] %s — %s", status, browser_name, error or "")
        logger.error(
            "Troubleshooting: ensure at least one of the following is "
            "installed: Chrome, Firefox, Edge, or Safari (macOS only). "
            "If an admin policy is active, check which browsers it permits."
        )
        logger.error("=" * 60)
