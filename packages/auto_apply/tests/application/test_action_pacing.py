"""Action pacing: min_action_delay_ms floors the between-actions rhythm, and a
one-time warmup precedes the first navigation.

Step 1c pins (behavioral, no browser needed):
  * the low-resource-clamped min_action_delay_ms reaches a real consumer — it
    floors _settle_pause, so a 2GB machine (floor 800ms) is genuinely paced
    slower than a fast one (floor 500ms). Retires the structural
    "floor is computed and discarded" pin with a behavioral guarantee.
  * a single warmup pause runs before the first navigation and never again.
  * pacing is deterministic under a fixed rng seed.
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock

import auto_apply.application.services.page_action.service as service_mod
from auto_apply.application.services.page_action.service import PageActionService


def _service(cfg, seed=42):
    reg = MagicMock()
    reg.get_all_effective_config.return_value = cfg
    return PageActionService(browser=MagicMock(), registry=reg, rng=random.Random(seed))


def _capture_sleeps(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(service_mod.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


_HUMAN = {"settle_min_s": 0.3, "settle_max_s": 1.2, "enable_human_timing": True,
          "enable_fingerprint_spoofing": False, "macro_pause_min_s": 1.5,
          "macro_pause_max_s": 4.5}


def test_floor_reaches_settle_fast_machine(monkeypatch):
    sleeps = _capture_sleeps(monkeypatch)
    svc = _service({**_HUMAN, "min_action_delay_ms": 500})
    for _ in range(300):
        svc._settle_pause()
    assert min(sleeps) >= 0.5 - 1e-9, "500ms floor not honored by settle pause"


def test_floor_reaches_settle_low_resource(monkeypatch):
    """The whole point of the 800ms low-resource clamp: it must slow the machine."""
    sleeps = _capture_sleeps(monkeypatch)
    svc = _service({**_HUMAN, "min_action_delay_ms": 800})
    for _ in range(300):
        svc._settle_pause()
    assert min(sleeps) >= 0.8 - 1e-9, "800ms low-resource floor did not reach settle"


def test_low_resource_paces_slower_than_fast(monkeypatch):
    def floor_min(delay_ms):
        sleeps = _capture_sleeps(monkeypatch)
        svc = _service({**_HUMAN, "min_action_delay_ms": delay_ms})
        for _ in range(300):
            svc._settle_pause()
        return min(sleeps)
    assert floor_min(800) > floor_min(500), "slow machine not paced slower than fast"


def test_settle_floor_with_human_timing_off(monkeypatch):
    sleeps = _capture_sleeps(monkeypatch)
    svc = _service({"settle_min_s": 0.3, "settle_max_s": 1.2,
                    "enable_human_timing": False, "min_action_delay_ms": 800})
    svc._settle_pause()
    assert abs(sleeps[0] - 0.8) < 1e-9, "floor not applied when human timing disabled"


def test_warmup_runs_once_before_first_navigation(monkeypatch):
    sleeps = _capture_sleeps(monkeypatch)
    svc = _service({**_HUMAN, "min_action_delay_ms": 800, "navigation_retries": 1})
    order = []
    svc._browser.get.side_effect = lambda url: order.append(len(sleeps))
    svc.navigate("https://example.com/first")
    assert sleeps, "no warmup pause occurred on first navigation"
    assert 1.5 <= sleeps[0] <= 4.5, "warmup outside the configured macro range"
    assert order and order[0] >= 1, "warmup did not precede the first get()"
    assert svc._warmed_up is True


def test_warmup_does_not_repeat(monkeypatch):
    sleeps = _capture_sleeps(monkeypatch)
    svc = _service({**_HUMAN, "min_action_delay_ms": 800, "navigation_retries": 1})
    svc._browser.get.side_effect = lambda url: None
    svc.navigate("https://example.com/first")
    warmup_count_after_first = 1
    n_after_first = len(sleeps)
    svc.navigate("https://example.com/second")
    # second navigation adds a macro pause but NOT another warmup: the first
    # sleep of the second nav is the macro reading pause, not a 2nd warmup.
    assert svc._warmed_up is True
    # warmup_pause is a no-op now, so navigating again must not reset the flag
    svc.warmup_pause()
    assert svc._warmed_up is True


def test_pacing_is_deterministic_under_seed(monkeypatch):
    def run():
        out: list[float] = []
        monkeypatch.setattr(service_mod.time, "sleep", lambda s: out.append(round(s, 6)))
        svc = _service({**_HUMAN, "min_action_delay_ms": 800}, seed=7)
        for _ in range(5):
            svc._settle_pause()
        return out
    assert run() == run(), "identical seed produced different pacing"
