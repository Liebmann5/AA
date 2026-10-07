"""Pins for the mouse tool's click ladder, hover and scroll primitives.

The browser is a MagicMock with scripted probe responses (dicts in the
shape _PROBE_SCRIPT returns); execute_motion is asserted on directly.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import pytest

from auto_apply.application.services.page_action.service import (
    ActionResult,
    PageActionService,
)
from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.models.motion import MotionCapabilities, MotionKind
from auto_apply.domain.types import Keys

CAPS = MotionCapabilities(trusted_pointer=True, wheel=True, timed_ticks=True)
NO_CAPS = MotionCapabilities()
BOX = {"x": 400.0, "y": 300.0, "w": 120.0, "h": 36.0}
CENTRE = (int(400 + 60), int(300 + 18))


def _probe(verdict="ok", box=None, tag="button", role="", input_type="", panes="default", vw=1366, vh=768):
    return {
        "verdict": verdict,
        "tag": tag,
        "role": role,
        "input_type": input_type,
        "box": box,
        "viewport": {"w": vw, "h": vh},
        "panes": (
            [{"x": 0, "y": 0, "w": vw, "h": vh, "top": 0, "max": 3000}]
            if panes == "default"
            else panes
        ),
    }


def _tool(probes, *, cfg=None, caps=CAPS, probe_raises=False, checked=()):
    """A tool whose probe returns the scripted dicts in order (last repeats)."""
    browser = MagicMock()
    queue = list(probes)
    checked_seq = list(checked)

    def _exec(script, *args):
        if ".checked" in script and checked_seq:
            return checked_seq.pop(0)
        if "elementFromPoint" in script:
            if probe_raises:
                raise RuntimeError("probe blew up")
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return None

    browser.execute_script.side_effect = _exec
    browser.motion_capabilities = caps
    browser.current_url = "https://example.com/x"

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
    tool = PageActionService(browser=browser, registry=registry, rng=random.Random(7))
    return tool


# ── rung 1: trusted pointer click ────────────────────────────────────────────


def test_a_click_travels_the_pointer_rung_and_never_hits_the_centre():
    tool = _tool([_probe(box=BOX)])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "pointer"
    tool._browser.execute_motion.assert_called_once()
    plan = tool._browser.execute_motion.call_args.args[0]
    assert plan.kind is MotionKind.CLICK
    assert len(plan.pointer_ticks) >= 2, "the human profile should curve"
    assert (plan.pointer_ticks[-1].x, plan.pointer_ticks[-1].y) != CENTRE
    element.click.assert_not_called()


def test_the_challenge_verdict_refuses_the_click_before_any_rung():
    tool = _tool([_probe(verdict="challenge")])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert "challenge" in result.reason
    assert result.rung == "probe"
    tool._browser.execute_motion.assert_not_called()
    element.click.assert_not_called()


def test_persistent_occlusion_is_still_refused():
    tool = _tool([_probe(verdict="occluded:div", box=BOX)])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert "occluded:div" in result.reason
    element.click.assert_not_called()


def test_an_offscreen_target_is_scrolled_then_clicked_by_pointer():
    deep = _probe(
        verdict="offscreen",
        box={"x": 400.0, "y": 2000.0, "w": 120.0, "h": 36.0},
    )
    inview = _probe(
        box=BOX,
        panes=[{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 800, "max": 3000}],
    )
    tool = _tool([deep, deep, inview, inview, inview])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "pointer"
    kinds = [c.args[0].kind for c in tool._browser.execute_motion.call_args_list]
    assert MotionKind.WHEEL in kinds, "the offscreen target was never scrolled"
    assert kinds[-1] is MotionKind.CLICK


# ── rungs 2-4 ────────────────────────────────────────────────────────────────


def test_the_keyboard_rung_activates_a_button_without_geometry():
    tool = _tool([_probe(box=None, tag="button")])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "keyboard"
    element.send_keys.assert_called_once_with(Keys.ENTER)


def test_the_keyboard_rung_focuses_text_entry_and_never_presses_enter():
    """D3, measured live: Enter on a text field SUBMITS the enclosing form."""
    tool = _tool([_probe(box=None, tag="input", input_type="text")])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "keyboard"
    assert result.effect == "focus"
    element.send_keys.assert_not_called()


def test_the_keyboard_rung_toggles_a_checkbox_with_space_and_verifies():
    """D3: Space toggles; the toggle is verified by the state changing."""
    tool = _tool([_probe(box=None, tag="input", input_type="checkbox")], checked=[False, True])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "keyboard"
    element.send_keys.assert_called_once_with(Keys.SPACE)


def test_an_unverified_toggle_descends_to_the_native_click():
    tool = _tool([_probe(box=None, tag="input", input_type="checkbox")], checked=[False, False])
    element = MagicMock()

    result = tool.click(element)

    assert result.rung == "native"
    element.click.assert_called_once()


def test_a_failed_probe_falls_through_to_the_native_click():
    tool = _tool([_probe()], probe_raises=True)
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "native"
    element.click.assert_called_once()


def test_the_js_rung_is_last_resort_and_recorded():
    tool = _tool([_probe(box=BOX, tag="div", role="")], caps=NO_CAPS)
    element = MagicMock()
    element.click.side_effect = RuntimeError("native failed")

    result = tool.click(element)

    assert bool(result) is True
    assert result.rung == "js"
    scripts = [c.args[0] for c in tool._browser.execute_script.call_args_list]
    assert "arguments[0].click();" in scripts


def test_an_irreversible_click_stops_when_a_rung_raises():
    tool = _tool([_probe(box=BOX)])
    tool._browser.execute_motion.side_effect = RuntimeError("driver blew up")
    element = MagicMock()

    result = tool.click(element, irreversible=True)

    assert bool(result) is False
    assert result.rung == "pointer"
    element.click.assert_not_called(), "a submit was retried after a possible action"


def test_the_js_rung_is_never_offered_to_an_irreversible_click():
    tool = _tool([_probe(box=BOX, tag="div", role="")], caps=NO_CAPS)
    element = MagicMock()
    element.click.side_effect = RuntimeError("native failed")

    result = tool.click(element, irreversible=True)

    assert bool(result) is False
    scripts = [c.args[0] for c in tool._browser.execute_script.call_args_list]
    assert "arguments[0].click();" not in scripts


def test_a_stale_element_fails_fast_without_walking_the_ladder():
    """D6: a stale element returns reason='stale' immediately — no probe,
    no rungs, no 90 seconds of handle timeouts."""
    tool = _tool([_probe(box=BOX)])

    def _exec(script, *args):
        if "isConnected" in script:
            return False
        return None

    tool._browser.execute_script.side_effect = _exec
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert result.reason == "stale"
    assert result.rung == "probe"
    tool._browser.execute_motion.assert_not_called()
    element.click.assert_not_called()
    element.send_keys.assert_not_called()


def test_a_stale_element_error_is_stale_not_a_ladder_walk():
    tool = _tool([_probe(box=BOX)])

    def _exec(script, *args):
        if "isConnected" in script:
            raise RuntimeError("StaleElementReferenceException")
        return None

    tool._browser.execute_script.side_effect = _exec

    result = tool.click(MagicMock())

    assert bool(result) is False
    assert result.reason.startswith("stale")
    assert result.rung == "probe"


def test_the_guard_runs_again_after_the_offscreen_scroll():
    """D10: a scroll changes what is topmost — the guard re-runs before acting."""
    deep = _probe(
        verdict="offscreen",
        box={"x": 400.0, "y": 2000.0, "w": 120.0, "h": 36.0},
    )
    covered = _probe(
        verdict="occluded:header",
        box=BOX,
        panes=[{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 800, "max": 3000}],
    )
    tool = _tool([deep, deep, covered, covered, covered])
    element = MagicMock()

    result = tool.click(element)

    assert bool(result) is False
    assert "occluded:header" in result.reason
    element.click.assert_not_called()


def test_navigation_resets_the_virtual_cursor():
    """D11: one cursor truth, reset when the document changes."""
    tool = _tool([_probe()])
    tool._cursor = (11, 22)
    tool._browser.get.return_value = None

    assert bool(tool.navigate("https://example.com/x")) is True
    assert tool._cursor is None


def test_effect_reports_focus_change():
    """D12: focus moves are a reported channel, not folded into 'none'."""
    tool = _tool([_probe(box=BOX)])
    shots = iter([
        ["https://example.com/x", 100, ""],
        ["https://example.com/x", 100, "INPUT#f"],
    ])

    def _exec(script, *args):
        if "activeElement" in script:
            return next(shots)
        if "elementFromPoint" in script:
            return _probe(box=BOX)
        return None

    tool._browser.execute_script.side_effect = _exec

    result = tool.click(MagicMock())

    assert result.effect == "focus-change"


# ── scroll primitives ────────────────────────────────────────────────────────


def test_scroll_to_leaves_the_target_inside_the_viewport_on_both_conventions():
    """The old overshoot bug: get_location (document-relative on Selenium,
    viewport-relative on Playwright) must never be read again."""
    deep = _probe(
        verdict="offscreen",
        box={"x": 400.0, "y": 2000.0, "w": 120.0, "h": 36.0},
    )
    inview = _probe(
        box=BOX,
        panes=[{"x": 0, "y": 0, "w": 1366, "h": 768, "top": 800, "max": 3000}],
    )
    tool = _tool([deep, inview, inview])
    element = MagicMock()

    result = tool.scroll_to(element)

    assert bool(result) is True
    assert result.rung == "wheel"
    element.get_location.assert_not_called()


def test_scroll_container_returns_the_measured_delta():
    pane_before = {"x": 0, "y": 100, "w": 500, "h": 300, "top": 100, "max": 900}
    pane_after = dict(pane_before, top=160)
    tool = _tool([
        _probe(box=BOX, panes=[pane_before]),
        _probe(box=BOX, panes=[pane_after]),
    ])

    assert tool.scroll_container(MagicMock(), 120) == 60


def test_scroll_container_returns_zero_when_nothing_can_move():
    pane = {"x": 0, "y": 0, "w": 1366, "h": 768, "top": 3000, "max": 3000}
    tool = _tool([_probe(box=BOX, panes=[pane])])

    assert tool.scroll_container(MagicMock(), 400) == 0


# ── the untangled switches ───────────────────────────────────────────────────


def test_motion_survives_with_the_fingerprint_flag_off_and_the_gate_is_gone():
    """Low-resource used to lose ALL motion as a side effect of a stealth flag."""
    tool = _tool([_probe(box=BOX)], cfg={"enable_fingerprint_spoofing": False})

    result = tool.click(MagicMock())

    assert bool(result) is True
    assert result.rung == "pointer"
    assert not hasattr(tool, "_fingerprint"), "the conflated gate survived"


# ── the handler seam ─────────────────────────────────────────────────────────


def test_a_handlers_refused_click_is_no_longer_silent():
    from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler

    class _H(BaseInputHandler):
        def handle(self, element, value):
            ...

    tool = MagicMock()
    tool.click.return_value = ActionResult(False, reason="occluded:div")
    handler = _H(browser=MagicMock(), page_action=tool)

    with pytest.raises(ApplicationError, match="occluded:div"):
        handler._click(MagicMock())


def test_a_handler_without_a_tool_refuses_a_raw_click():
    from auto_apply.adapters.secondary.interaction.handlers.base import BaseInputHandler

    class _H(BaseInputHandler):
        def handle(self, element, value):
            ...

    handler = _H(browser=MagicMock(), page_action=None)
    element = MagicMock()

    with pytest.raises(ApplicationError, match="no interaction tool"):
        handler._click(element)
    element.click.assert_not_called()


# ── the session tally ────────────────────────────────────────────────────────


def test_the_tally_counts_a_pointer_click_once():
    tool = _tool([_probe(box=BOX)])

    assert bool(tool.click(MagicMock())) is True
    assert tool.tally_snapshot()["clicks"] == {"pointer": 1}
    assert tool.tally_snapshot()["click_refusals"] == 0


def test_the_tally_counts_a_refusal_without_a_rung():
    tool = _tool([_probe(verdict="challenge")])

    assert bool(tool.click(MagicMock())) is False
    snap = tool.tally_snapshot()
    assert snap["clicks"] == {}
    assert snap["click_refusals"] == 1


def test_the_tally_counts_a_js_click_as_js():
    tool = _tool([_probe(box=BOX, tag="div", role="")], caps=NO_CAPS)
    element = MagicMock()
    element.click.side_effect = RuntimeError("native failed")

    assert bool(tool.click(element)) is True
    assert tool.tally_snapshot()["clicks"] == {"js": 1}


def test_the_tally_counts_scroll_rungs():
    tool = _tool([_probe(box=BOX)])

    result = tool.scroll_into_view(MagicMock())

    assert result.rung == "already-visible"
    assert tool.tally_snapshot()["scrolls"] == {"already-visible": 1}
