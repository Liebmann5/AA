"""Pacing — the tool's two-timescale human behavior model.

MICRO timing (keystrokes, intra-task) and MACRO timing (reading time between
tasks) live here and nowhere else in AA. All values come from the resolved
effective config via the shared context; all randomness from the seeded
streams. Handlers, engines and providers feel this pacing only through the
tool's public verbs — they never sleep on their own.
"""
from __future__ import annotations

import time

from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.domain.services import motion_model


class Pacing:
    """Settle, macro pause, warmup and idle fidgets. No other concern."""

    def __init__(self, state: PageActionContext) -> None:
        self._state = state

    def micro_delay(self, peak_ms: float = 80.0, randomness: float = 0.35) -> float:
        """A parabolic intra-task delay in seconds."""
        state = self._state
        if not state.human_timing:
            return max(0.02, (peak_ms / 1000.0) * 0.4)
        x = state.rng.uniform(-1.0, 1.0)
        base = (-x * x + 1.0) * (peak_ms / 1000.0)
        factor = state.rng.uniform(1.0 - randomness, 1.0 + randomness)
        return max(0.01, abs(base * factor))

    def settle_pause(self) -> None:
        """Short post-action pause within a task, floored by min_action_delay_ms.

        The floor (low-resource-clamped by the registry) is the minimum time
        between actions, so it raises the settle range's lower bound; the upper
        bound is widened to match if the floor exceeds it, keeping lo <= hi.
        """
        state = self._state
        lo = max(state.settle_min_s, state.min_action_delay_s)
        hi = max(state.settle_max_s, lo)
        if not state.human_timing:
            time.sleep(lo)
            return
        time.sleep(state.rng.uniform(lo, hi))

    def macro_pause(
        self,
        min_s: float | None = None,
        max_s: float | None = None,
    ) -> None:
        """A human reading/thinking pause between tasks.

        Called by the tool after navigation and by engines at task boundaries:
        after a form page transition, after captcha resolves, before submitting.
        """
        state = self._state
        lo = min_s if min_s is not None else state.macro_min_s
        hi = max_s if max_s is not None else state.macro_max_s

        if not state.human_timing:
            time.sleep(lo)
            return

        if state.rng.random() < 0.70:
            duration = state.rng.uniform(lo, lo + (hi - lo) * 0.5)
        else:
            duration = state.rng.uniform(lo + (hi - lo) * 0.4, hi)

        if state.motion.profile.fidget_moves_max:
            self._idle_with_fidgets(duration)
        else:
            time.sleep(duration)

    def warmup_pause(self) -> None:
        """One-time pause before the first navigation of the session.

        Models a human orienting before acting. Uses the MACRO range (no new
        timing knobs) floored by min_action_delay_ms, jittered via the seeded
        rng, gated by enable_human_timing. Idempotent: a no-op after the
        first call. The facade's navigate() calls it; callers do not.
        """
        state = self._state
        if state.warmed_up:
            return
        state.warmed_up = True
        lo = max(state.macro_min_s, state.min_action_delay_s)
        hi = max(state.macro_max_s, lo)
        if not state.human_timing:
            time.sleep(lo)
            return
        time.sleep(state.rng.uniform(lo, hi))

    def _idle_with_fidgets(self, duration: float) -> None:
        """Sleeps for `duration` seconds with PLANNED pointer micro-movements.

        The motion model's tremor-and-return replaces the old adapter fidget
        (a ±5px wiggle on Selenium, a full-page teleport on Playwright).
        Skipped entirely until a probe has measured a viewport.
        """
        state = self._state
        profile = state.motion.profile
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if profile.fidget_moves_max and state.last_viewport is not None:
                current = state.cursor or (
                    state.last_viewport[0] // 2, state.last_viewport[1] // 2
                )
                plan = motion_model.plan_fidget(
                    current, state.last_viewport, profile, state.pointer_rng
                )
                if plan.pointer_ticks:
                    try:
                        state.browser.execute_motion(plan)
                        state.cursor = (
                            plan.pointer_ticks[-1].x, plan.pointer_ticks[-1].y
                        )
                    except Exception:
                        pass
            time.sleep(state.rng.uniform(0.2, 0.7))
