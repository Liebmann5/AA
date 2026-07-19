"""Tests verifying hardware‑gated model construction in composition_root."""

from unittest.mock import patch, MagicMock

import pytest

from auto_apply.infrastructure.composition_root import build_orchestrator
from auto_apply.infrastructure.registry import CapabilitiesRegistry, _RUNTIME_DEFAULTS
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


def _build_registry(is_low_resource: bool, profile: UserProfile) -> CapabilitiesRegistry:
    """Return a registry stub that reports the requested low‑resource state."""
    registry = MagicMock(spec=CapabilitiesRegistry)
    registry.get_active_profile.return_value = profile
    registry.get_runtime_profile.return_value = MagicMock(headless=False, use_stealth_driver=False)
    registry.is_low_resource_environment.return_value = is_low_resource
    registry.is_research_enabled.return_value = False
    registry.get_all_effective_config.return_value = dict(_RUNTIME_DEFAULTS)
    registry.get_session_plan.return_value = MagicMock()
    registry.get_allowed_browsers.return_value = []
    registry.discovery_requires_live_browser.return_value = False
    registry.get_viable_candidates.return_value = []
    registry.build_capability_profile.return_value = MagicMock(mode_name="STATIC_ASSISTED", has_browser=False)
    return registry


@patch(
    "auto_apply.adapters.secondary.reasoning.gpt4all_adapter.GPT4AllAdapter",
    autospec=True,
)
def test_gpt4all_not_constructed_on_low_resource(mock_gpt4all, minimal_profile):
    """When low‑resource is True, GPT4AllAdapter must not be constructed."""
    registry = _build_registry(is_low_resource=True, profile=minimal_profile)

    orchestrator = build_orchestrator(registry, driver=None)

    # Verify the adapter was never instantiated.
    mock_gpt4all.assert_not_called()
    # The text generation port in VettingWorkflow should be None.
    vetting = orchestrator._workflows["VettingWorkflow"]
    assert vetting._text_generation_port is None


@patch(
    "auto_apply.adapters.secondary.reasoning.gpt4all_adapter.GPT4AllAdapter",
    autospec=True,
)
def test_gpt4all_is_constructed_on_high_resource(mock_gpt4all, minimal_profile):
    """When low‑resource is False, GPT4AllAdapter must be constructed."""
    registry = _build_registry(is_low_resource=False, profile=minimal_profile)

    orchestrator = build_orchestrator(registry, driver=None)

    # The adapter should have been instantiated exactly once.
    mock_gpt4all.assert_called_once()
    # The port must be the instance returned by the mock (or verified to be non-None).
    vetting = orchestrator._workflows["VettingWorkflow"]
    assert vetting._text_generation_port is not None