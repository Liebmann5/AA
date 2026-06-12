"""Immutable Pydantic models for session timing and behavior parameters.

Centralizes all human-behavior simulation and navigation timing parameters.
Used by BehaviorSimulator and the HumanLikeAdapter.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TimingProfile(BaseModel):
    """Centralized timing configuration for all human-behavior simulation.

    All values are in seconds or milliseconds as indicated. Defaults are
    tuned for a realistic job-seeking user on an average computer.
    """
    model_config = ConfigDict(frozen=True)

    # ── Human-like interaction timing ──────────────────────────────────
    inter_action_delay_ms: int = Field(default=1200, description="Delay between form interactions, milliseconds.")
    macro_pause_min_seconds: float = Field(default=0.8, description="Minimum longer pause between major steps.")
    macro_pause_max_seconds: float = Field(default=2.5, description="Maximum longer pause between major steps.")
    micro_delay_peak_ms: int = Field(default=50, description="Peak of per-keystroke jitter distribution, ms.")
    typing_wpm: int = Field(default=60, description="Nominal typing speed in words per minute.")
    typing_jitter_fraction: float = Field(default=0.20, ge=0.0, le=1.0, description="Fractional jitter applied per keystroke (±20%).")
    thinking_pause_probability: float = Field(default=1 / 15, ge=0.0, le=1.0, description="Probability of a thinking pause after a character.")
    thinking_pause_min: float = Field(default=0.3, description="Minimum thinking pause duration, seconds.")
    thinking_pause_max: float = Field(default=0.8, description="Maximum thinking pause duration, seconds.")

    # ── Mouse behavior ────────────────────────────────────────────────
    mouse_move_steps: int = Field(default=5, description="Number of incremental moves per fidget or mouse action.")
    mouse_offset_min_px: int = Field(default=50, description="Minimum pixel offset per single mouse move.")
    mouse_offset_max_px: int = Field(default=200, description="Maximum pixel offset per single mouse move.")
    mouse_step_delay_min: float = Field(default=0.2, description="Minimum delay between mouse moves, seconds.")
    mouse_step_delay_max: float = Field(default=0.8, description="Maximum delay between mouse moves, seconds.")

    # ── Navigation ─────────────────────────────────────────────────────
    between_provider_pause_min: float = Field(default=2.0, description="Minimum pause between search providers, seconds.")
    between_provider_pause_max: float = Field(default=5.0, description="Maximum pause between search providers, seconds.")
    idle_action_max_interval: float = Field(default=8.0, description="Maximum seconds without any browser micro-action.")
    page_load_timeout: int = Field(default=30, description="Timeout for page loads, seconds.")
    navigation_retries: int = Field(default=3, description="Number of retries on failed navigation.")


class BehaviorParameters(BaseModel):
    """Immutable session-wide behavior configuration.

    Contains a `TimingProfile` and an optional deterministic seed for
    reproducibility. Built once at session start from the effective config.
    """
    model_config = ConfigDict(frozen=True)

    timing: TimingProfile = Field(default_factory=TimingProfile)
    random_seed: int | None = Field(default=None, description="Seed for deterministic runs; None means non-deterministic.")

    @classmethod
    def from_config(cls, config: dict) -> "BehaviorParameters":
        """Create a BehaviorParameters instance from the effective config dictionary.

        Config sections used:
        - ``browser``   → navigation timeouts, idle intervals
        - ``discovery`` → provider pauses
        - ``applications`` → form interaction timing, typing, thinking pauses
        - ``session``   → random_seed

        All defaults match the `runtime_defaults.yaml` values.
        """
        browser = config.get("browser", {})
        discovery = config.get("discovery", {})
        applications = config.get("applications", {})
        session_cfg = config.get("session", {})

        return cls(
            timing=TimingProfile(
                inter_action_delay_ms=applications.get("inter_action_delay_ms", 1200),
                macro_pause_min_seconds=applications.get("macro_pause_min_seconds", 0.8),
                macro_pause_max_seconds=applications.get("macro_pause_max_seconds", 2.5),
                micro_delay_peak_ms=applications.get("micro_delay_peak_ms", 50),
                typing_wpm=applications.get("typing_wpm", 60),
                typing_jitter_fraction=applications.get("typing_jitter_fraction", 0.20),
                thinking_pause_probability=applications.get("thinking_pause_probability", 1 / 15),
                thinking_pause_min=applications.get("thinking_pause_min", 0.3),
                thinking_pause_max=applications.get("thinking_pause_max", 0.8),
                mouse_move_steps=browser.get("mouse_move_steps", 5),
                mouse_offset_min_px=browser.get("mouse_offset_min_px", 50),
                mouse_offset_max_px=browser.get("mouse_offset_max_px", 200),
                mouse_step_delay_min=browser.get("mouse_step_delay_min", 0.2),
                mouse_step_delay_max=browser.get("mouse_step_delay_max", 0.8),
                between_provider_pause_min=discovery.get("between_provider_pause_min", 2.0),
                between_provider_pause_max=discovery.get("between_provider_pause_max", 5.0),
                idle_action_max_interval=browser.get("idle_action_max_interval_seconds", 8.0),
                page_load_timeout=browser.get("page_load_timeout_seconds", 30),
                navigation_retries=browser.get("navigation_retries", 3),
            ),
            random_seed=session_cfg.get("random_seed"),
        )