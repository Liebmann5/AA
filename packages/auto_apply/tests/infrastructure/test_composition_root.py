"""Tests verifying hardware‑gated model construction in composition_root."""

from unittest.mock import patch, MagicMock

import pytest

from auto_apply.domain.ports.research_consent_port import (
    ResearchConsentReason,
    ResearchConsentState,
)
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


# ─────────────────────────────────────────────────────────────────────────────
# Research consent wiring (FORK 1/4, pinned 2026-10-01)
# ─────────────────────────────────────────────────────────────────────────────


def _research_registry_stub(profile: UserProfile) -> MagicMock:
    """A registry stub in the _build_registry pattern, plus the two members
    the consent gate actually reads."""
    registry = MagicMock(spec=CapabilitiesRegistry)
    registry.get_active_profile.return_value = profile
    registry.get_runtime_profile.return_value = MagicMock(headless=False, use_stealth_driver=False)
    registry.is_low_resource_environment.return_value = False
    registry.is_research_enabled.return_value = False
    registry.is_research_offered.return_value = True
    registry.get_admin_policy.return_value = None
    registry.get_all_effective_config.return_value = dict(_RUNTIME_DEFAULTS)
    registry.get_session_plan.return_value = MagicMock()
    registry.get_allowed_browsers.return_value = []
    registry.discovery_requires_live_browser.return_value = False
    registry.get_viable_candidates.return_value = []
    registry.build_capability_profile.return_value = MagicMock(mode_name="NO_BROWSER", has_browser=False)
    return registry


def _patch_research_paths(monkeypatch, tmp_path):
    """Point the research home at tmp_path, mirroring test_research_data_home."""
    import auto_apply.infrastructure.composition_root as composition_root

    monkeypatch.setattr(composition_root, "USER_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        composition_root,
        "RESEARCH_DB_PATH",
        tmp_path / "research" / "research_signals.db",
    )
    monkeypatch.setattr(
        composition_root, "PROVENANCE_KEY_PATH", tmp_path / "provenance_key.pem"
    )
    return composition_root


def test_grant_with_salt_yields_an_active_research_observer(
    minimal_profile, tmp_path, monkeypatch
):
    """DIFFERENTIAL (M1/M2, deliverable i): granting through the consent
    interface, with a salt set and default config, makes the REAL build path
    construct and start a live research observer — visible through the consent
    service the session was built with, and as the database the aggregator
    initializes.

    RED today two ways: build_orchestrator has no research_consent parameter
    (TypeError), and its gate reads a config flag no user can set, so the
    observer is NullResearchObserver and no database appears.
    """
    monkeypatch.setenv("AA_RESEARCH_SALT", "composition-pin-salt")
    composition_root = _patch_research_paths(monkeypatch, tmp_path)
    registry = _research_registry_stub(minimal_profile)

    consent = composition_root.build_research_consent(registry)
    status = consent.grant()
    assert status.state is ResearchConsentState.ACTIVE
    assert not status.collecting_now, "nothing runs before a session build"

    orchestrator = composition_root.build_orchestrator(
        registry, driver=None, research_consent=consent
    )
    try:
        assert orchestrator is not None
        after = consent.status()
        assert after.collecting_now, (
            "a live observer must register with the consent service it was built with"
        )
        assert (tmp_path / "research" / "research_signals.db").exists()
    finally:
        consent.stop_collection()


def test_grant_without_salt_still_builds_and_reports_inactive(
    minimal_profile, tmp_path, monkeypatch
):
    """TEETH (V3, original M3/FORK-4 intent): consent granted, no
    AA_RESEARCH_SALT, and the salt file CANNOT be created — the build must
    NOT raise, research must stay clearly off, and the interface must say
    why. Rows are never written without a salt because no aggregator
    exists to write them.

    The pre-V3 version of this test encoded the pre-item-10 contract (a
    grant could never create a salt) and failed even run alone once
    grant-time provisioning landed: the state after a plain grant is
    ACTIVE by design. The intent survives unchanged — a missing salt
    never stops AA starting — so the salt is made unCREATABLE here.
    """
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    composition_root = _patch_research_paths(monkeypatch, tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    monkeypatch.setattr(
        composition_root, "RESEARCH_SALT_PATH", blocker / "research_salt.txt"
    )
    registry = _research_registry_stub(minimal_profile)

    consent = composition_root.build_research_consent(registry)
    consent.grant()

    orchestrator = composition_root.build_orchestrator(
        registry, driver=None, research_consent=consent
    )
    assert orchestrator is not None, "a missing salt must never stop AA starting"
    status = consent.status()
    assert status.state is ResearchConsentState.INACTIVE
    assert status.reason is ResearchConsentReason.NO_SALT
    assert not status.collecting_now
    assert not (tmp_path / "research" / "research_signals.db").exists()