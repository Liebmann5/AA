"""Pins for C1: scroll progress is measured after the scroll settles.

Playwright's wheel returns before the page scrolls; smooth scrolling animates
afterwards. The old immediate re-probe read the PRE-scroll offset and
reported "no movement" — measured live as 1 run in 4 on Chromium 141 falling
back to the instant JS scroll. These pins fail on that code.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

from auto_apply.application.services.page_action.service import PageActionService
from auto_apply.domain.models.motion import MotionCapabilities

CAPS = MotionCapabilities(trusted_pointer=True, wheel=True, timed_ticks=True)


def _pane(top):
    return {"x": 0, "y": 0, "w": 1366, "h": 768, "top": top, "max": 3000,
            "left": 0, "maxX": 0, "ox": 683, "oy": 384}


def _probe(pane):
    return {"verdict": "ok", "viewport": {"w": 1366, "h": 768}, "panes": [pane],
            "box": {"x": 10.0, "y": 10.0, "w": 50.0, "h": 20.0}}


def _tool(probes):
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
        "enable_human_timing": False, "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0, "settle_min_s": 0.0, "settle_max_s": 0.0,
        "min_action_delay_ms": 0, "infinite_scroll_settle_s": 0.0,
        "scroll_settle_timeout_s": 0.6,
    }
    return PageActionService(browser=browser, registry=registry, rng=random.Random(7))


def test_scroll_container_waits_for_the_scroll_before_measuring():
    """TEETH: delayed movement (0,0,300,300) read 0 on the old immediate probe."""
    tool = _tool([_probe(_pane(0)), _probe(_pane(0)), _probe(_pane(0)),
                  _probe(_pane(300)), _probe(_pane(300))])
    assert tool.scroll_container(MagicMock(), 400) == 300


def test_scroll_container_reports_zero_when_nothing_moves():
    """GUARD: a pane that never moves is honestly 0, bounded by the budget."""
    tool = _tool([_probe(_pane(0))])
    assert tool.scroll_container(MagicMock(), 400) == 0


def test_scroll_into_view_does_not_give_up_on_a_delayed_wheel():
    """TEETH: a wheel that animates after execute_motion returns used to read
    as 'no movement' and fall through to the instant JS scroll."""
    offscreen = {
        "verdict": "offscreen", "viewport": {"w": 1366, "h": 768},
        "box": {"x": 400.0, "y": 2000.0, "w": 120.0, "h": 36.0},
        "panes": [_pane(0)],
    }
    moved = {
        "verdict": "ok", "viewport": {"w": 1366, "h": 768},
        "box": {"x": 400.0, "y": 300.0, "w": 120.0, "h": 36.0},
        "panes": [_pane(300)],
    }
    tool = _tool([offscreen, offscreen, moved, moved, moved])
    result = tool.scroll_into_view(MagicMock())
    assert bool(result) is True
    assert result.rung == "wheel"
    scripts = [c.args[0] for c in tool._browser.execute_script.call_args_list]
    assert not any("scrollIntoView" in s for s in scripts if isinstance(s, str))
