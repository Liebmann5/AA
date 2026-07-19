"""Tests verifying BrowserLeaseManager injection in composition_root."""

from unittest.mock import patch, MagicMock

import pytest

from auto_apply.infrastructure.composition_root import build_orchestrator
from auto_apply.infrastructure.registry import CapabilitiesRegistry, _RUNTIME_DEFAULTS
from auto_apply.domain.models.profile import UserProfile


def _build_registry() -> MagicMock:
    """Return a registry stub with enough attributes to satisfy build_orchestrator."""
    registry = MagicMock(spec=CapabilitiesRegistry)
    registry.get_active_profile.return_value = _make_profile()
    registry.get_runtime_profile.return_value = MagicMock()
    registry.is_low_resource_environment.return_value = False
    registry.is_research_enabled.return_value = False
    registry.get_all_effective_config.return_value = dict(_RUNTIME_DEFAULTS)
    registry.get_session_plan.return_value = MagicMock()
    registry.get_allowed_browsers.return_value = []
    registry.discovery_requires_live_browser.return_value = False
    registry.get_viable_candidates.return_value = []
    registry.build_capability_profile.return_value = MagicMock()
    return registry


def _make_profile() -> UserProfile:
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


def test_discovery_workflow_receives_lease_when_driver_available():
    """When a browser driver is available, DiscoveryWorkflow._browser_lease is not None."""
    registry = _build_registry()
    # Force driver != None via a manual argument.
    orchestrator = build_orchestrator(registry, driver=MagicMock())

    discovery = orchestrator._workflows.get("DiscoveryWorkflow")
    assert discovery is not None
    assert getattr(discovery, "_browser_lease", None) is not None


def test_browser_lease_capacity_is_one():
    """The lease's semaphore must have capacity 1, never higher."""
    registry = _build_registry()
    orchestrator = build_orchestrator(registry, driver=MagicMock())

    lease = orchestrator._workflows["DiscoveryWorkflow"]._browser_lease
    # The semaphore is a private attribute; accessing via _semaphore.
    sem = getattr(lease, "_semaphore", None)
    assert sem is not None
    # Semaphore._value on a BoundedSemaphore is the current active permits;
    # initial value equals max_concurrent.
    assert sem._value == 1


def test_lease_capacity_ignores_max_concurrent_config():
    """Even when max_concurrent_sources is set high, the lease stays at 1."""
    registry = _build_registry()
    config_overrides = dict(_RUNTIME_DEFAULTS)
    config_overrides["discovery"] = {
        **config_overrides["discovery"],
        "max_concurrent_sources": 4,
    }
    registry.get_all_effective_config.return_value = config_overrides

    orchestrator = build_orchestrator(registry, driver=MagicMock())

    lease = orchestrator._workflows["DiscoveryWorkflow"]._browser_lease
    assert getattr(lease, "_semaphore")._value == 1


def test_lease_not_created_when_no_driver():
    """Without a driver, DiscoveryWorkflow._browser_lease must be None."""
    registry = _build_registry()
    orchestrator = build_orchestrator(registry, driver=None)

    discovery = orchestrator._workflows["DiscoveryWorkflow"]
    assert getattr(discovery, "_browser_lease", None) is None