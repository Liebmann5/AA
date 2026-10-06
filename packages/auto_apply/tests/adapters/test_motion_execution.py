"""Adapter-level pins for honest motion-plan execution on both drivers.

The Selenium pins build a REAL ActionBuilder over a stub driver and read the
encoded W3C payload. The previous pins patched the builder with a MagicMock,
which accepted methods that do not exist on the real classes — D2 shipped
because shape was checked instead of binding.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

from auto_apply.domain.models.motion import (
    MotionCapabilities,
    MotionKind,
    MotionPlan,
    PointerTick,
    WheelTick,
)


def _click_plan(n: int = 5) -> MotionPlan:
    ticks = tuple(
        PointerTick(x=10 * i, y=20 * i, dt_ms=12) for i in range(1, n + 1)
    )
    return MotionPlan(
        kind=MotionKind.CLICK, pointer_ticks=ticks, pre_delay_ms=30, hold_ms=60
    )


def _device_actions(driver) -> dict:
    """The payload of the single perform(), grouped by input-device type."""
    driver.execute.assert_called_once()
    payload = driver.execute.call_args.args[1]
    devices: dict[str, list] = {}
    for dev in payload["actions"]:
        devices.setdefault(dev.get("type"), []).extend(dev.get("actions", []))
    return devices


# ── Selenium (real ActionBuilder, stub driver) ──────────────────────────────


class TestSeleniumMotion:
    def _adapter(self):
        from auto_apply.adapters.secondary.browser import selenium_adapter as mod

        mod._ensure_selenium()
        adapter = mod.SeleniumAdapter.__new__(mod.SeleniumAdapter)
        adapter._driver = MagicMock()
        adapter._cursor_x = 0
        adapter._cursor_y = 0
        return adapter

    def test_one_movement_is_one_perform_with_a_real_builder(self):
        adapter = self._adapter()
        adapter.execute_motion(_click_plan())
        adapter._driver.execute.assert_called_once()

    def test_the_payload_moves_every_tick_with_millisecond_durations(self):
        adapter = self._adapter()
        plan = _click_plan()
        adapter.execute_motion(plan)

        moves = [
            a for a in _device_actions(adapter._driver)["pointer"]
            if a["type"] == "pointerMove"
        ]
        assert len(moves) == len(plan.pointer_ticks)
        for action, tick in zip(moves, plan.pointer_ticks):
            assert action["x"] == tick.x
            assert action["y"] == tick.y
            assert action["duration"] == tick.dt_ms, "W3C pointer durations are ms"
            assert action["origin"] == "viewport"

    def test_the_payload_presses_and_releases_once_with_a_hold_pause(self):
        adapter = self._adapter()
        adapter.execute_motion(_click_plan())

        actions = _device_actions(adapter._driver)["pointer"]
        kinds = [a["type"] for a in actions]
        assert kinds.count("pointerDown") == 1
        assert kinds.count("pointerUp") == 1
        assert any(
            a["type"] == "pause" and a.get("duration") == 60 for a in actions
        ), "the 60ms hold is encoded as a pause, in ms"

    def test_wheel_ticks_encode_origin_deltas_and_millisecond_durations(self):
        adapter = self._adapter()
        plan = MotionPlan(
            kind=MotionKind.WHEEL,
            wheel_ticks=(
                WheelTick(dx=0, dy=120, dt_ms=8),
                WheelTick(dx=0, dy=120, dt_ms=8),
            ),
            wheel_origin=(100, 200),
        )
        adapter.execute_motion(plan)

        scrolls = [
            a for a in _device_actions(adapter._driver)["wheel"]
            if a["type"] == "scroll"
        ]
        assert len(scrolls) == 2
        for action in scrolls:
            assert (action["x"], action["y"]) == (100, 200)
            assert action["deltaY"] == 120
            assert action["duration"] == 8

    def test_capabilities_declare_full_support(self):
        assert self._adapter().motion_capabilities == MotionCapabilities(
            trusted_pointer=True, wheel=True, timed_ticks=True
        )

    def test_the_wheel_source_is_padded_until_the_pointer_arrives(self):
        """G3: W3C dispatches input sources tick by tick in lockstep, so an
        unpadded wheel fires while the pointer is still travelling. The wheel
        source's first action must be a pause of pre_delay + pointer dts."""
        adapter = self._adapter()
        plan = MotionPlan(
            kind=MotionKind.WHEEL,
            pointer_ticks=(
                PointerTick(x=100, y=100, dt_ms=20),
                PointerTick(x=200, y=200, dt_ms=30),
            ),
            wheel_ticks=(WheelTick(dx=0, dy=120, dt_ms=8),),
            wheel_origin=(200, 200),
            pre_delay_ms=10,
        )
        adapter.execute_motion(plan)

        wheel_actions = _device_actions(adapter._driver)["wheel"]
        assert wheel_actions[0] == {"type": "pause", "duration": 60}, (
            "the wheel must wait out the 10ms pre-delay plus the 20+30ms "
            "approach before its first scroll"
        )
        assert [a["type"] for a in wheel_actions] == ["pause", "scroll"]


# ── Playwright ──────────────────────────────────────────────────────────────


class TestPlaywrightMotion:
    def _adapter(self):
        from auto_apply.adapters.secondary.browser import playwright_adapter as mod

        adapter = mod.PlaywrightAdapter.__new__(mod.PlaywrightAdapter)
        adapter._page = MagicMock()
        adapter._cursor_x = 0
        adapter._cursor_y = 0
        adapter._rng = random.Random(1)
        # Instance attribute set by __init__ from the js_handle_timeout_ms
        # config value; __new__ bypasses __init__, so the test supplies it.
        adapter._handle_timeout_ms = 2000
        return mod, adapter

    def test_move_mouse_by_offset_is_no_longer_a_no_op(self):
        _, adapter = self._adapter()
        adapter.move_mouse_by_offset(3, 4)
        adapter._page.mouse.move.assert_called_once_with(3, 4)
        adapter.move_mouse_by_offset(-1, 2)
        adapter._page.mouse.move.assert_called_with(2, 6)

    def test_the_fidget_no_longer_teleports(self):
        _, adapter = self._adapter()
        adapter._cursor_x, adapter._cursor_y = 500, 400
        adapter.perform_mouse_fidget()
        for call in adapter._page.mouse.move.call_args_list:
            x, y = call.args
            assert abs(x - 500) <= 5 and abs(y - 400) <= 5

    def test_execute_motion_ends_with_a_press_and_bounded_moves(self):
        _, adapter = self._adapter()
        adapter.execute_motion(_click_plan(n=25))
        adapter._page.mouse.down.assert_called_once_with()
        adapter._page.mouse.up.assert_called_once_with()
        assert adapter._page.mouse.move.call_count <= adapter._MOTION_MAX_SEGMENTS

    def test_the_wheel_origin_is_honoured_by_moving_there_first(self):
        """D4: a real wheel scrolls whatever is under the cursor."""
        _, adapter = self._adapter()
        plan = MotionPlan(
            kind=MotionKind.WHEEL,
            wheel_ticks=(WheelTick(dx=0, dy=100, dt_ms=0),),
            wheel_origin=(300, 200),
        )
        adapter.execute_motion(plan)
        adapter._page.mouse.move.assert_called_with(300, 200)
        adapter._page.mouse.wheel.assert_called_once_with(0, 100)
        assert (adapter._cursor_x, adapter._cursor_y) == (300, 200)

    def test_execute_script_bounds_handle_resolution_and_disposes(self):
        """D6: no more 30s default wait; handles are disposed after use."""
        mod, adapter = self._adapter()
        element = mod.PlaywrightElementAdapter.__new__(mod.PlaywrightElementAdapter)
        element._locator = MagicMock()
        handle = element._locator.element_handle.return_value

        adapter.execute_script("return arguments[0].id;", element)

        element._locator.element_handle.assert_called_once_with(timeout=2000)
        handle.dispose.assert_called_once_with()

    def test_execute_script_now_passes_arguments(self):
        mod, adapter = self._adapter()
        element = mod.PlaywrightElementAdapter.__new__(mod.PlaywrightElementAdapter)
        element._locator = MagicMock()
        element._locator.element_handle.return_value = "HANDLE"

        adapter.execute_script("return arguments[0] + arguments[1];", element, 5)

        expr, payload = adapter._page.evaluate.call_args.args
        assert ".apply(null, aa_args)" in expr
        assert "return arguments[0] + arguments[1];" in expr
        assert payload == ["HANDLE", 5]

    def test_execute_script_without_args_keeps_the_old_shape(self):
        _, adapter = self._adapter()
        adapter.execute_script("return 1")
        (expr,) = adapter._page.evaluate.call_args.args
        assert expr == "() => { return 1 }"

    def test_capabilities_are_honest_about_timing(self):
        _, adapter = self._adapter()
        assert adapter.motion_capabilities == MotionCapabilities(
            trusted_pointer=True, wheel=True, timed_ticks=False
        )
