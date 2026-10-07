"""Pins for the pure motion model and the motion configuration.

The properties the whole mouse tool stands on:

    * determinism: same seed -> identical plan; different seed -> different;
    * a click never lands at the exact centre of its target;
    * every path ends exactly on the sampled landing point;
    * wheel ticks sum to the requested distance, with the right sign;
    * a bad motion value is refused at load, naming the key and the range;
    * the legacy browser.mouse_* knobs finally have a reader.
"""
from __future__ import annotations

import random

import pytest

from auto_apply.domain.models.motion_profile import MotionConfig
from auto_apply.domain.services import motion_model

HUMAN = MotionConfig.from_mapping({}).profile
INSTANT = MotionConfig.from_mapping({"motion": {"profile": "instant"}}).profile


def _plan(seed: int, profile=HUMAN):
    return motion_model.plan_click(
        (10, 10), (400, 300), 120.0, (1366, 768), profile, random.Random(seed)
    )


# ── determinism ─────────────────────────────────────────────────────────────


def test_same_seed_produces_the_identical_plan():
    assert _plan(42) == _plan(42)


def test_different_seeds_produce_different_plans():
    assert _plan(1) != _plan(2)


def test_the_plan_is_deterministic_across_many_draws():
    for seed in range(25):
        assert _plan(seed) == _plan(seed)


# ── the landing point ───────────────────────────────────────────────────────


def test_a_click_never_lands_at_the_exact_centre():
    boxes = [
        (100.0, 100.0, 121.0, 37.0),
        (0.0, 0.0, 200.0, 40.0),
        (5.0, 5.0, 8.0, 8.0),
    ]
    rng = random.Random(7)
    for box in boxes:
        cx = int(round(box[0] + box[2] / 2.0))
        cy = int(round(box[1] + box[3] / 2.0))
        for _ in range(1000):
            assert motion_model.sample_landing_point(box, HUMAN, rng) != (cx, cy)


def test_the_landing_point_is_inside_the_box():
    rng = random.Random(11)
    box = (100.0, 100.0, 121.0, 37.0)
    for _ in range(1000):
        x, y = motion_model.sample_landing_point(box, HUMAN, rng)
        assert box[0] <= x <= box[0] + box[2]
        assert box[1] <= y <= box[1] + box[3]


def test_the_path_ends_exactly_on_the_sampled_point():
    plan = _plan(3)
    last = plan.pointer_ticks[-1]
    assert (last.x, last.y) == (400, 300)


def test_the_path_stays_inside_the_viewport():
    plan = _plan(9)
    for tick in plan.pointer_ticks:
        assert 0 <= tick.x < 1366
        assert 0 <= tick.y < 768


# ── profiles ────────────────────────────────────────────────────────────────


def test_the_default_profile_is_human():
    assert MotionConfig.from_mapping({}).profile.name == "human"


def test_instant_is_a_single_segment_move():
    plan = _plan(5, profile=INSTANT)
    assert len(plan.pointer_ticks) <= 2  # 1 segment + optional exact-landing tick


def test_every_named_profile_validates():
    for name in ("instant", "human", "careful"):
        cfg = MotionConfig.from_mapping({"motion": {"profile": name}})
        assert cfg.profile.name == name


# ── wheel ───────────────────────────────────────────────────────────────────


def test_wheel_ticks_sum_to_the_requested_distance():
    rng = random.Random(13)
    for distance in (0, 250, -250, 691, -691, 5000):
        ticks = motion_model.plan_wheel(distance, HUMAN, rng)
        if distance == 0:
            assert ticks == ()
        else:
            assert sum(t.dy for t in ticks) == distance
            assert all((t.dy > 0) == (distance > 0) for t in ticks)


def test_wheel_device_emits_whole_notches_and_verification_absorbs_the_residual():
    """A notch device never emits a partial notch (D7): 350px -> 3 whole
    notches, and the 50px residual is left to the caller's measured check."""
    profile = MotionConfig.from_mapping(
        {"motion": {"overrides": {"wheel_device": "wheel"}}}
    ).profile
    ticks = motion_model.plan_wheel(350, profile, random.Random(2))
    assert all(t.dy == 100 for t in ticks)
    assert sum(t.dy for t in ticks) == 300
    # ...but a small request still scrolls (minimum one notch).
    assert len(motion_model.plan_wheel(50, profile, random.Random(2))) == 1


# ── configuration validation ────────────────────────────────────────────────


def test_an_unknown_profile_name_is_refused_and_names_the_value():
    with pytest.raises(ValueError, match="glide"):
        MotionConfig.from_mapping({"motion": {"profile": "glide"}})


def test_an_unknown_override_key_is_refused_and_names_the_key():
    with pytest.raises(ValueError, match="hover_wobble"):
        MotionConfig.from_mapping({"motion": {"overrides": {"hover_wobble": 3}}})


def test_an_out_of_range_override_is_refused():
    with pytest.raises(ValueError):
        MotionConfig.from_mapping({"motion": {"overrides": {"hold_ms_min": 5000}}})


def test_an_inverted_range_is_refused_and_names_both_fields():
    with pytest.raises(ValueError, match="hold_ms_min"):
        MotionConfig.from_mapping(
            {"motion": {"overrides": {"hold_ms_min": 200, "hold_ms_max": 50}}}
        )


def test_overrides_apply_to_the_active_profile():
    cfg = MotionConfig.from_mapping({"motion": {"overrides": {"hold_ms_min": 90}}})
    assert cfg.profile.hold_ms_min == 90


def test_js_click_defaults_on_and_can_be_switched_off():
    assert MotionConfig.from_mapping({}).allow_js_click is True
    assert (
        MotionConfig.from_mapping({"motion": {"allow_js_click": False}}).allow_js_click
        is False
    )


def test_the_retired_browser_mouse_knobs_are_not_honoured():
    """D1: the legacy knobs never had a reader; mapping them broke startup
    on the shipped config (150px > the fidget limit) and overrode profiles."""
    cfg = MotionConfig.from_mapping(
        {
            "browser": {
                "mouse_move_steps": 4,
                "mouse_offset_min_px": 30,
                "mouse_offset_max_px": 150,
                "mouse_step_delay_min": 0.05,
                "mouse_step_delay_max": 0.2,
            }
        }
    )
    assert cfg.profile.name == "human"
    assert cfg.profile.fidget_offset_max_px == 12  # the human profile's own value


def test_the_yaml_motion_section_selects_the_default_profile():
    yaml = pytest.importorskip("yaml")
    import pathlib

    text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")
    section = yaml.safe_load(text)["motion"]
    assert section["profile"] == "human"
    assert section["allow_js_click"] is True
    assert MotionConfig.from_mapping({"motion": section}).profile.name == "human"


def test_the_shipped_runtime_defaults_build_a_motion_config():
    """D1's pin: the shipped YAML, unmodified, must resolve without raising."""
    yaml = pytest.importorskip("yaml")
    import pathlib

    text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")
    cfg = MotionConfig.from_mapping(yaml.safe_load(text))
    assert cfg.profile.name == "human"
    assert cfg.allow_js_click is True
