"""Pins for G1 (axis choice) and G2 (pane-clipped visibility), measured live
on the committed tool and fixed in the split scroller/probe.

G1 — the axis choice used to send vertical scrolls to the JS fallback
whenever a target sat further from the viewport's centre column than below
the fold. Now an axis needs a scroll only when the target lies outside the
visible range on that axis.

G2 — a target clipped by its own scroll pane used to be refused as
"occluded:div" with the pane's scrollTop still 0. Now visibility is the
intersection of the window viewport with every scrolling ancestor's client
rect, a pane-clip verdict scrolls the pane, and only a PERSISTENT clip is
refused (guard-independent: the pointer rung would land on whatever is on
top of the target inside the pane).
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

from auto_apply.application.services.page_action.probe import TargetProbe
from auto_apply.application.services.page_action.service import PageActionService
from auto_apply.domain.models.motion import MotionCapabilities, MotionKind

CAPS = MotionCapabilities(trusted_pointer=True, wheel=True, timed_ticks=True)

WINDOW_PANE = {
    "x": 0, "y": 0, "w": 1366, "h": 1200,
    "top": 0, "max": 4000, "left": 0, "maxX": 0, "ox": 683, "oy": 600,
}
INNER_BEFORE = {
    "x": 100, "y": 100, "w": 300, "h": 200,
    "top": 0, "max": 900, "left": 0, "maxX": 0, "ox": 150, "oy": 150,
}
INNER_AFTER = dict(INNER_BEFORE, top=650)
BOX_CLIPPED = {"x": 150.0, "y": 900.0, "w": 120.0, "h": 36.0}
BOX_CLEARED = {"x": 150.0, "y": 150.0, "w": 120.0, "h": 36.0}


def _probe(verdict, box, panes, vw=1366, vh=768):
    return {
        "verdict": verdict,
        "tag": "button",
        "role": "",
        "input_type": "",
        "box": box,
        "frame": {"x": 0, "y": 0},
        "viewport": {"w": vw, "h": vh},
        "panes": panes,
    }


def _tool(probes, *, cfg=None):
    """A tool whose probe returns the scripted dicts in order (last repeats)."""
    browser = MagicMock()
    queue = list(probes)

    def _exec(script, *args):
        if "elementFromPoint" in script:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return None

    browser.execute_script.side_effect = _exec
    browser.motion_capabilities = CAPS

    registry = MagicMock()
    registry.get_all_effective_config.return_value = {
        "enable_human_timing": False,
        "occlusion_guard": True,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.0,
        "settle_max_s": 0.0,
        "min_action_delay_ms": 0,
        "infinite_scroll_settle_s": 0.0,
        **(cfg or {}),
    }
    return PageActionService(browser=browser, registry=registry, rng=random.Random(7))


# ── G1: the axis choice ──────────────────────────────────────────────────────


def test_axis_need_is_zero_when_the_box_intersects_the_visible_range():
    assert TargetProbe.axis_need(-50.0, 170.0, 0.0, 1366.0) == 0.0
    assert TargetProbe.axis_need(100.0, 300.0, 0.0, 768.0) == 0.0
    # Fully below: positive (scroll down). Fully above: negative.
    assert TargetProbe.axis_need(1400.0, 1440.0, 0.0, 768.0) > 0.0
    assert TargetProbe.axis_need(-200.0, -60.0, 0.0, 768.0) < 0.0


def test_a_left_column_target_scrolls_vertically_by_wheel_not_the_js_fallback():
    """The measured G1 case: dx=-638.8, dy=+569.5 used to pick horizontal,
    fail every pane, and land on scrollIntoView."""
    deep = _probe(
        "offscreen",
        {"x": -50.0, "y": 1400.0, "w": 220.0, "h": 40.0},
        [{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 0, "max": 3000,
          "left": 0, "maxX": 0, "ox": 683, "oy": 384}],
    )
    inview = _probe(
        "ok",
        {"x": -50.0, "y": 400.0, "w": 220.0, "h": 40.0},
        [{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 700, "max": 3000,
          "left": 0, "maxX": 0, "ox": 683, "oy": 384}],
    )
    tool = _tool([deep, inview, inview])

    result = tool.scroll_into_view(MagicMock())

    assert bool(result) is True
    assert result.rung == "wheel"
    scripts = [c.args[0] for c in tool._browser.execute_script.call_args_list]
    assert not any("scrollIntoView" in s for s in scripts if isinstance(s, str))
    plan = tool._browser.execute_motion.call_args.args[0]
    assert all(t.dx == 0 for t in plan.wheel_ticks), "a horizontal wheel tick survived"
    assert any(t.dy > 0 for t in plan.wheel_ticks), "no vertical wheel happened"


# ── G2: visibility is region intersection ────────────────────────────────────


def test_visible_region_is_the_window_intersected_with_every_scrolling_ancestor():
    probe = _probe("ok", BOX_CLIPPED, [INNER_BEFORE, WINDOW_PANE], vh=1200)
    region = TargetProbe.visible_region(probe)
    assert region == (100.0, 100.0, 300.0, 200.0)


def test_a_target_inside_the_window_but_clipped_by_its_pane_is_not_visible():
    probe = _probe("pane-clip", BOX_CLIPPED, [INNER_BEFORE, WINDOW_PANE], vh=1200)
    region = TargetProbe.visible_region(probe)
    # Box centre (210, 918) is inside the 1366x1200 window but outside the
    # pane's 100..300 client band — NOT visible.
    assert not (region[0] <= 210.0 < region[0] + region[2]
                and region[1] <= 918.0 < region[1] + region[3])


def test_the_probe_script_distinguishes_a_pane_clip_from_an_overlay():
    script = PageActionService._PROBE_SCRIPT
    assert "pane-clip" in script
    assert "isScroller(t)" in script


def test_a_pane_clipped_target_is_scrolled_inside_the_pane_then_clicked():
    """G2, measured live: refused as occluded:div with scrollTop still 0 —
    now the pane scrolls and the pointer rung lands the click."""
    clipped = _probe("pane-clip", BOX_CLIPPED, [INNER_BEFORE, WINDOW_PANE], vh=1200)
    cleared = _probe("ok", BOX_CLEARED, [INNER_AFTER, WINDOW_PANE], vh=1200)
    tool = _tool([clipped, clipped, cleared, cleared, cleared])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "pointer"
    element.click.assert_not_called()
    plans = [c.args[0] for c in tool._browser.execute_motion.call_args_list]
    wheel = next(p for p in plans if p.kind is MotionKind.WHEEL)
    # The wheel acted over the INNER pane's own origin (D4), not the window's.
    assert wheel.wheel_origin == (150, 150)
    assert any(t.dy > 0 for t in wheel.wheel_ticks)
    assert plans[-1].kind is MotionKind.CLICK


def test_scroll_into_view_marks_the_pane_scroll_as_the_wheel_rung():
    clipped = _probe("pane-clip", BOX_CLIPPED, [INNER_BEFORE, WINDOW_PANE], vh=1200)
    cleared = _probe("ok", BOX_CLEARED, [INNER_AFTER, WINDOW_PANE], vh=1200)
    tool = _tool([clipped, cleared, cleared])

    result = tool.scroll_into_view(MagicMock())

    assert bool(result) is True
    assert result.rung == "wheel"
    plan = tool._browser.execute_motion.call_args.args[0]
    assert plan.wheel_origin == (150, 150)


def test_a_persistent_pane_clip_is_refused_and_nothing_is_clicked():
    """A clip no scroll resolves: refuse, guard-independent, and never let
    the pointer rung land on whatever is on top of the target."""
    stuck_pane = dict(INNER_BEFORE, max=0)  # the pane itself cannot move
    stuck = _probe("pane-clip", BOX_CLIPPED, [stuck_pane, WINDOW_PANE], vh=1200)
    tool = _tool([stuck, stuck, stuck])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert "clipped by its scroll pane" in result.reason
    assert result.rung == "probe"
    element.click.assert_not_called()
    kinds = [c.args[0].kind for c in tool._browser.execute_motion.call_args_list]
    assert MotionKind.CLICK not in kinds
    # And the WINDOW was never wheeled to fix an inner pane's clip:
    wheel_plans = [
        c.args[0] for c in tool._browser.execute_motion.call_args_list
        if c.args[0].kind is MotionKind.WHEEL
    ]
    assert all(p.wheel_origin != (683, 600) for p in wheel_plans)


def test_the_window_is_still_wheeled_when_it_is_the_clipper():
    """Ordinary below-the-fold: the window pane excludes the target, so the
    window scrolls — the G2 clipper filter must not break the common case."""
    deep = _probe(
        "offscreen",
        {"x": 400.0, "y": 2000.0, "w": 120.0, "h": 36.0},
        [{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 0, "max": 3000,
          "left": 0, "maxX": 0, "ox": 683, "oy": 384}],
    )
    inview = _probe(
        "ok",
        {"x": 400.0, "y": 300.0, "w": 120.0, "h": 36.0},
        [{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 800, "max": 3000,
          "left": 0, "maxX": 0, "ox": 683, "oy": 384}],
    )
    tool = _tool([deep, inview, inview])

    result = tool.scroll_into_view(MagicMock())

    assert bool(result) is True
    assert result.rung == "wheel"
    plan = tool._browser.execute_motion.call_args.args[0]
    assert plan.wheel_origin == (683, 384)
    assert any(t.dy > 0 for t in plan.wheel_ticks)
