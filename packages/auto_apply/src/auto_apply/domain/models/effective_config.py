"""Typed, frozen snapshot of the fully-resolved effective configuration.

Why this exists
---------------
Three writers (runtime_defaults.yaml, the user's ApplicationConfig, admin
policy) and a low-resource clamp are merged into one flat ``dict`` at startup.
Historically every consumer read that dict with ``dict.get(key, default)`` — and
``SessionPlan.from_config`` / ``BehaviorParameters.from_config`` read a *nested*
shape the YAML never had, so every lookup missed and returned the hardcoded
default, silently, forever.

This object is the single typed reading of that merged dict. Fields are required
and typed: a missing key raises at construction instead of defaulting three
years later, and a renamed field fails at import instead of returning a stale
default. It is ``frozen`` so the resolved configuration is computed once and can
be shared across threads without locks or races.

Nothing is coerced to a safe-looking default here. If the merged config cannot
populate every field, construction fails loudly — which is the point.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class VettingSettings(_Frozen):
    hard_skills_min_overlap: float
    role_alignment_threshold: float
    borderline_band: list[float]
    filter_weights: dict[str, float]


class DiscoverySettings(_Frozen):
    max_concurrent_sources: int
    max_pages_per_query: int
    between_provider_pause_min: float
    between_provider_pause_max: float


class ApplicationTimingSettings(_Frozen):
    max_pages: int
    max_steps_per_page: int
    dom_stabilization_timeout_s: float
    custom_answer_max_tokens: int
    inter_action_delay_ms: int
    macro_pause_min_seconds: float
    macro_pause_max_seconds: float
    micro_delay_peak_ms: int
    typing_wpm: int
    typing_jitter_fraction: float
    thinking_pause_probability: float
    thinking_pause_min: float
    thinking_pause_max: float


class BrowserMotionSettings(_Frozen):
    mouse_move_steps: int
    mouse_offset_min_px: int
    mouse_offset_max_px: int
    mouse_step_delay_min: float
    mouse_step_delay_max: float


class Gpt4AllSettings(_Frozen):
    model: str
    max_tokens: int
    temperature: float
    device: str


class EffectiveConfig(_Frozen):
    # ── 26 flat top-level knobs ──────────────────────────────────────────────
    headless_mode: bool
    browser_timeout_seconds: int
    page_load_timeout_seconds: int
    navigation_retries: int
    preferred_browser_order: list[str]
    max_applications_per_session: int
    max_applications_per_company: int
    cooldown_days_default: int
    max_discovery_results_per_query: int
    task_retry_limit: int
    network_reconnect_timeout_seconds: int
    checkpoint_interval_actions: int
    enable_human_timing: bool
    enable_fingerprint_spoofing: bool
    min_action_delay_ms: int
    max_action_delay_ms: int
    macro_pause_min_s: float
    macro_pause_max_s: float
    settle_min_s: float
    settle_max_s: float
    enable_research_collection: bool
    enable_company_batching: bool
    company_batch_threshold: int
    discovery_strategy: str
    perception_strategy: str
    store_session_logs: bool
    log_retention_days: int
    # ── 5 typed nested sections ──────────────────────────────────────────────
    vetting: VettingSettings
    discovery: DiscoverySettings
    applications: ApplicationTimingSettings
    browser: BrowserMotionSettings
    gpt4all: Gpt4AllSettings

    @classmethod
    def from_mapping(cls, merged: dict) -> "EffectiveConfig":
        """Build from the merged effective_config dict.

        Extra keys (profile fields merged via ``app_config.__dict__``, admin
        overrides) are ignored. Missing required keys raise ``ValidationError``.
        """
        return cls(**merged)
