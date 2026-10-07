"""Pin: the pointer only ever lands on the VISIBLE part of its target.

TEETH: a button whose lower strip is clipped by its scroll pane. Before the
fix the landing point was sampled from the whole box, so some seeds landed on
the clipped strip (real Chrome: the background was clicked and the tool
reported success, about 1 click in 10 - the CI failure of 2026-10-06).
"""
import random

from auto_apply.application.services.page_action.probe import TargetProbe
from auto_apply.domain.models.motion_profile import MotionConfig
from auto_apply.domain.services import motion_model

# The /clip page of tests/integration/test_probe_real_browser.py, measured:
# pane 100..180 (y), button 156..186, so its last 6 px are clipped.
_PROBE = {
    "viewport": {"w": 1000, "h": 657},
    "box": {"x": 100.0, "y": 156.0, "w": 30.8, "h": 30.0},
    "panes": [{"x": 100, "y": 100, "w": 300, "h": 80}],
}


def test_the_clickable_box_excludes_the_clipped_strip() -> None:
    box = TargetProbe.clickable_box(_PROBE)
    assert box is not None
    assert (box["x"], box["y"], box["h"]) == (100.0, 156.0, 24.0)
    assert abs(box["w"] - 30.8) < 1e-9


def test_no_landing_point_falls_outside_the_visible_part() -> None:
    box = TargetProbe.clickable_box(_PROBE)
    assert box is not None
    profile = MotionConfig.from_mapping({}).profile
    for seed in range(2000):
        x, y = motion_model.sample_landing_point(
            (box["x"], box["y"], box["w"], box["h"]), profile, random.Random(seed)
        )
        assert 156 <= y < 180, f"seed {seed} lands at y={y}, outside the pane"


def test_a_fully_clipped_target_has_no_clickable_box() -> None:
    hidden = dict(_PROBE, box={"x": 100.0, "y": 300.0, "w": 30.0, "h": 30.0})
    assert TargetProbe.clickable_box(hidden) is None
