# This class implements the RegistryPort protocol defined in
# auto_apply/domain/ports/registry_port.py.

"""Runtime environment registry — single source of truth for capabilities and config.

This module provides CapabilitiesRegistry: the single authoritative answer to
"what can AA do in the current environment?" Every component that needs to know
"what's available?", "what's allowed?", or "what's configured?" must ask the
registry. Nothing reads config files, OS state, or tool availability directly.

Three-Tier Configuration Hierarchy:
    1. AdminPolicy  (top)    — Set by device owner. OS-auth protected.
                               Overrides everything below it. Immutable
                               during a session once loaded.
    2. UserSettings (middle) — Set by the end user via the GUI/CLI wizard.
                               Overrides RuntimeDefaults. May be constrained
                               by AdminPolicy at load time (PolicyEnforcement).
    3. RuntimeDefaults (bottom) — Hardcoded fallback values. Used when
                               neither admin nor user has specified something.

Browser Selection Contract:
    CapabilitiesRegistry does NOT select browsers — that is BrowserCascade's job.
    The registry answers questions like "is Chrome available?", "is Firefox
    allowed by admin policy?", and "what is the user's preferred order?".
    BrowserCascade consumes those answers to build its ordered fallback list.

Example:
    >>> registry = CapabilitiesRegistry.build(user_profile=profile)
    >>> registry.is_browser_available("chrome")
    True
    >>> registry.get_effective_config("max_applications_per_session")
    100
    >>> plan = registry.get_session_plan()
    >>> plan.max_concurrency
    1
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_apply.adapters.secondary.os.detectors import BrowserDetector, ToolDetector
from auto_apply.adapters.secondary.os.hardware import HardwareInspector
from auto_apply.adapters.secondary.os.platform_inspector import PlatformInspector
from auto_apply.adapters.secondary.persistence.policy_manager import PolicyManager
from auto_apply.domain.config import DB_PATH
from auto_apply.domain.models.policy import AdminPolicy
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.resources import RuntimeProfile
from auto_apply.domain.models.session import SessionPlan
from auto_apply.infrastructure.candidates import (
    AutomationCandidate,
    CANDIDATE_PRIORITY,
    build_filtered_candidates,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Low-resource hardware thresholds
# ─────────────────────────────────────────────────────────────────────────────

_LOW_RESOURCE_MIN_RAM_MB: int = 2048
_LOW_RESOURCE_MIN_CPU_CORES: int = 2
_LOW_RESOURCE_MIN_DISK_MB: int = 512

# Path to the runtime defaults YAML — loaded once at module import.
_DEFAULTS_YAML: Path = (
    Path(__file__).resolve().parent   # infrastructure/
    .parent                            # auto_apply/
    / "resources"
    / "config"
    / "runtime_defaults.yaml"
)

# ─────────────────────────────────────────────────────────────────────────────
# _RUNTIME_DEFAULTS — populated from YAML; falls back to inline dict if
# pyyaml is not installed or the file is missing/malformed.
# ─────────────────────────────────────────────────────────────────────────────

_RUNTIME_DEFAULTS_FALLBACK: dict[str, Any] = {
    "headless_mode": False,
    "browser_timeout_seconds": 30,
    "page_load_timeout_seconds": 20,
    "preferred_browser_order": ["chrome", "firefox", "edge", "safari"],
    "max_applications_per_session": 50,
    "max_applications_per_company": 3,
    "max_discovery_results_per_query": 30,
    "task_retry_limit": 3,
    "network_reconnect_timeout_seconds": 300,
    "checkpoint_interval_actions": 5,
    "enable_human_timing": True,
    "enable_fingerprint_spoofing": True,
    "min_action_delay_ms": 500,
    "max_action_delay_ms": 2000,
    "enable_research_collection": False,
    "enable_company_batching": True,
    "company_batch_threshold": 3,
    "discovery_strategy": "live_browser",
    "perception_strategy": "math",
    "store_session_logs": True,
    "log_retention_days": 30,
}


def _load_runtime_defaults() -> dict[str, Any]:
    """Loads runtime defaults from YAML; returns the inline fallback on any error."""
    try:
        import yaml  # noqa: PLC0415 — optional dep; lazy import intentional
    except ImportError:
        logger.debug("pyyaml not installed — using built-in runtime defaults")
        return dict(_RUNTIME_DEFAULTS_FALLBACK)

    if not _DEFAULTS_YAML.is_file():
        logger.warning(
            "runtime_defaults.yaml not found at %s — using built-in defaults",
            _DEFAULTS_YAML,
        )
        return dict(_RUNTIME_DEFAULTS_FALLBACK)

    try:
        with _DEFAULTS_YAML.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError("top-level value is not a mapping")
        merged = dict(_RUNTIME_DEFAULTS_FALLBACK)
        merged.update(data)
        logger.debug("Loaded runtime defaults from %s", _DEFAULTS_YAML)
        return merged
    except Exception as exc:
        logger.warning(
            "Failed to load runtime_defaults.yaml (%s) — using built-in defaults", exc
        )
        return dict(_RUNTIME_DEFAULTS_FALLBACK)


_RUNTIME_DEFAULTS: dict[str, Any] = _load_runtime_defaults()

# Path to the offline geographic city database used by SpatialLocationFilter.
_GEO_DB_PATH: Path = DB_PATH.parent / "geo" / "cities.db"


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


class CapabilitiesRegistry:
    """Single source of truth for AA's runtime capabilities and configuration.

    All components query the registry rather than reading configs, detecting
    tools, or checking OS state themselves. This enforces the single-source-
    of-truth principle across the entire codebase.

    The registry is read-only after construction. It is built once per session
    by SessionController (via build()) and injected into every component that
    needs it.

    Construction should always use CapabilitiesRegistry.build(), which runs
    all detectors, loads all config tiers, applies PolicyEnforcement, and
    returns a fully resolved instance.
    """

    def __init__(
        self,
        capabilities: EnvironmentCapabilities,
        admin_policy: AdminPolicy | None,
        user_profile: UserProfile,
        effective_config: dict[str, Any],
        session_plan: SessionPlan,
    ) -> None:
        self._capabilities = capabilities
        self._admin_policy = admin_policy
        self._profile = user_profile
        self._effective_config = effective_config
        self._plan = session_plan

        logger.info(
            "CapabilitiesRegistry initialized | os=%s browsers=%s low_resource=%s",
            capabilities.os_name,
            capabilities.available_browsers,
            capabilities.is_low_resource,
        )

    # =========================================================================
    # CONSTRUCTION
    # =========================================================================

    @classmethod
    def build(
        cls,
        user_profile: "UserProfile",
    ) -> "CapabilitiesRegistry":
        """Builds a fully initialized registry for the current environment.

        This is the single correct way to create a CapabilitiesRegistry.
        It performs, in order:
            1. OS and hardware detection
            2. Browser and tool detection
            3. Low-resource override calculation
            4. AdminPolicy loading (if configured)
            5. Three-tier config merging (defaults → user → admin → hardware)
            6. PolicyEnforcement (reconciles user vs admin settings)
            7. Constructs a frozen SessionPlan from the resolved config.

        IMPORTANT: The UserProfile is injected, not loaded. Profile loading
        is the responsibility of the caller (e.g., SessionController or the
        ProfileRepository). The registry never performs file I/O for profile
        data.

        Args:
            user_profile: A pre-loaded, Pydantic-validated UserProfile.

        Returns:
            A fully initialized, read-only CapabilitiesRegistry.
        """
        logger.info("Building CapabilitiesRegistry...")

        hw = HardwareInspector.inspect()
        plat = PlatformInspector.inspect()

        available_browsers = BrowserDetector.detect_installed_browsers()
        available_tools = ToolDetector.detect_optional_tools()

        is_low_resource = (
            hw.ram_mb < _LOW_RESOURCE_MIN_RAM_MB
            or hw.cpu_cores < _LOW_RESOURCE_MIN_CPU_CORES
            or hw.disk_free_mb < _LOW_RESOURCE_MIN_DISK_MB
        )

        capabilities = EnvironmentCapabilities(
            available_browsers=available_browsers,
            available_tools=available_tools,
            os_name=plat.os_name,
            os_version=plat.os_version,
            cpu_cores=hw.cpu_cores,
            ram_mb=hw.ram_mb,
            disk_free_mb=hw.disk_free_mb,
            is_low_resource=is_low_resource,
        )

        if is_low_resource:
            logger.warning(
                "Low-resource environment detected | ram_mb=%d cpu_cores=%d — "
                "applying conservative config overrides",
                hw.ram_mb,
                hw.cpu_cores,
            )

        admin_policy: AdminPolicy | None = PolicyManager.load_admin_policy()

        effective_config = cls._merge_config(
            runtime_defaults=_RUNTIME_DEFAULTS,
            user_settings=(
                user_profile.settings
                if hasattr(user_profile, "settings")
                else getattr(user_profile.app_config, "__dict__", {})
            ),
            admin_policy=admin_policy,
            is_low_resource=is_low_resource,
        )

        # Construct the SessionPlan
        discovery_cfg = effective_config.get("discovery", {})
        applications_cfg = effective_config.get("applications", {})
        session_cfg = effective_config.get("session", {})
        providers_list = discovery_cfg.get("providers", ["google", "bing", "indeed"])
        linear_mode_platforms = set(effective_config.get("linear_mode_platforms", []))

        plan = SessionPlan(
            session_id="unset",  # will be overwritten by the orchestrator
            max_concurrency=discovery_cfg.get("max_concurrent_sources", 1),
            max_results_per_query=effective_config.get("max_discovery_results_per_query", 30),
            max_applications_per_session=applications_cfg.get("max_applications_per_session", 50),
            max_applications_per_company=applications_cfg.get("max_applications_per_company", 3),
            max_queries_per_session=discovery_cfg.get("max_queries_per_session", 20),
            enable_company_page_mining=discovery_cfg.get("enable_company_page_mining", False),
            use_ats_site_search=discovery_cfg.get("use_ats_site_search", False),
            date_range=effective_config.get("date_range"),
            providers=providers_list,
            linear_mode_platforms=linear_mode_platforms,
            research_enabled=effective_config.get("enable_research_collection", False),
            random_seed=session_cfg.get("random_seed"),
            nlp_tier=effective_config.get("nlp_tier", "basic"),
            browser_framework=effective_config.get("browser_framework", "selenium"),
            headless=effective_config.get("headless_mode", True),
            stealth_mode=effective_config.get("stealth_mode", True),
            has_live_browser=effective_config.get("discovery_strategy", "live_browser") != "static_fetch",
        )

        registry = cls(
            capabilities=capabilities,
            admin_policy=admin_policy,
            user_profile=user_profile,
            effective_config=effective_config,
            session_plan=plan,
        )

        from auto_apply.adapters.secondary.security.policy_enforcement import (  # noqa: PLC0415
            PolicyEnforcement,
        )
        PolicyEnforcement(registry).enforce()

        logger.info(
            "CapabilitiesRegistry build complete | profile=%s",
            getattr(user_profile, "profile_name", "unknown"),
        )
        return registry

    @staticmethod
    def _merge_config(
        runtime_defaults: dict[str, Any],
        user_settings: dict[str, Any],
        admin_policy: AdminPolicy | None,
        is_low_resource: bool,
    ) -> dict[str, Any]:
        """Merges the three config tiers into a single resolved dict.

        Merge order (later overrides earlier):
            RuntimeDefaults → UserSettings → AdminPolicy → LowResourceOverrides
        """
        merged = dict(runtime_defaults)
        merged.update(user_settings)

        if admin_policy:
            for key, value in admin_policy.config_overrides.items():
                merged[key] = value
                logger.debug("Admin policy override | key=%s value=%s", key, value)

        if is_low_resource:
            low_resource_overrides = {
                "max_applications_per_session": min(
                    merged.get("max_applications_per_session", 50), 25
                ),
                "max_discovery_results_per_query": min(
                    merged.get("max_discovery_results_per_query", 30), 15
                ),
                "min_action_delay_ms": max(
                    merged.get("min_action_delay_ms", 500), 800
                ),
                "discovery_strategy": "static_fetch",
                "enable_fingerprint_spoofing": False,
            }
            merged.update(low_resource_overrides)

        return merged

    # =========================================================================
    # BROWSER CAPABILITY QUERIES
    # =========================================================================

    def get_allowed_browsers(self) -> list[str]:
        """Returns the list of browsers allowed in the current environment."""
        available = set(self._capabilities.available_browsers)

        if self._admin_policy and self._admin_policy.allowed_browsers:
            allowed_by_policy = set(self._admin_policy.allowed_browsers)
            available = available.intersection(allowed_by_policy)

        preferred_order: list[str] = self._effective_config.get(
            "preferred_browser_order", []
        )
        ordered = [b for b in preferred_order if b in available]
        ordered += [b for b in sorted(available) if b not in ordered]
        return ordered

    def is_browser_available(self, browser_name: str) -> bool:
        """Returns True if the named browser is installed and policy-allowed."""
        return browser_name.lower() in self.get_allowed_browsers()

    def is_tool_available(self, tool_name: str) -> bool:
        """Returns True if an optional tool is installed and policy-allowed."""
        if tool_name not in self._capabilities.available_tools:
            return False

        if self._admin_policy and self._admin_policy.blocked_tools:
            if tool_name in self._admin_policy.blocked_tools:
                return False

        return True

    def discovery_requires_live_browser(self) -> bool:
        """Returns True if the active discovery strategy requires a live browser."""
        strategy = self._effective_config.get("discovery_strategy", "live_browser")
        return strategy != "static_fetch"

    # =========================================================================
    # NEW: FRAMEWORK NATIVE BROWSERS MAP
    # =========================================================================

    def get_framework_native_browsers(self) -> dict[str, list[str]]:
        """Returns a mapping of framework -> list of browsers it bundles internally.

        Selenium bundles no browsers, so its list is always empty.
        """
        return {
            "playwright": ["chromium", "firefox", "webkit"],
            "camoufox": ["firefox"],
            "selenium": [],
        }

    # =========================================================================
    # NEW: VIABLE CANDIDATES FOR BROWSER CASCADE
    # =========================================================================

    def get_viable_candidates(self) -> list[dict[str, str]]:
        """Returns the ordered list of viable automation candidates.

        Each candidate is a dict with keys:
            framework   - automation framework name
            browser_type - browser identifier (e.g. "chromium", "chrome")
            source       - "bundled", "os", or "none"

        The ordering is defined by a hardcoded priority; only candidates whose
        framework is installed and whose browser is not blocked are returned.
        The "static" fallback is always included as the last resort.
        """
        available_frameworks = [
            tool for tool in ("playwright", "selenium", "camoufox")
            if self.is_tool_available(tool)
        ]
        os_browsers = self.get_allowed_browsers()
        native_map = self.get_framework_native_browsers()

        candidates = build_filtered_candidates(
            available_frameworks=available_frameworks,
            os_browsers=os_browsers,
            framework_native_map=native_map,
            admin_policy=self._admin_policy,
        )
        return [
            {
                "framework": c.framework,
                "browser_type": c.browser_type,
                "source": c.source,
            }
            for c in candidates
        ]

    # =========================================================================
    # CONFIGURATION QUERIES
    # =========================================================================

    def get_effective_config(self, key: str, default: Any = None) -> Any:
        """Returns the resolved effective value for a configuration key."""
        return self._effective_config.get(key, default)

    def get_all_effective_config(self) -> dict[str, Any]:
        """Returns a copy of the full resolved configuration dict."""
        return dict(self._effective_config)

    # =========================================================================
    # PROFILE AND POLICY ACCESSORS
    # =========================================================================

    def get_active_profile(self) -> UserProfile:
        """Returns the active user profile."""
        return self._profile

    def get_runtime_profile(self) -> RuntimeProfile:
        """Returns a RuntimeProfile built from the detected capabilities."""
        browsers = self._capabilities.available_browsers
        browser_name = browsers[0] if browsers else "chrome"
        # Framework selection is now handled by BrowserCascade.
        browser_framework: str = "unresolved"
        return RuntimeProfile(
            browser_name=browser_name,
            browser_framework=browser_framework,
            headless=bool(self._effective_config.get("headless_mode", True)),
            use_stealth=bool(
                self._effective_config.get("enable_fingerprint_spoofing", True)
            ),
            use_stealth_driver=(
                "undetected_chromedriver" in self._capabilities.available_tools
            ),
            max_concurrency=1 if self._capabilities.is_low_resource else 2,
            ai_enabled=False,
            nlp_engine="basic",
        )

    def get_admin_policy(self) -> AdminPolicy | None:
        """Returns the active AdminPolicy, or None if none is configured."""
        return self._admin_policy

    def has_admin_policy(self) -> bool:
        """Returns True if an admin policy is active for this environment."""
        return self._admin_policy is not None

    # =========================================================================
    # ENVIRONMENT INFORMATION
    # =========================================================================

    def get_environment_capabilities(self) -> EnvironmentCapabilities:
        """Returns the detected environment capabilities snapshot."""
        return self._capabilities

    def is_low_resource_environment(self) -> bool:
        """Returns True if the host hardware is below the recommended minimum."""
        return self._capabilities.is_low_resource

    def get_os_name(self) -> str:
        """Returns the normalized OS name: "windows", "macos", "linux", or "unknown"."""
        return self._capabilities.os_name

    # =========================================================================
    # FEATURE FLAGS
    # =========================================================================

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Returns True if a named feature flag is enabled."""
        key = (
            feature_name
            if feature_name.startswith("enable_")
            else f"enable_{feature_name}"
        )
        return bool(self._effective_config.get(key, False))

    def is_research_enabled(self) -> bool:
        """Returns True if the user has opted into research data collection."""
        return self.is_feature_enabled("research_collection")

    # =========================================================================
    # SESSION PLAN ACCESSOR
    # =========================================================================

    def get_session_plan(self) -> SessionPlan:
        """Returns the frozen SessionPlan for the current session."""
        return self._plan

    # =========================================================================
    # REPR
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"CapabilitiesRegistry("
            f"os={self._capabilities.os_name}, "
            f"browsers={self._capabilities.available_browsers}, "
            f"low_resource={self._capabilities.is_low_resource}, "
            f"admin_policy={'yes' if self._admin_policy else 'no'}"
            f")"
        )