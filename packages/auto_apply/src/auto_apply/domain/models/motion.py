"""Value types for pointer and wheel motion plans.

A MotionPlan is the single currency between the pure motion model
(``domain/services/motion_model.py``, which plans) and the browser adapters
(which execute). Plans are ephemeral — they cross no process boundary and are
never persisted — so these are plain frozen dataclasses, not Pydantic models,
the same call the codebase already makes for ephemeral worker records.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MotionKind(Enum):
    """What a plan does once it reaches its target."""

    MOVE = "move"
    CLICK = "click"
    WHEEL = "wheel"


@dataclass(frozen=True, slots=True)
class PointerTick:
    """One absolute pointer position in viewport CSS pixels.

    ``dt_ms`` is the pause BEFORE this tick is emitted, so a timed sequence
    replays the planned pace driver-side in a single action sequence.
    """

    x: int
    y: int
    dt_ms: int


@dataclass(frozen=True, slots=True)
class WheelTick:
    """One wheel delta in CSS pixels (dy > 0 scrolls down); dt as PointerTick."""

    dx: int
    dy: int
    dt_ms: int


@dataclass(frozen=True, slots=True)
class MotionPlan:
    """A complete, adapter-executable motion: ticks, timing, and press data.

    ``wheel_origin`` is the viewport point the wheel acts over. A real wheel
    scrolls whatever pane is under the cursor, so the tool sets this from
    probe geometry; adapters fall back to their last known pointer position.
    """

    kind: MotionKind
    pointer_ticks: tuple[PointerTick, ...] = ()
    wheel_ticks: tuple[WheelTick, ...] = ()
    pre_delay_ms: int = 0
    hold_ms: int = 0
    wheel_origin: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class MotionCapabilities:
    """What an adapter can truthfully do with motion plans.

    All-False is the honest default: an adapter that predates motion plans
    degrades loudly instead of pretending. ``native_humanization`` marks a
    driver that humanises on its own (e.g. camoufox); the tool then skips
    its own motion so two humanisers never stack.
    """

    trusted_pointer: bool = False
    wheel: bool = False
    timed_ticks: bool = False
    native_humanization: bool = False
