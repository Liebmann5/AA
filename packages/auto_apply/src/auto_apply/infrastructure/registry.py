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
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from auto_apply.domain.models.capability_profile import (
        ResolvedCapabilityProfile,
    )

from auto_apply.adapters.secondary.os.detectors import BrowserDetector, ToolDetector
from auto_apply.adapters.secondary.os.hardware import HardwareInspector
from auto_apply.adapters.secondary.os.platform_inspector import PlatformInspector
from auto_apply.adapters.secondary.persistence.policy_manager import PolicyManager
from auto_apply.domain.config import DB_PATH
from auto_apply.domain.models.policy import AdminPolicy
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.effective_config import EffectiveConfig
from auto_apply.domain.models.resources import RuntimeProfile
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.timing import BehaviorParameters
from auto_apply.domain.models.browser_candidates import (
    DEFAULT_FRAMEWORK_ORDER,
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
    Path(__file__).resolve().parent.parent  # infrastructure/  # auto_apply/
    / "resources"
    / "config"
    / "runtime_defaults.yaml"
)

# ─────────────────────────────────────────────────────────────────────────────
# _RUNTIME_DEFAULTS — populated from YAML; falls back to inline dict if
# pyyaml is not installed or the file is missing/malformed.
# ─────────────────────────────────────────────────────────────────────────────

def _new_session_id() -> str:
    """Mint the one identity for this run.

    Must be a UUID, not a clock reading. ``SessionPlan`` is frozen, so whatever
    is assigned here is permanent for the whole session, and CheckpointManager
    keys checkpoints by it — a collision restores another session's state.

    A wall-clock id collides for any two sessions inside the same second, and
    collides *permanently* on a machine with a dead RTC, which reports the same
    epoch on every boot. Those machines are AA's target hardware, not an edge
    case. uuid4 is also opaque, so it leaks no run time into research exports.
    """
    return str(uuid.uuid4())


_RUNTIME_DEFAULTS_FALLBACK: dict[str, Any] = {
    "headless_mode": False,
    "browser_timeout_seconds": 30,
    "page_load_timeout_seconds": 20,
    "navigation_retries": 3,
    "occlusion_guard": True,
    "force_analysis_tier": "",
    "infinite_scroll_settle_s": 2.0,
    "preferred_browser_order": ["chrome", "firefox", "edge", "safari"],
    "framework_order": ["playwright", "selenium", "camoufox"],
    "max_applications_per_session": 50,
    "max_applications_per_company": 3,
    "cooldown_days_default": 180,
    "max_discovery_results_per_query": 30,
    "task_retry_limit": 3,
    "network_reconnect_timeout_seconds": 300,
    "checkpoint_interval_actions": 5,
    "enable_human_timing": True,
    "enable_fingerprint_spoofing": True,
    "min_action_delay_ms": 500,
    "max_action_delay_ms": 2000,
    "macro_pause_min_s": 1.2,
    "macro_pause_max_s": 2.5,
    "settle_min_s": 0.4,
    "settle_max_s": 0.8,
    "enable_research_collection": False,
    "enable_company_batching": True,
    "company_batch_threshold": 3,
    "discovery_strategy": "live_browser",
    "perception_strategy": "math",
    "store_session_logs": True,
    "log_retention_days": 30,
    "vetting": {
        "hard_skills_min_overlap": 0.5,
        "role_alignment_threshold": 0.6,
        "borderline_band": [0.45, 0.65],
        "filter_weights": {
            "ThrottlingFilter": 0.1,
            "SpatialLocationFilter": 0.15,
            "LogicFilters": 0.15,
            "ExperienceFilter": 0.15,
            "HardSkillsFilter": 0.2,
            "RoleAlignmentFilter": 0.25,
        },
    },
    "discovery": {
        "max_concurrent_sources": 1,
        "max_pages_per_query": 1,
        "between_provider_pause_min": 1.0,
        "between_provider_pause_max": 2.0,
    },
    "applications": {
        "max_pages": 10,
        "max_steps_per_page": 15,
        "dom_stabilization_timeout_s": 3.0,
        "dom_stabilization_poll_interval_s": 0.25,
        "custom_answer_max_tokens": 150,
        "inter_action_delay_ms": 400,
        "macro_pause_min_seconds": 0.4,
        "macro_pause_max_seconds": 1.2,
        "micro_delay_peak_ms": 30,
        "typing_wpm": 80,
        "typing_jitter_fraction": 0.15,
        "thinking_pause_probability": 0.05,
        "thinking_pause_min": 0.2,
        "thinking_pause_max": 0.6,
    },
    "browser": {
        "mouse_move_steps": 4,
        "mouse_offset_min_px": 30,
        "mouse_offset_max_px": 150,
        "mouse_step_delay_min": 0.05,
        "mouse_step_delay_max": 0.2,
    },
    "gpt4all": {
        "model": "Meta-Llama-3-8B-Instruct.Q4_0.gguf",
        "max_tokens": 512,
        "temperature": 0.7,
        "device": "cpu",
    },
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

        # Construct BehaviorParameters from the merged config
        behavior_params = BehaviorParameters.from_config(effective_config)

        # Construct the SessionPlan using the canonical factory
        plan = SessionPlan.from_config(
            session_id=_new_session_id(),
            config=effective_config,
            behavior=behavior_params,
            nlp_tier=effective_config.get("nlp_tier", "basic"),
            browser_framework=effective_config.get("browser_framework", "selenium"),
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

        # Browser preference reconciliation (input -> resolution -> resolved state).
        # The profile carries the user's single pick as a declarative input
        # (preferred_browser); the cascade reads the resolved fallback order
        # (preferred_browser_order). Fold the pick to the FRONT of that order so a
        # user choosing firefox tries firefox first and still falls back through the
        # rest. Without this the pick was a dead-write: written, merged, read by none.
        browser_pick = merged.get("preferred_browser")
        merged.pop("preferred_browser", None)
        if browser_pick and browser_pick != "any":
            order = list(merged.get("preferred_browser_order", []))
            merged["preferred_browser_order"] = [browser_pick] + [
                b for b in order if b != browser_pick
            ]

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
                "min_action_delay_ms": max(merged.get("min_action_delay_ms", 500), 800),
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
        return (
            self._effective_config.get("discovery_strategy", "live_browser")
            != "static_fetch"
        )

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
            tool
            for tool in ("playwright", "selenium", "camoufox")
            if self.is_tool_available(tool)
        ]
        os_browsers = self.get_allowed_browsers()
        native_map = self.get_framework_native_browsers()

        framework_order = self._effective_config.get(
            "framework_order", DEFAULT_FRAMEWORK_ORDER
        )
        candidates = build_filtered_candidates(
            available_frameworks=available_frameworks,
            os_browsers=os_browsers,
            framework_native_map=native_map,
            admin_policy=self._admin_policy,
            framework_order=framework_order,
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

    def get_effective_settings(self) -> EffectiveConfig:
        """Returns the resolved configuration as a typed, frozen object.

        Same data as ``get_all_effective_config``, read through one typed
        name per concept. A missing key raises at construction instead of
        defaulting silently; a consumer migrating onto this cannot misread
        a key the way ``dict.get(key, default)`` allowed.
        """
        return EffectiveConfig.from_mapping(self._effective_config)

    # =========================================================================
    # PROFILE AND POLICY ACCESSORS
    # =========================================================================

    def get_active_profile(self) -> UserProfile:
        """Returns the active user profile."""
        return self._profile

    def get_runtime_profile(self) -> RuntimeProfile:
        """Returns a RuntimeProfile built from detected capabilities.

        The profile reflects hardware‑based resource scaling, capped by the
        session plan's explicitly configured limits so it never contradicts the
        user/admin‑controlled concurrency ceiling.

        NLP tier and AI flags are set by detecting optional tools (SpaCy,
        sentence‑transformers); behaviour‑humanisation and stealth‑driver
        flags are also factored in.
        """
        caps = self._capabilities
        plan = self.get_session_plan()
        config = self._effective_config

        # ── Browser identity ────────────────────────────────────────────────
        browser_name = (
            caps.available_browsers[0] if caps.available_browsers else "chrome"
        )

        # ── Max concurrency ──────────────────────────────────────────────────
        # Hardware‑derived, then capped by the session plan's safety ceiling.
        if caps.is_low_resource:
            hw_concurrency = 1
        else:
            if caps.cpu_cores >= 4:
                # Originally from SessionResourcesManager.negotiate():
                #   concurrency = min(4, int((ram_mb / 1024) / 2))
                hw_concurrency = max(1, min(4, int((caps.ram_mb / 1024.0) / 2.0)))
            else:
                hw_concurrency = 1
        concurrency = min(hw_concurrency, plan.max_concurrency)

        # ── NLP / AI availability ───────────────────────────────────────────
        nlp_engine = "basic"
        ai_enabled = False
        if not caps.is_low_resource:
            if self.is_tool_available("sentence_transformers"):
                nlp_engine = "transformer"
                ai_enabled = True
            elif self.is_tool_available("spacy"):
                nlp_engine = "spacy"
                ai_enabled = True

        # ── Stealth driver eligibility ──────────────────────────────────────
        enable_humanization = bool(config.get("enable_behavior_humanization", True))
        use_stealth_driver = (
            not caps.is_low_resource
            and "undetected_chromedriver" in caps.available_tools
            and enable_humanization
            and browser_name in ("chrome", "chromium")
        )

        return RuntimeProfile(
            browser_name=browser_name,
            browser_framework="unresolved",  # resolved later by BrowserCascade
            headless=bool(config.get("headless_mode", True)),
            use_stealth=bool(config.get("enable_fingerprint_spoofing", True)),
            use_stealth_driver=use_stealth_driver,
            max_concurrency=concurrency,
            ai_enabled=ai_enabled,
            nlp_engine=nlp_engine,
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
    # CAPABILITY PROFILE
    # =========================================================================

    def build_capability_profile(
        self, driver_available: bool
    ) -> "ResolvedCapabilityProfile":
        """Build the frozen capability profile for this session.

        Called once in build_orchestrator() after the driver is (or isn't) created.
        The result is injected into the orchestrator and never changes.

        Args:
            driver_available: Whether a live browser driver was successfully created.

        Returns:
            A frozen ResolvedCapabilityProfile.
        """
        from auto_apply.domain.models.capability_profile import (
            ResolvedCapabilityProfile,
        )

        has_spacy = False
        try:
            import spacy  # noqa: F401

            has_spacy = True
        except ImportError:
            pass

        has_gpt4all = False
        try:
            from gpt4all import GPT4All  # noqa: F401

            has_gpt4all = True
        except ImportError:
            pass

        max_workers = self.get_effective_config("discovery.max_concurrent_sources", 1)
        if not driver_available:
            max_workers = 0  # No browser = no browser-based discovery

        return ResolvedCapabilityProfile(
            has_browser=driver_available,
            browser_framework="selenium" if driver_available else None,
            max_browser_workers=max(1, int(max_workers)),
            has_spacy=has_spacy,
            has_gpt4all=has_gpt4all,
            has_research_consent=self.is_research_enabled(),
            research_signals_active=self.is_research_enabled(),
            is_low_resource=self.is_low_resource_environment(),
            max_applications_per_session=self.get_effective_config(
                "session.max_applications", None
            ),
            max_concurrent_sources=max(
                1, int(self.get_effective_config("discovery.max_concurrent_sources", 1))
            ),
        )

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
