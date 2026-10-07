"""Motion profiles — the ONE home for every pointer/wheel behaviour value.

Three named profiles live here, fully documented with units and ranges:
``instant`` (CI / fast replay), ``human`` (the default: a fast human), and
``careful`` (slower, stealth-max). runtime_defaults.yaml's ``motion:``
section selects one and offers override slots; it deliberately restates NO
field values, so there is exactly one copy of every number.

Validation happens at load (CapabilitiesRegistry.build calls
``MotionConfig.from_mapping`` before anything runs): an unknown profile
name, an unknown override key, or an out-of-range value is refused with the
key, the value and the allowed range in the message.

The Fitts coefficients are starting points, and their basis is stated here
because AA forbids unmeasured numbers without a named source: they keep
total click time inside today's measured pacing envelope (the old
pre-click micro pauses summed to roughly 30-320 ms). The live-run
diagnostics in the motion design are what refines them.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class MotionProfile(BaseModel):
    """One named, validated set of pointer/wheel behaviour values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str

    # ── Pointer timing (Fitts's law): duration_ms = a + b*log2(D/W + 1) ──
    fitts_a_ms: int = Field(ge=0, le=2000, description="Fitts intercept, ms.")
    fitts_b_ms: int = Field(ge=0, le=2000, description="Fitts slope, ms/bit.")
    move_segments_min: int = Field(ge=1, le=64, description="Min ticks per move.")
    move_segments_max: int = Field(ge=1, le=64, description="Max ticks per move.")
    curvature_min: float = Field(ge=0.0, le=1.0, description="Min curve, fraction of distance.")
    curvature_max: float = Field(ge=0.0, le=1.0, description="Max curve, fraction of distance.")
    overshoot_probability: float = Field(ge=0.0, le=1.0, description="Chance of overshoot on moves > 300px.")
    overshoot_min_px: int = Field(ge=0, le=400, description="Min overshoot distance, px.")
    overshoot_max_px: int = Field(ge=0, le=400, description="Max overshoot distance, px.")
    tremor_max_px: int = Field(ge=0, le=10, description="Max per-tick jitter, px.")
    hold_ms_min: int = Field(ge=0, le=1000, description="Min press-hold, ms.")
    hold_ms_max: int = Field(ge=0, le=1000, description="Max press-hold, ms.")
    hesitation_ms_min: int = Field(ge=0, le=3000, description="Min pre-press pause, ms.")
    hesitation_ms_max: int = Field(ge=0, le=3000, description="Max pre-press pause, ms.")
    inner_margin_fraction: float = Field(
        gt=0.0, lt=0.5,
        description="Landing points are sampled inside the target box shrunk by this fraction per axis; never the exact centre.",
    )

    # ── Wheel ────────────────────────────────────────────────────────────
    wheel_device: Literal["trackpad", "wheel"] = Field(
        default="trackpad",
        description="trackpad = fine deltas; wheel = 100px notches. Consistent within a session.",
    )
    wheel_tick_px_min: int = Field(ge=1, le=2000, description="Min delta per wheel tick, px.")
    wheel_tick_px_max: int = Field(ge=1, le=2000, description="Max delta per wheel tick, px.")
    wheel_tick_ms_min: int = Field(ge=0, le=1000, description="Min pause per wheel tick, ms.")
    wheel_tick_ms_max: int = Field(ge=0, le=1000, description="Max pause per wheel tick, ms.")

    # ── Idle fidget ──────────────────────────────────────────────────────
    fidget_moves_min: int = Field(ge=0, le=12, description="Min moves per fidget (0 = no fidgets).")
    fidget_moves_max: int = Field(ge=0, le=12, description="Max moves per fidget.")
    fidget_offset_min_px: int = Field(ge=0, le=100, description="Min fidget displacement, px.")
    fidget_offset_max_px: int = Field(ge=0, le=100, description="Max fidget displacement, px.")
    fidget_delay_min_s: float = Field(ge=0.0, le=5.0, description="Min pause between fidget moves, s.")
    fidget_delay_max_s: float = Field(ge=0.0, le=5.0, description="Max pause between fidget moves, s.")

    @model_validator(mode="after")
    def _mins_do_not_exceed_maxes(self) -> "MotionProfile":
        for lo_name, hi_name in (
            ("move_segments_min", "move_segments_max"),
            ("curvature_min", "curvature_max"),
            ("overshoot_min_px", "overshoot_max_px"),
            ("hold_ms_min", "hold_ms_max"),
            ("hesitation_ms_min", "hesitation_ms_max"),
            ("wheel_tick_px_min", "wheel_tick_px_max"),
            ("wheel_tick_ms_min", "wheel_tick_ms_max"),
            ("fidget_moves_min", "fidget_moves_max"),
            ("fidget_offset_min_px", "fidget_offset_max_px"),
            ("fidget_delay_min_s", "fidget_delay_max_s"),
        ):
            lo = getattr(self, lo_name)
            hi = getattr(self, hi_name)
            if lo > hi:
                raise ValueError(f"{lo_name} ({lo}) exceeds {hi_name} ({hi})")
        return self


_BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "instant": dict(
        name="instant",
        fitts_a_ms=0, fitts_b_ms=0,
        move_segments_min=1, move_segments_max=1,
        curvature_min=0.0, curvature_max=0.0,
        overshoot_probability=0.0, overshoot_min_px=0, overshoot_max_px=0,
        tremor_max_px=0,
        hold_ms_min=20, hold_ms_max=40,
        hesitation_ms_min=0, hesitation_ms_max=0,
        inner_margin_fraction=0.25,
        wheel_device="trackpad",
        wheel_tick_px_min=600, wheel_tick_px_max=900,
        wheel_tick_ms_min=0, wheel_tick_ms_max=0,
        fidget_moves_min=0, fidget_moves_max=0,
        fidget_offset_min_px=0, fidget_offset_max_px=0,
        fidget_delay_min_s=0.0, fidget_delay_max_s=0.0,
    ),
    "human": dict(
        name="human",
        fitts_a_ms=90, fitts_b_ms=120,
        move_segments_min=18, move_segments_max=32,
        curvature_min=0.05, curvature_max=0.20,
        overshoot_probability=0.25, overshoot_min_px=20, overshoot_max_px=80,
        tremor_max_px=2,
        hold_ms_min=45, hold_ms_max=120,
        hesitation_ms_min=60, hesitation_ms_max=220,
        inner_margin_fraction=0.20,
        wheel_device="trackpad",
        wheel_tick_px_min=40, wheel_tick_px_max=120,
        wheel_tick_ms_min=8, wheel_tick_ms_max=24,
        fidget_moves_min=2, fidget_moves_max=4,
        fidget_offset_min_px=3, fidget_offset_max_px=12,
        fidget_delay_min_s=0.2, fidget_delay_max_s=0.6,
    ),
    "careful": dict(
        name="careful",
        fitts_a_ms=140, fitts_b_ms=160,
        move_segments_min=24, move_segments_max=40,
        curvature_min=0.10, curvature_max=0.30,
        overshoot_probability=0.40, overshoot_min_px=30, overshoot_max_px=120,
        tremor_max_px=2,
        hold_ms_min=70, hold_ms_max=160,
        hesitation_ms_min=150, hesitation_ms_max=400,
        inner_margin_fraction=0.18,
        wheel_device="trackpad",
        wheel_tick_px_min=30, wheel_tick_px_max=90,
        wheel_tick_ms_min=12, wheel_tick_ms_max=36,
        fidget_moves_min=2, fidget_moves_max=5,
        fidget_offset_min_px=3, fidget_offset_max_px=15,
        fidget_delay_min_s=0.25, fidget_delay_max_s=0.7,
    ),
}

#: The selectable behaviour-profile names. Single source: the GUI combobox,
#: the CLI wizard, the profile validator, AdminPolicy and the docs all read
#: this tuple instead of restating the names.
MOTION_PROFILE_NAMES: tuple[str, ...] = tuple(_BUILTIN_PROFILES)


class MotionConfig(BaseModel):
    """The resolved motion configuration for a session."""

    model_config = ConfigDict(frozen=True)

    profile: MotionProfile
    allow_js_click: bool = True

    @classmethod
    def from_mapping(cls, merged: dict[str, Any]) -> "MotionConfig":
        """Resolve the ``motion:`` section of the merged effective config.

        Precedence: built-in profile < legacy ``browser.mouse_*`` knobs <
        ``motion.profiles.<name>`` redefinition < ``motion.overrides``.

        Raises:
            ValueError: unknown profile name, unknown override key, or an
                out-of-range value. The message names the key, the value and
                the allowed range.
        """
        motion = merged.get("motion") or {}
        if not isinstance(motion, dict):
            raise ValueError(
                f"motion: expected a mapping, got {type(motion).__name__}"
            )
        raw_name = motion.get("profile", "human")
        name = str(raw_name).lower()
        if name not in _BUILTIN_PROFILES:
            raise ValueError(
                f"motion.profile {raw_name!r} is not one of "
                f"{sorted(_BUILTIN_PROFILES)}"
            )

        # The legacy ``browser.mouse_*`` knobs are NOT honoured here. They
        # never had a reader before this tool existed; mapping them broke
        # startup on the shipped config (150px > the fidget limit) and
        # silently overrode every named profile, instant included (D1). They
        # are retired outright — YAML, registry fallback, EffectiveConfig
        # and TimingProfile lose them in the same change.
        fields: dict[str, Any] = dict(_BUILTIN_PROFILES[name])
        custom = (motion.get("profiles") or {}).get(name) or {}
        fields.update(custom)
        fields.update(motion.get("overrides") or {})

        try:
            profile = MotionProfile(**fields)
        except ValidationError as exc:
            raise ValueError(
                f"motion: invalid value for profile {name!r}: {exc}"
            ) from exc
        return cls(
            profile=profile,
            allow_js_click=bool(motion.get("allow_js_click", True)),
        )
