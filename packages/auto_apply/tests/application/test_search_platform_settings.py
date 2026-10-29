"""Pins for the persistent search-platform setting and the admin lock.

Label honesty: the setting is new surface. Each pin names the mutation it
catches. The merge-fold pins are the ones the config ledger depends on.
"""

from __future__ import annotations

from auto_apply.domain.models.policy import AdminPolicy
from auto_apply.domain.models.profile import ApplicationConfig
from auto_apply.infrastructure.registry import (
    CapabilitiesRegistry,
    _RUNTIME_DEFAULTS,
)


def test_profile_field_normalizes_and_dedupes() -> None:
    """TEETH: stored values are lowercase, stripped, deduplicated.

    Mutation caught: storing raw input (a registry name would never match
    ' Jobvite ')."""
    config = ApplicationConfig(
        search_platforms=[" Jobvite ", "JOBVITE", "greenhouse", ""]
    )
    assert config.search_platforms == ["jobvite", "greenhouse"]


def test_profile_settings_emit_platforms_only_when_set(minimal_valid_profile) -> None:
    """TEETH: None is never emitted (it would shadow the YAML default);
    a set list is.

    Mutation caught: emitting None, or dropping the key entirely."""
    profile = minimal_valid_profile
    assert "search_platforms" not in profile.settings
    profile.app_config.search_platforms = ["jobvite"]
    assert profile.settings["search_platforms"] == ["jobvite"]


def test_merge_folds_profile_platforms_into_discovery_section() -> None:
    """TEETH: the flat profile input resolves into the nested discovery
    section the plan reads, and the flat key is gone.

    Mutation caught: leaving the flat key (two sources of truth), or
    folding without setting the engagement flag."""
    merged = CapabilitiesRegistry._merge_config(
        runtime_defaults=dict(_RUNTIME_DEFAULTS),
        user_settings={"search_platforms": ["jobvite"]},
        admin_policy=None,
        is_low_resource=False,
    )
    assert "search_platforms" not in merged
    assert merged["discovery"]["ats_platforms"] == ["jobvite"]
    assert merged["discovery"]["use_ats_site_search"] is True


def test_admin_lock_beats_the_profile() -> None:
    """TEETH: the admin lock wins over the profile, including locking the
    feature off with an empty list.

    Mutation caught: applying the profile after the lock, or treating []
    as 'no lock'."""
    merged = CapabilitiesRegistry._merge_config(
        runtime_defaults=dict(_RUNTIME_DEFAULTS),
        user_settings={"search_platforms": ["jobvite"]},
        admin_policy=AdminPolicy(search_platforms=[]),
        is_low_resource=False,
    )
    assert merged["discovery"]["ats_platforms"] == []
    assert merged["discovery"]["use_ats_site_search"] is False


def test_admin_lock_is_applied_after_config_overrides() -> None:
    """TEETH: the named lock beats even a full-section config_overrides
    replacement (the documented rule).

    Mutation caught: applying the lock before config_overrides."""
    merged = CapabilitiesRegistry._merge_config(
        runtime_defaults=dict(_RUNTIME_DEFAULTS),
        user_settings={},
        admin_policy=AdminPolicy(
            search_platforms=["jobvite"],
            config_overrides={
                "discovery": {
                    "ats_platforms": ["greenhouse"],
                    "use_ats_site_search": False,
                }
            },
        ),
        is_low_resource=False,
    )
    assert merged["discovery"]["ats_platforms"] == ["jobvite"]
    assert merged["discovery"]["use_ats_site_search"] is True
