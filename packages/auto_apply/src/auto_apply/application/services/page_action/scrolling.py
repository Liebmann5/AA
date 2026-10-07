"""Scroller — every scroll the tool performs: into view, container, feed, reveal.

One wheel cadence (the motion model's plan), real wheel input wherever the
driver allows it, and MEASURED progress: a step counts only when the pane's
own offset moved. The instant-JS scroll survives only as the recorded
no-wheel fallback (R-19, ruled: cadence first, teleport last).

Two measured-gap fixes live here:

G1 — axis need. An axis needs a scroll only when the target lies outside the
     visible range on that axis (TargetProbe.axis_need). A left-column
     target below the fold no longer reads as needing a horizontal scroll,
     which used to fail every pane and fall back to scrollIntoView.

G2 — pane-aware visibility. "Visible" is the intersection of the window
     viewport with every scrolling ancestor's client rect
     (TargetProbe.visible_region). A target clipped by its own scroll pane
     is scrolled INSIDE that pane; a pane whose client range already
     contains the target on the needed axis is never wheeled (scrolling it
     changes nothing), so the window is never scrolled to fix an inner pane.
"""
from __future__ import annotations

import logging
import time

from auto_apply.application.services.page_action.pacing import Pacing
from auto_apply.application.services.page_action.probe import (
    ROOT_SCROLL_READ,
    TargetProbe,
)
from auto_apply.application.services.page_action.result import ActionResult
from auto_apply.application.services.page_action.state import PageActionContext
from auto_apply.domain.models.motion import MotionKind, MotionPlan, WheelTick
from auto_apply.domain.services import motion_model
from auto_apply.domain.ports.browser_port import ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)

_SCROLL_INTO_VIEW_MAX_STEPS: int = 12
_RETURN_TO_TOP_MAX_STEPS: int = 12


class Scroller:
    """Scrolls panes with real wheel input until the target is visible."""

    def __init__(
        self,
        state: PageActionContext,
        probe: TargetProbe,
        pacing: Pacing,
    ) -> None:
        self._state = state
        self._probe = probe
        self._pacing = pacing

    # ------------------------------------------------------------------
    # Into view
    # ------------------------------------------------------------------

    def scroll_to(self, element: ElementInterface) -> ActionResult:
        """Scrolls an element into view. Alias of scroll_into_view, kept for
        the existing call sites (occlusion guard, click ladder, handlers)."""
        return self.scroll_into_view(element)

    def scroll_into_view(self, element: ElementInterface) -> ActionResult:
        """Records the rung of every into-view scroll in the session tally."""
        result = self._scroll_into_view_impl(element)
        self._state.tally.record_scroll(result.rung)
        return result

    def _scroll_into_view_impl(self, element: ElementInterface) -> ActionResult:
        """Scrolls panes (innermost first) with real wheel input until the
        element's box centre sits inside the VISIBLE REGION — the window
        viewport intersected with every scrolling ancestor's client rect.

        Progress is verified by MEASURED offset change each step, which
        tolerates scroll-jacking, smooth-scroll and scroll-snap; a recorded
        instant JS scroll is the fallback when wheel input is unavailable
        or makes no progress.
        """
        last_rung = "already-visible"
        for _ in range(_SCROLL_INTO_VIEW_MAX_STEPS):
            probe = self._probe.run(element)
            if probe is None:
                return ActionResult(False, reason="scroll probe failed", rung="probe")
            box = probe.get("box")
            if not isinstance(box, dict):
                return ActionResult(False, reason="scroll probe failed", rung="probe")
            region = TargetProbe.visible_region(probe)
            if self._box_centre_inside(box, region):
                return ActionResult(True, element=element, rung=last_rung)
            dx_needed = TargetProbe.axis_need(
                box["x"], box["x"] + box["w"], region[0], region[2]
            )
            dy_needed = TargetProbe.axis_need(
                box["y"], box["y"] + box["h"], region[1], region[3]
            )
            if dx_needed == 0.0 and dy_needed == 0.0:
                return ActionResult(True, element=element, rung=last_rung)
            if not self._wheel_toward(element, probe, box, dx_needed, dy_needed):
                break
            last_rung = "wheel"
        try:
            self._state.browser.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            probe = self._probe.run(element)
            box = (probe or {}).get("box")
            if isinstance(box, dict) and self._box_centre_inside(
                box, TargetProbe.visible_region(probe)
            ):
                logger.info("scroll_into_view used the instant JS fallback")
                return ActionResult(True, element=element, rung="js-scroll")
        except Exception as exc:
            return ActionResult(False, reason=str(exc), rung="js-scroll")
        return ActionResult(
            False, reason="target could not be scrolled into view", rung=last_rung
        )

    @staticmethod
    def _box_centre_inside(box: dict, region: tuple[float, float, float, float]) -> bool:
        rx, ry, rw, rh = region
        if rw <= 0 or rh <= 0:
            return False
        cx = box["x"] + box["w"] / 2.0
        cy = box["y"] + box["h"] / 2.0
        return rx <= cx < rx + rw and ry <= cy < ry + rh

    def _wheel_toward(
        self,
        element: ElementInterface,
        probe: dict,
        box: dict,
        dx_needed: float,
        dy_needed: float,
    ) -> bool:
        """One wheel step toward the target through the innermost pane that
        can move in the needed direction (whichever axis needs more — with
        G1's axis_need, a visible axis reports 0 and never wins the choice).

        Only a pane whose own client range EXCLUDES the target on the needed
        axis is a candidate: scrolling a pane that already contains the
        target changes nothing (G2 — the window must not be wheeled to fix
        an inner pane's clip). The pointer moves to the pane's own origin
        first (D4), and progress is the MEASURED offset change on the
        scrolled axis. True iff something moved; False means 'try the
        fallback'.
        """
        caps = self._probe.capabilities()
        if not caps.wheel:
            self._probe.note_capability_gap("wheel input")
            return False
        horizontal = abs(dx_needed) > abs(dy_needed)
        needed = dx_needed if horizontal else dy_needed
        direction = 1 if needed > 0 else -1
        box_lo = box["x"] if horizontal else box["y"]
        box_hi = box_lo + (box["w"] if horizontal else box["h"])
        for pane in probe.get("panes") or []:
            pane_lo = float(pane.get("x", 0) if horizontal else pane.get("y", 0))
            pane_len = float(pane.get("w", 0) if horizontal else pane.get("h", 0))
            if box_hi > pane_lo and box_lo < pane_lo + pane_len:
                # The target is already inside this pane's range on this
                # axis — this pane is not the clipper.
                continue
            if horizontal:
                pos = float(pane.get("left", 0))
                limit = float(pane.get("maxX", 0))
                extent = float(pane.get("w", 400))
            else:
                pos = float(pane.get("top", 0))
                limit = float(pane.get("max", 0))
                extent = float(pane.get("h", 400))
            room = (limit - pos) if direction > 0 else pos
            if room <= 0:
                continue
            step = direction * min(abs(needed), extent * 0.8, room)
            base_ticks = motion_model.plan_wheel(
                int(step), self._state.motion.profile, self._state.wheel_rng
            )
            if not base_ticks:
                continue
            if horizontal:
                ticks = tuple(
                    WheelTick(dx=t.dy, dy=0, dt_ms=t.dt_ms) for t in base_ticks
                )
            else:
                ticks = base_ticks
            origin = TargetProbe.pane_origin(pane)
            path = self._approach_path(origin)
            try:
                self._state.browser.execute_motion(
                    MotionPlan(
                        kind=MotionKind.WHEEL,
                        pointer_ticks=path,
                        wheel_ticks=ticks,
                        wheel_origin=origin,
                    )
                )
                if path:
                    self._state.cursor = origin
            except Exception as exc:
                logger.warning("wheel rung failed | %s", exc)
                return False
            after = TargetProbe.match_pane_offsets(
                self._settle_pane(element, pane), pane
            )
            if after is not None:
                new_pos = after[1] if horizontal else after[0]
                if abs(new_pos - pos) > 0.5:
                    return True
            # No movement in this pane — try the next ancestor.
        return False

    def _settle_pane(self, element, pane: dict) -> dict | None:
        """Re-probe until the pane's offset stops changing, then return the probe.

        Playwright's wheel returns before the page scrolls, and smooth
        scrolling animates afterwards; an immediate re-probe reads the
        PRE-scroll offset and reports "no movement" (measured live: 1 run in
        4 on Chromium 141 fell back to the instant JS scroll for exactly
        this reason). Poll until the offset is stable across two consecutive
        reads that differ from the pre-scroll offset — or the configured
        ``scroll_settle_timeout_s`` budget expires. Bounded always; a pane
        that never moves costs one budget, never a hang.
        """
        before_top = float(pane.get("top", 0))
        before_left = float(pane.get("left", 0))
        deadline = time.monotonic() + self._state.scroll_settle_s
        last: tuple[float, float] | None = None
        probe: dict | None = None
        while time.monotonic() < deadline:
            probe = self._probe.run(element)
            offsets = TargetProbe.match_pane_offsets(probe, pane)
            if offsets is not None:
                moved = (
                    abs(offsets[0] - before_top) > 0.5
                    or abs(offsets[1] - before_left) > 0.5
                )
                if (
                    moved
                    and last is not None
                    and abs(offsets[0] - last[0]) <= 0.5
                    and abs(offsets[1] - last[1]) <= 0.5
                ):
                    break
                last = offsets
            time.sleep(0.05)
        return probe

    # ------------------------------------------------------------------
    # Container scroll (the AD-1 primitive)
    # ------------------------------------------------------------------

    def scroll_container(self, element: ElementInterface, dy: int) -> int:
        """Scrolls the nearest scrollable ancestor of *element* by up to
        |dy| CSS pixels of wheel input (the AD-1 primitive).

        Returns the MEASURED offset change — 0 when nothing moved, no pane
        could scroll, or the driver cannot do wheel input (logged once).
        """
        probe = self._probe.run(element)
        if probe is None:
            return 0
        caps = self._probe.capabilities()
        if not caps.wheel:
            self._probe.note_capability_gap("wheel input")
            return 0
        direction = 1 if dy > 0 else -1
        for pane in probe.get("panes") or []:
            top = float(pane.get("top", 0))
            max_top = float(pane.get("max", 0))
            room = (max_top - top) if direction > 0 else top
            if room <= 0:
                continue
            step = direction * min(abs(dy), room)
            ticks = motion_model.plan_wheel(
                int(step), self._state.motion.profile, self._state.wheel_rng
            )
            if not ticks:
                return 0
            origin = TargetProbe.pane_origin(pane)
            path = self._approach_path(origin)
            try:
                self._state.browser.execute_motion(
                    MotionPlan(
                        kind=MotionKind.WHEEL,
                        pointer_ticks=path,
                        wheel_ticks=ticks,
                        wheel_origin=origin,
                    )
                )
                if path:
                    self._state.cursor = origin
            except Exception as exc:
                logger.warning("scroll_container wheel failed | %s", exc)
                return 0
            after = TargetProbe.match_pane_offsets(
                self._settle_pane(element, pane), pane
            )
            moved = int(after[0] - top) if after is not None else 0
            if moved:
                self._state.tally.record_scroll("wheel")
            return moved
        return 0

    # ------------------------------------------------------------------
    # Feed scroll
    # ------------------------------------------------------------------

    def scroll_to_bottom(self) -> bool:
        """One measured scroll step toward the feed bottom.

        CONTRACT (D5): True = the step made progress — the document's real
        scroller (document.scrollingElement) moved OR the document grew.
        False = measured end: no movement and no growth. The caller's loop
        stops only on False or on its own caps, so a page that is merely
        taller than one viewport no longer reads as 'end of feed'.

        The wheel acts over the WINDOW pane's own origin (a point whose
        topmost element belongs to that pane, not to a nested scroller —
        D4), reached on a planned pointer path. The settle is measured DOM
        stability when a readiness port is injected, else the configured
        ``infinite_scroll_settle_s`` wait (the upper bound either way).
        The caller still owns the loop and the dry-scroll guard.

        Returns:
            True on progress, False at the measured end or on error (a
            scroll probe must never abort discovery).
        """
        try:
            before = self._state.browser.execute_script(ROOT_SCROLL_READ)
            viewport = self._state.last_viewport or (1366, 768)
            self._wheel_window(int(viewport[1] * 0.9))
            self._await_feed_settle()
            after = self._state.browser.execute_script(ROOT_SCROLL_READ)
            moved = after[1] != before[1]
            grew = after[0] > before[0]
            return bool(moved or grew)
        except Exception as exc:
            logger.warning("scroll_to_bottom failed | %s", exc)
            return False

    def _wheel_window(self, dy_px: int) -> bool:
        """One wheel plan over the window pane's own origin. True when the
        plan executed; False after the recorded instant-scroll fallback ran
        instead (no wheel capability)."""
        caps = self._probe.capabilities()
        if not caps.wheel:
            if dy_px:
                self._probe.note_capability_gap(
                    "wheel input — using the recorded instant-scroll fallback"
                )
                self._state.browser.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);"
                    if dy_px > 0
                    else "window.scrollTo(0, 0);"
                )
                self._state.tally.record_scroll("js-scroll")
            return False
        if dy_px == 0:
            return False
        viewport = self._state.last_viewport or (1366, 768)
        origin: tuple[int, int] = (viewport[0] // 2, viewport[1] // 2)
        body = self._state.browser.find_element(Locator.TAG_NAME, "body")
        if body is not None:
            body_probe = self._probe.run(body)
            panes = (body_probe or {}).get("panes") or []
            if panes:
                origin = TargetProbe.pane_origin(panes[-1])
        ticks = motion_model.plan_wheel(
            int(dy_px), self._state.motion.profile, self._state.wheel_rng
        )
        if not ticks:
            return False
        path = self._approach_path(origin)
        self._state.browser.execute_motion(
            MotionPlan(
                kind=MotionKind.WHEEL,
                pointer_ticks=path,
                wheel_ticks=ticks,
                wheel_origin=origin,
            )
        )
        if path:
            self._state.cursor = origin
        self._state.tally.record_scroll("wheel")
        return True

    def _await_feed_settle(self) -> None:
        """Wait for the feed to react: measured DOM stability when a
        readiness port is injected, else the configured fixed wait
        (``infinite_scroll_settle_s`` is the upper bound either way)."""
        if self._state.readiness is not None:
            try:
                self._state.readiness.wait_for_dom_stable(
                    timeout=self._state.infinite_scroll_settle_s
                )
                return
            except Exception:
                pass
        time.sleep(self._state.infinite_scroll_settle_s)

    # ------------------------------------------------------------------
    # The form reveal (call 2)
    # ------------------------------------------------------------------

    def reveal_page(self, max_steps: int = 8) -> int:
        """Wheel-scan down so lazy content renders, then return to the top.

        A form read before the page is scrolled sees only the first
        screenful: sections below the fold are never rendered, so the
        analysis never sees them. This scan uses the wheel cadence (a fast
        human), is bounded by ``max_steps`` on every axis, and NEVER raises —
        a reveal must not be able to abort a form fill. The return journey
        is wheel input too, with the recorded teleport as the no-wheel
        fallback.

        Returns:
            The number of downward steps that made progress (0 on a dead
            browser or a single-screen page).
        """
        steps = 0
        try:
            for _ in range(max(0, int(max_steps))):
                if not self.scroll_to_bottom():
                    break
                steps += 1
            self._return_to_top()
        except Exception as exc:
            logger.debug("reveal_page degraded: %s", exc)
        return steps

    def _return_to_top(self, max_steps: int = _RETURN_TO_TOP_MAX_STEPS) -> None:
        """Wheel back up until the document's real scroller reads 0."""
        try:
            for _ in range(max(1, max_steps)):
                read = self._state.browser.execute_script(ROOT_SCROLL_READ)
                if not isinstance(read, (list, tuple)) or len(read) != 2:
                    return
                top = read[1]
                if not top or top <= 0:
                    return
                viewport = self._state.last_viewport or (1366, 768)
                if not self._wheel_window(-min(int(top), int(viewport[1] * 0.9))):
                    return
        except Exception as exc:
            logger.debug("return-to-top degraded: %s", exc)

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------

    def _approach_path(self, origin: tuple[int, int]) -> tuple:
        """Planned pointer path to a wheel origin. A real wheel scrolls
        whatever is under the cursor (D4), so the cursor travels to the
        origin first; empty when it is already there or no viewport is known.
        """
        if self._state.last_viewport is None:
            return ()
        start = self._state.cursor or (
            self._state.last_viewport[0] // 2, self._state.last_viewport[1] // 2
        )
        if start == origin:
            return ()
        return motion_model.plan_pointer_move(
            start,
            origin,
            24.0,
            self._state.last_viewport,
            self._state.motion.profile,
            self._state.pointer_rng,
        )
