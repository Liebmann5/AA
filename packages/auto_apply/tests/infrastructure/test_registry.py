"""Tests for CapabilitiesRegistry low‑resource hardware detection and runtime consistency."""

from unittest.mock import patch

import pytest

from auto_apply.adapters.secondary.os.hardware import HardwareSnapshot
from auto_apply.infrastructure.registry import CapabilitiesRegistry
from auto_apply.domain.models.profile import UserProfile


@pytest.fixture
def minimal_profile():
    return UserProfile.model_validate({
        "profile_name": "test",
        "personal_info": {
            "first_name": "T",
            "last_name": "U",
            "email": "t@example.com",
            "phone_number": "000",
            "street_address": "",
            "city": "",
            "state": "",
            "zip_code": "",
        },
        "links": {},
        "career_summary": "A test profile for validation purposes, written to satisfy the fifty character minimum length requirement.",
        "search_preferences": {
            "desired_job_titles": ["Developer"],
            "preferred_locations": ["Remote"],
        },
        "politeness_settings": {},
    })


def test_is_low_resource_true_when_ram_below_threshold(minimal_profile):
    """When hardware reports < 2048 MB RAM, low‑resource mode is active."""
    low_ram_snapshot = HardwareSnapshot(
        cpu_cores=2,
        ram_mb=1024,          # below 2048
        disk_free_mb=2048,
    )
    with patch("auto_apply.infrastructure.registry.HardwareInspector.inspect", return_value=low_ram_snapshot):
        registry = CapabilitiesRegistry.build(user_profile=minimal_profile)
    assert registry.is_low_resource_environment() is True


def test_is_low_resource_true_when_cpu_cores_below_threshold(minimal_profile):
    """When hardware reports < 2 cores, low‑resource mode is active."""
    low_cpu_snapshot = HardwareSnapshot(
        cpu_cores=1,           # below 2
        ram_mb=4096,
        disk_free_mb=2048,
    )
    with patch("auto_apply.infrastructure.registry.HardwareInspector.inspect", return_value=low_cpu_snapshot):
        registry = CapabilitiesRegistry.build(user_profile=minimal_profile)
    assert registry.is_low_resource_environment() is True


def test_is_low_resource_true_when_disk_below_threshold(minimal_profile):
    """When hardware reports < 512 MB free disk, low‑resource mode is active."""
    low_disk_snapshot = HardwareSnapshot(
        cpu_cores=4,
        ram_mb=4096,
        disk_free_mb=256,      # below 512
    )
    with patch("auto_apply.infrastructure.registry.HardwareInspector.inspect", return_value=low_disk_snapshot):
        registry = CapabilitiesRegistry.build(user_profile=minimal_profile)
    assert registry.is_low_resource_environment() is True


def test_is_low_resource_false_when_adequate_hardware(minimal_profile):
    """When hardware meets or exceeds all thresholds, low‑resource mode is off."""
    adequate_snapshot = HardwareSnapshot(
        cpu_cores=4,
        ram_mb=4096,
        disk_free_mb=4096,
    )
    with patch("auto_apply.infrastructure.registry.HardwareInspector.inspect", return_value=adequate_snapshot):
        registry = CapabilitiesRegistry.build(user_profile=minimal_profile)
    assert registry.is_low_resource_environment() is False


def test_runtime_max_concurrency_capped_by_session_plan(minimal_profile):
    """RuntimeProfile.max_concurrency must never exceed SessionPlan.max_concurrency.

    The session plan's max_concurrency is derived from
    discovery.max_concurrent_sources, which defaults to 1 (and carries a
    comment that it MUST BE 1 when sharing a single live browser).  Even on
    high‑resource hardware, the runtime profile must respect that ceiling.
    """
    high_hw = HardwareSnapshot(
        cpu_cores=8,
        ram_mb=16384,   # 16 GB
        disk_free_mb=20480,
    )
    with patch("auto_apply.infrastructure.registry.HardwareInspector.inspect", return_value=high_hw):
        registry = CapabilitiesRegistry.build(user_profile=minimal_profile)

    runtime = registry.get_runtime_profile()
    plan = registry.get_session_plan()

    assert runtime.max_concurrency <= plan.max_concurrency
    # With the safe default of 1, the runtime profile must also be 1.
    assert runtime.max_concurrency == 1