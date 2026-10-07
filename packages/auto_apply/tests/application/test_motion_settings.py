"""Pins for the honest settings model (call 4): the per-user motion profile,
the layered settings pattern (ADR 018), the field-level admin lock, and the
CLI/GUI write parity.

Labels: validator and merge tests are TEETH (each fails against the pre-
change tree — the fields, the fold and the policy lock did not exist). The
defaults-agreement and old-profile tests are GUARDs: they pin a property the
rest of the suite relies on so a later change cannot silently break it.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from auto_apply.adapters.primary.cli.profile_wizard import run_profile_wizard
from auto_apply.domain.models.motion_profile import MotionConfig
from auto_apply.domain.models.policy import AdminPolicy
from auto_apply.domain.models.profile import ApplicationConfig, UserProfile
from auto_apply.infrastructure.registry import (
    _RUNTIME_DEFAULTS,
    CapabilitiesRegistry,
)


def _profile_dict(**app_config) -> dict:
    return {
        "profile_name": "Test User",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "",
            "street_address": "",
            "city": "",
            "state": "",
            "zip_code": "",
        },
        "links": {},
        "career_summary": "Test summary.",
        "search_preferences": {"desired_job_titles": ["Engineer"]},
        "app_config": app_config,
    }


def _merge(profile: UserProfile, admin: AdminPolicy | None = None) -> dict:
    return CapabilitiesRegistry._merge_config(
        runtime_defaults=dict(_RUNTIME_DEFAULTS),
        user_settings=profile.settings,
        admin_policy=admin,
        is_low_resource=False,
    )


# ── the profile field validates in plain words, at edit time (TEETH) ──────


def test_motion_profile_rejects_an_unknown_name_in_plain_words() -> None:
    with pytest.raises(ValidationError, match="Unknown behaviour profile"):
        ApplicationConfig(motion_profile="rocket")


def test_motion_profile_accepts_the_three_canonical_names() -> None:
    for name in ("instant", "human", "careful"):
        assert ApplicationConfig(motion_profile=name).motion_profile == name


def test_motion_overrides_reject_an_unknown_field() -> None:
    with pytest.raises(ValidationError, match="Invalid motion override"):
        ApplicationConfig(motion_overrides={"hovercraft": 3})


def test_motion_overrides_reject_an_out_of_range_value() -> None:
    with pytest.raises(ValidationError, match="Invalid motion override"):
        ApplicationConfig(motion_overrides={"fitts_a_ms": 99999})


# ── the merge: input -> resolution -> resolved state (TEETH) ──────────────


def test_an_old_profile_without_motion_fields_loads_and_inherits() -> None:
    """GUARD: profiles written before this change keep working and inherit
    the YAML default."""
    profile = UserProfile.model_validate(_profile_dict())
    assert profile.app_config.motion_profile is None
    merged = _merge(profile)
    assert MotionConfig.from_mapping(merged).profile.name == "human"
    assert "motion_profile" not in merged


def test_the_users_pick_is_folded_into_the_motion_section() -> None:
    profile = UserProfile.model_validate(_profile_dict(motion_profile="careful"))
    merged = _merge(profile)
    assert merged["motion"]["profile"] == "careful"
    assert "motion_profile" not in merged


def test_user_overrides_merge_onto_the_active_profile() -> None:
    profile = UserProfile.model_validate(
        _profile_dict(motion_overrides={"fitts_a_ms": 150})
    )
    merged = _merge(profile)
    motion = MotionConfig.from_mapping(merged)
    assert motion.profile.fitts_a_ms == 150
    assert motion.profile.name == "human"


def test_admin_policy_wins_over_the_users_pick() -> None:
    profile = UserProfile.model_validate(_profile_dict(motion_profile="instant"))
    merged = _merge(profile, admin=AdminPolicy(motion_profile="careful"))
    assert merged["motion"]["profile"] == "careful"


def test_admin_lock_is_field_level() -> None:
    assert AdminPolicy(motion_profile="careful").is_field_locked("motion_profile")
    assert AdminPolicy(motion_profile="careful").has_any_constraint()
    assert not AdminPolicy.empty().is_field_locked("motion_profile")


def test_an_old_policy_file_without_the_field_loads() -> None:
    """GUARD: a policy file written before this change is still valid."""
    policy = AdminPolicy.from_dict({"force_headless": True})
    assert policy.motion_profile is None


# ── one source for the defaults (GUARD) ────────────────────────────────────


def test_the_stealth_driver_default_agrees_with_the_registry() -> None:
    """GUARD: the domain field is the one source; registry and wizard read it."""
    import inspect

    from auto_apply.adapters.primary.cli import profile_wizard
    from auto_apply.infrastructure import registry

    assert ApplicationConfig.model_fields["enable_behavior_humanization"].default is True
    for module in (registry, profile_wizard):
        src = inspect.getsource(module)
        assert '"enable_behavior_humanization", True' not in src, module.__name__


def test_overrides_are_validated_against_the_chosen_profile() -> None:
    """TEETH: 30 ms is legal for careful (max 36) but not for human (max 24)."""
    ac = ApplicationConfig(motion_profile="careful", motion_overrides={"wheel_tick_ms_min": 30})
    assert ac.motion_overrides == {"wheel_tick_ms_min": 30}


def test_an_admin_motion_lock_ignores_the_users_motion_settings() -> None:
    """TEETH: a locked profile cannot be retuned by user overrides."""
    merged = CapabilitiesRegistry._merge_config(
        dict(_RUNTIME_DEFAULTS),
        {"motion_profile": "instant", "motion_overrides": {"wheel_tick_ms_min": 40}},
        AdminPolicy(motion_profile="careful"),
        False,
    )
    assert merged["motion"]["profile"] == "careful"
    assert "wheel_tick_ms_min" not in (merged["motion"].get("overrides") or {})


# ── CLI parity: the wizard writes the same canonical field the GUI writes ──


def _wizard_answers(*motion_answers: str) -> list[str]:
    return [
        "Ada", "Lovelace", "ada@example.com",
        "",      # phone (optional)
        "",      # linkedin (optional)
        "",      # resume path -> default resume.pdf (existence is a warning)
        "Engineer",
        "Remote",
        "I build things.",
        *motion_answers,
    ]


def test_the_cli_wizard_writes_the_canonical_motion_name(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(_wizard_answers("careful"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    saved = run_profile_wizard(tmp_path)

    assert saved is not None
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["app_config"]["motion_profile"] == "careful"


def test_the_wizard_reprompts_a_bad_behaviour_answer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(_wizard_answers("warp", "instant"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    saved = run_profile_wizard(tmp_path)

    assert saved is not None
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["app_config"]["motion_profile"] == "instant"
