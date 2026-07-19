"""Immutable Pydantic models for session timing and behavior parameters.

Centralizes all human-behavior simulation and navigation timing parameters.
Used by BehaviorSimulator and the HumanLikeAdapter.
"""
from __future__ import annotations

import hashlib
import os
import random

from pydantic import BaseModel, ConfigDict, Field

from auto_apply.domain.models.effective_config import EffectiveConfig


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
    page_load_timeout: int = Field(default=15, description="Timeout for page loads, seconds.")


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

        The ``AA_RANDOM_SEED`` environment variable takes precedence over the
        config file value, allowing ``--seed N`` on the command line to
        override any persisted setting.
        """
        settings = EffectiveConfig.from_mapping(config)
        session_cfg = config.get("session", {})

        # ── Resolve random_seed: CLI flag (env var) > config file > None ──
        # random_seed is a session-level value (env var or an admin-injected
        # ``session`` section), not a YAML knob, so it is read from the raw config.
        seed_from_env: int | None = None
        raw_env = os.environ.get("AA_RANDOM_SEED")
        if raw_env is not None:
            try:
                seed_from_env = int(raw_env)
            except ValueError:
                pass  # Ignore non-integer values; fall through to config

        random_seed: int | None = (
            seed_from_env
            if seed_from_env is not None
            else session_cfg.get("random_seed")
        )

        return cls(
            timing=TimingProfile(
                inter_action_delay_ms=settings.applications.inter_action_delay_ms,
                macro_pause_min_seconds=settings.applications.macro_pause_min_seconds,
                macro_pause_max_seconds=settings.applications.macro_pause_max_seconds,
                micro_delay_peak_ms=settings.applications.micro_delay_peak_ms,
                typing_wpm=settings.applications.typing_wpm,
                typing_jitter_fraction=settings.applications.typing_jitter_fraction,
                thinking_pause_probability=settings.applications.thinking_pause_probability,
                thinking_pause_min=settings.applications.thinking_pause_min,
                thinking_pause_max=settings.applications.thinking_pause_max,
                mouse_move_steps=settings.browser.mouse_move_steps,
                mouse_offset_min_px=settings.browser.mouse_offset_min_px,
                mouse_offset_max_px=settings.browser.mouse_offset_max_px,
                mouse_step_delay_min=settings.browser.mouse_step_delay_min,
                mouse_step_delay_max=settings.browser.mouse_step_delay_max,
                between_provider_pause_min=settings.discovery.between_provider_pause_min,
                between_provider_pause_max=settings.discovery.between_provider_pause_max,
                page_load_timeout=settings.page_load_timeout_seconds,
            ),
            random_seed=random_seed,
        )


    def make_rng(self, *namespaces: str) -> random.Random:
        """Return a :class:`random.Random` instance for reproducible or production use.

        When ``random_seed`` is not ``None``, a deterministic, reproducible
        ``Random`` is returned.  The seed is derived by hashing the original
        seed together with the supplied *namespaces*, which can include a
        component name, a work‑unit ID, an attempt counter, or any other stable
        string identifier.  Different namespace sets produce independent,
        uncorrelated streams — they are not simply different starting points
        in the same sequence.

        When ``random_seed`` is ``None`` (production mode), a fresh, unseeded
        ``random.Random()`` is returned, preserving completely non‑deterministic
        behavior without any effect from this method.

        Args:
            *namespaces: One or more stable string identifiers that
                differentiate the RNG stream within the session.  For example:
                ``make_rng("evasion.typing")``, ``make_rng("discovery.provider",
                provider_name)``, or ``make_rng("user_agent_rotation")``.

        Returns:
            A :class:`random.Random` instance ready for injection and use in
            any component that needs randomness, such as
            :class:`BehaviorSimulator` or :class:`HumanLikeAdapter`.
        """
        if self.random_seed is None:
            return random.Random()  # unseeded, non-deterministic

        # Concatenate the namespace parts in a stable order.
        namespace_str = ":".join(namespaces)

        # Hash the seed + namespace to produce a reproducible 64‑bit seed.
        # SHA‑256 is used instead of Python's built‑in hash() to avoid the
        # per‑process PYTHONHASHSEED randomization, which would make the
        # derived stream unreproducible across separate runs.
        seed_bytes = hashlib.sha256(
            f"{self.random_seed}:{namespace_str}".encode("utf-8")
        ).digest()

        # Use the first 8 bytes of the digest as a 64‑bit integer seed.
        derived_seed = int.from_bytes(seed_bytes[:8], byteorder="big")

        return random.Random(derived_seed)