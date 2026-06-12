"""Negotiates the best resource strategy based on hardware and availability.

This module acts as the 'Resource Negotiator'. It queries the CapabilitiesRegistry
(injected via constructor) to produce a RuntimeProfile. It ensures the application
never attempts to run heavy AI models on a potato PC.
"""
# Layer: application
# Depends on: domain

import logging
from typing import TYPE_CHECKING

from auto_apply.domain.models.profile import ApplicationConfig
from auto_apply.domain.models.resources import RuntimeProfile

if TYPE_CHECKING:
    from auto_apply.infrastructure.composition_root import CapabilitiesRegistry

logger = logging.getLogger(__name__)


class SessionResourcesManager:
    """Determines the optimal resource allocation for a session."""

    def __init__(self, app_config: ApplicationConfig, registry: "CapabilitiesRegistry"):
        """Initializes the manager with the user's configuration and capabilities.

        Args:
            app_config: The user's runtime settings.
            registry: Pre-built capabilities registry for the current environment.
        """
        self.app_config = app_config
        self._registry = registry

    def negotiate(self) -> RuntimeProfile:
        """Calculates the best execution strategy.

        Returns:
            RuntimeProfile: The blueprint for the Session.
        """
        caps = self._registry.get_environment_capabilities()
        is_low_spec = caps.is_low_resource

        if is_low_spec:
            logger.info("Low-resource environment detected. Enforcing efficiency mode.")

        framework, browser_name = self._resolve_browser_strategy()

        concurrency = 1
        if not is_low_spec and caps.cpu_cores >= 4:
            concurrency = min(4, int((caps.ram_mb / 1024) / 2))

        nlp_engine = "basic"
        ai_enabled = False

        if not is_low_spec:
            if self._registry.is_tool_available("sentence_transformers"):
                nlp_engine = "transformer"
                ai_enabled = True
            elif self._registry.is_tool_available("spacy"):
                nlp_engine = "spacy"
                ai_enabled = True

        use_stealth_driver = (
            not is_low_spec
            and self._registry.is_tool_available("undetected_chromedriver")
            and self.app_config.enable_behavior_humanization
            and browser_name in ["chrome", "chromium"]
        )

        manifest = RuntimeProfile(
            browser_framework=framework,
            browser_name=browser_name,
            headless=self.app_config.run_headless,
            use_stealth=self.app_config.enable_behavior_humanization,
            use_stealth_driver=use_stealth_driver,
            max_concurrency=concurrency,
            ai_enabled=ai_enabled,
            nlp_engine=nlp_engine,
        )

        logger.info("Resource Negotiation Complete: %s", manifest)
        return manifest

    def _resolve_browser_strategy(self) -> tuple[str, str]:
        """Decides which framework and browser to use based on availability."""
        pref = self.app_config.preferred_browser.lower()

        if pref != "any":
            if self._registry.is_tool_available("playwright") and pref in [
                "chromium",
                "firefox",
                "webkit",
            ]:
                return "playwright", pref
            return "selenium", pref

        if self._registry.is_tool_available("playwright"):
            return "playwright", "chromium"

        allowed = self._registry.get_allowed_browsers()
        for preferred in ["chrome", "firefox", "edge"]:
            if preferred in allowed:
                return "selenium", preferred

        return "selenium", "chrome"
