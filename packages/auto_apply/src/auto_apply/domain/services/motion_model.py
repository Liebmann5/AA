"""Pure pointer/wheel motion planner. No I/O, no browser, no clock.

Every function takes an injected ``random.Random`` and returns immutable
plans, so a seeded session reproduces the identical plan on every OS and
Python version AA supports. Positions are integers (viewport CSS pixels)
and durations are integer milliseconds, so nothing downstream depends on
float formatting.
"""
from __future__ import annotations

import math
import random

from auto_apply.domain.models.motion import (
    MotionKind,
    MotionPlan,
    PointerTick,
    WheelTick,
)
from auto_apply.domain.models.motion_profile import MotionProfile

Box = tuple[float, float, float, float]  # x, y, width, height (viewport CSS px)
Point = tuple[int, int]
Viewport = tuple[int, int]


def sample_landing_point(
    box: Box, profile: MotionProfile, rng: random.Random
) -> Point:
    """A point inside the target's safe inner region — never the exact centre.

    Every driver's native click lands dead centre; a uniform sample inside
    the shrunken box is the cheapest anti-signature there is, so even the
    ``instant`` profile keeps it.
    """
    bx, by, bw, bh = box
    cx, cy = bx + bw / 2.0, by + bh / 2.0
    mx = min(bw / 2.0, max(1.0, bw * profile.inner_margin_fraction))
    my = min(bh / 2.0, max(1.0, bh * profile.inner_margin_fraction))
    lo_x, hi_x = bx + mx, bx + bw - mx
    lo_y, hi_y = by + my, by + bh - my
    if hi_x <= lo_x:
        hi_x = lo_x + 1.0
    if hi_y <= lo_y:
        hi_y = lo_y + 1.0
    x = int(round(rng.uniform(lo_x, hi_x)))
    y = int(round(rng.uniform(lo_y, hi_y)))
    if (x, y) == (int(round(cx)), int(round(cy))):
        x += 1 if x < bx + bw - 1 else -1
    return x, y


def fitts_duration_ms(
    distance_px: float, target_width_px: float, profile: MotionProfile
) -> float:
    """Movement time by Fitts's law: a + b * log2(D / W + 1)."""
    width = max(1.0, float(target_width_px))
    return profile.fitts_a_ms + profile.fitts_b_ms * math.log2(
        distance_px / width + 1.0
    )


def _min_jerk(t: float) -> float:
    """Minimum-jerk easing: slow at both ends, like a hand."""
    return t * t * t * (10.0 - 15.0 * t + 6.0 * t * t)


def plan_pointer_move(
    start: Point,
    end: Point,
    target_width_px: float,
    viewport: Viewport,
    profile: MotionProfile,
    rng: random.Random,
) -> tuple[PointerTick, ...]:
    """A curved, eased pointer path from ``start`` to ``end``.

    Cubic Bezier with two perpendicular-offset control points, min-jerk
    easing, optional overshoot-and-correct on long moves, and a small
    tremor. The final tick lands exactly on ``end``.
    """
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])
    distance = math.hypot(ex - sx, ey - sy)
    vw, vh = viewport
    if distance < 2.0:
        return (PointerTick(x=int(ex), y=int(ey), dt_ms=0),)

    duration = max(1.0, fitts_duration_ms(distance, target_width_px, profile))
    n = rng.randint(profile.move_segments_min, profile.move_segments_max)

    aim_x, aim_y = ex, ey
    overshoot = (
        distance > 300.0
        and profile.overshoot_max_px > 0
        and rng.random() < profile.overshoot_probability
    )
    if overshoot:
        amount = rng.uniform(profile.overshoot_min_px, profile.overshoot_max_px)
        ux, uy = (ex - sx) / distance, (ey - sy) / distance
        aim_x, aim_y = ex + ux * amount, ey + uy * amount

    curvature = rng.uniform(profile.curvature_min, profile.curvature_max) * distance
    if rng.random() < 0.5:
        curvature = -curvature
    nx, ny = (-(ey - sy) / distance, (ex - sx) / distance)
    c1 = (sx + (aim_x - sx) / 3.0 + nx * curvature,
          sy + (aim_y - sy) / 3.0 + ny * curvature)
    c2 = (sx + 2.0 * (aim_x - sx) / 3.0 - nx * curvature * 0.6,
          sy + 2.0 * (aim_y - sy) / 3.0 - ny * curvature * 0.6)

    raw_dts = [rng.uniform(0.75, 1.25) for _ in range(n)]
    total = sum(raw_dts)
    points: list[tuple[int, int, int]] = []
    prev: tuple[int, int] | None = None
    for i in range(1, n + 1):
        s = _min_jerk(i / n)
        u = 1.0 - s
        x = u**3 * sx + 3 * u * u * s * c1[0] + 3 * u * s * s * c2[0] + s**3 * aim_x
        y = u**3 * sy + 3 * u * u * s * c1[1] + 3 * u * s * s * c2[1] + s**3 * aim_y
        if profile.tremor_max_px:
            x += rng.uniform(-profile.tremor_max_px, profile.tremor_max_px)
            y += rng.uniform(-profile.tremor_max_px, profile.tremor_max_px)
        xi = min(max(int(round(x)), 0), max(vw - 1, 0))
        yi = min(max(int(round(y)), 0), max(vh - 1, 0))
        dt = max(0, int(round(duration * raw_dts[i - 1] / total)))
        if (xi, yi) != prev:
            points.append((xi, yi, dt))
            prev = (xi, yi)

    if overshoot and points:
        correct = max(2, n // 6)
        last_x, last_y = points[-1][0], points[-1][1]
        for j in range(1, correct + 1):
            t = j / correct
            xi = int(round(last_x + (ex - last_x) * t))
            yi = int(round(last_y + (ey - last_y) * t))
            if (xi, yi) != (points[-1][0], points[-1][1]):
                points.append((xi, yi, max(1, int(duration * 0.15 / correct))))

    fx, fy = int(round(ex)), int(round(ey))
    if not points or (points[-1][0], points[-1][1]) != (fx, fy):
        points.append((fx, fy, max(1, points[-1][2] if points else 0)))
    return tuple(PointerTick(x=x, y=y, dt_ms=dt) for x, y, dt in points)


def plan_click(
    start: Point,
    landing: Point,
    target_width_px: float,
    viewport: Viewport,
    profile: MotionProfile,
    rng: random.Random,
) -> MotionPlan:
    """A pointer move plus the hesitation before and the hold during the press."""
    ticks = plan_pointer_move(
        start, landing, target_width_px, viewport, profile, rng
    )
    hesitation = int(
        round(rng.uniform(profile.hesitation_ms_min, profile.hesitation_ms_max))
    )
    hold = int(round(rng.uniform(profile.hold_ms_min, profile.hold_ms_max)))
    return MotionPlan(
        kind=MotionKind.CLICK,
        pointer_ticks=ticks,
        pre_delay_ms=hesitation,
        hold_ms=hold,
    )


def plan_wheel(
    distance_px: int, profile: MotionProfile, rng: random.Random
) -> tuple[WheelTick, ...]:
    """Wheel ticks for ``distance_px`` (dy > 0 scrolls down), integer-exact.

    Trackpad deltas sum EXACTLY to the request. A notch device emits whole
    100px notches only — a sub-notch residual is left for the caller's
    measured verification to absorb. The previous float version drifted:
    250px requested produced 251 delivered, and a notch device emitted a
    50px partial notch (D7).
    """
    if distance_px == 0:
        return ()
    direction = 1 if distance_px > 0 else -1
    remaining = abs(int(distance_px))
    ticks: list[WheelTick] = []
    if profile.wheel_device == "wheel":
        # Whole notches; minimum one so a small request still scrolls.
        for _ in range(max(1, remaining // 100)):
            dt = rng.randint(profile.wheel_tick_ms_min, profile.wheel_tick_ms_max)
            ticks.append(WheelTick(dx=0, dy=direction * 100, dt_ms=dt))
        return tuple(ticks)
    while remaining > 0:
        if len(ticks) >= 63:
            step = remaining
        else:
            step = rng.randint(profile.wheel_tick_px_min, profile.wheel_tick_px_max)
        step = min(step, remaining)
        dt = rng.randint(profile.wheel_tick_ms_min, profile.wheel_tick_ms_max)
        ticks.append(WheelTick(dx=0, dy=direction * step, dt_ms=dt))
        remaining -= step
    return tuple(ticks)


def plan_fidget(
    current: Point,
    viewport: Viewport,
    profile: MotionProfile,
    rng: random.Random,
) -> MotionPlan:
    """A small tremor around the current position, ending back where it started."""
    vw, vh = viewport
    cx, cy = current
    n = (
        rng.randint(profile.fidget_moves_min, profile.fidget_moves_max)
        if profile.fidget_moves_max
        else 0
    )
    ticks: list[PointerTick] = []
    x, y = float(cx), float(cy)
    for _ in range(n):
        dx = rng.uniform(
            profile.fidget_offset_min_px, profile.fidget_offset_max_px
        ) * rng.choice((-1.0, 1.0))
        dy = rng.uniform(
            profile.fidget_offset_min_px, profile.fidget_offset_max_px
        ) * rng.choice((-1.0, 1.0))
        x = min(max(x + dx, 0.0), max(vw - 1.0, 0.0))
        y = min(max(y + dy, 0.0), max(vh - 1.0, 0.0))
        dt = int(
            round(
                rng.uniform(profile.fidget_delay_min_s, profile.fidget_delay_max_s)
                * 1000
            )
        )
        ticks.append(PointerTick(x=int(round(x)), y=int(round(y)), dt_ms=dt))
    if ticks and (int(x), int(y)) != (cx, cy):
        ticks.append(PointerTick(x=cx, y=cy, dt_ms=max(1, ticks[-1].dt_ms // 2)))
    return MotionPlan(kind=MotionKind.MOVE, pointer_ticks=tuple(ticks))
