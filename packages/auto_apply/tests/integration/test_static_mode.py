"""Static mode (no browser) end-to-end test.

Verifies that a worst-case user (no Chrome, no Playwright, no internet) can:
  - Run AA without crashing
  - Build an orchestrator in static mode (driver=None)
  - Reject APPLY tasks when capability profile has no browser
  - Build a session controller without a live browser

No browser. No internet. No API keys. Safe to run in CI.

Run:
    uv run pytest tests/integration/test_static_mode.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.session_plan import SessionPlan
from auto_apply.domain.models.work_unit import TaskType, WorkUnit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_profile_dict() -> dict:
    """A minimal valid profile dict for building a UserProfile."""
    return {
        "profile_name": "static-test-user",
        "personal_info": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@example.com",
            "phone_number": "555-000-1234",
            "street_address": "123 Main St",
            "city": "Testville",
            "state": "CA",
            "zip_code": "90210",
        },
        "links": {},
        "career_summary": (
            "Experienced software engineer with Python and automation background. "
            "Five years building production systems and open-source tools."
        ),
        "search_preferences": {
            "desired_job_titles": ["Software Engineer"],
            "preferred_locations": ["Remote"],
        },
        "politeness_settings": {},
    }


@pytest.fixture
def test_profile(minimal_profile_dict) -> UserProfile:
    """A fully validated UserProfile for static mode tests."""
    return UserProfile.model_validate(minimal_profile_dict)


@pytest.fixture
def static_capability() -> ResolvedCapabilityProfile:
    """A capability profile representing static (no-browser) mode."""
    return ResolvedCapabilityProfile(
        has_browser=False,
        browser_framework=None,
        max_browser_workers=0,
        has_spacy=False,
        has_gpt4all=False,
        has_research_consent=False,
        research_signals_active=False,
        is_low_resource=True,
        max_applications_per_session=25,
        max_concurrent_sources=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Static Capability Profile
# ─────────────────────────────────────────────────────────────────────────────

class TestStaticCapabilityProfile:
    """Verify the capability profile correctly gates task types."""

    def test_apply_task_not_allowed_in_static_mode(self, static_capability):
        """APPLY task must be rejected when capability profile has no browser."""
        assert "apply" not in static_capability.allowed_task_types, (
            "Static mode must not allow APPLY tasks — forms cannot be filled "
            "without a live browser"
        )

    def test_apply_rejected_by_can_run_task(self, static_capability):
        """can_run_task('apply') must return False in static mode."""
        assert static_capability.can_run_task("apply") is False

    def test_discover_allowed_in_static_mode(self, static_capability):
        """DISCOVER task must still be allowed in static mode."""
        assert "discover" in static_capability.allowed_task_types

    def test_vet_allowed_in_static_mode(self, static_capability):
        """VET task must still be allowed in static mode."""
        assert "vet" in static_capability.allowed_task_types

    def test_mode_name_is_static_assisted(self, static_capability):
        """The mode name should indicate static/assisted operation."""
        assert static_capability.mode_name == "STATIC_ASSISTED"

    def test_max_browser_workers_is_zero(self, static_capability):
        """No browser workers available when has_browser is False."""
        assert static_capability.max_browser_workers == 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — build_orchestrator with driver=None
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildOrchestratorStaticMode:
    """Verify the composition root can build an orchestrator without a browser."""

    def test_build_orchestrator_static_mode_succeeds(self, test_profile, tmp_path):
        """build_orchestrator(driver=None) must succeed without crashing."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        import logging
        logging.basicConfig(level=logging.WARNING)

        from auto_apply.infrastructure.composition_root import (
            CapabilitiesRegistry,
            build_orchestrator,
        )

        registry = CapabilitiesRegistry.build(user_profile=test_profile)

        try:
            orchestrator = build_orchestrator(registry, driver=None)
        except Exception as exc:
            pytest.fail(f"build_orchestrator(driver=None) raised: {exc}")

        assert orchestrator is not None, (
            "build_orchestrator must return a valid orchestrator even without a browser"
        )

    def test_build_orchestrator_static_has_workflows(self, test_profile, tmp_path):
        """The static orchestrator must have all three workflow keys."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        import logging
        logging.basicConfig(level=logging.WARNING)

        from auto_apply.infrastructure.composition_root import (
            CapabilitiesRegistry,
            build_orchestrator,
        )

        registry = CapabilitiesRegistry.build(user_profile=test_profile)
        orchestrator = build_orchestrator(registry, driver=None)

        workflows = orchestrator._workflows
        assert "DiscoveryWorkflow" in workflows
        assert "VettingWorkflow" in workflows
        assert "ApplicationsWorkflow" in workflows

    def test_build_orchestrator_static_session_plan_type(self, test_profile, tmp_path):
        """The session plan must be the canonical SessionPlan from session_plan.py."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        import logging
        logging.basicConfig(level=logging.WARNING)

        from auto_apply.infrastructure.composition_root import (
            CapabilitiesRegistry,
            build_orchestrator,
        )
        from auto_apply.domain.models.session_plan import SessionPlan as CanonicalPlan

        registry = CapabilitiesRegistry.build(user_profile=test_profile)
        orchestrator = build_orchestrator(registry, driver=None)

        plan = orchestrator.session_plan
        assert isinstance(plan, CanonicalPlan), (
            "orchestrator.session_plan must be the canonical SessionPlan from "
            "domain/models/session_plan.py, not a duplicate from session.py"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests — WorkUnit Queue Rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkUnitRejectionStaticMode:
    """APPLY WorkUnits must be rejected at queue insertion in static mode."""

    def test_database_manager_rejects_apply_in_static_mode(
        self, test_profile, tmp_path, static_capability
    ):
        """DatabaseManager.set_capability_profile must gate APPLY tasks."""
        import os
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        from auto_apply.adapters.secondary.persistence.database import DatabaseManager

        db = DatabaseManager()
        db.set_capability_profile(static_capability)

        job = Job(
            title="Engineer",
            company="Acme Corp",
            url="https://example.com/jobs/123",
            source="test",
        )

        with pytest.raises(ValueError, match="capability profile"):
            db.queue_task(WorkUnit(
                priority=1,
                task_type=TaskType.APPLY,
                payload=job,
                source="test",
            ))

    def test_database_manager_allows_discover_in_static_mode(
        self, test_profile, tmp_path, static_capability
    ):
        """DISCOVER tasks must still be allowed in static mode."""
        import os
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        from auto_apply.adapters.secondary.persistence.database import DatabaseManager

        db = DatabaseManager()
        db.set_capability_profile(static_capability)

        # DISCOVER should NOT raise — allowed in static mode
        db.queue_task(WorkUnit(
            priority=5,
            task_type=TaskType.DISCOVER,
            payload={"query": "Engineer", "location": "Remote"},
            source="test",
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Tests — SessionController in Static Mode
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionControllerStaticMode:
    """SessionController must function correctly in static mode."""

    def test_build_session_controller_static_mode(self, test_profile, tmp_path):
        """build_session_controller must succeed with a static-mode profile."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        import logging
        logging.basicConfig(level=logging.WARNING)

        from auto_apply.infrastructure.composition_root import build_session_controller

        controller = build_session_controller(test_profile)
        assert controller is not None
        assert controller.registry is not None
        assert controller.orchestrator is not None

    def test_initialize_session_discovery_mode(self, test_profile, tmp_path):
        """initialize_session must return >= 0 tasks in discovery mode."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        import logging
        logging.basicConfig(level=logging.WARNING)

        from auto_apply.infrastructure.composition_root import build_session_controller

        controller = build_session_controller(test_profile)
        task_count = controller.initialize_session({
            "mode": "discovery",
            "input": "Software Engineer",
        })

        # In static mode with no providers (no browser), this may return 0
        # but must NOT raise an exception.
        assert isinstance(task_count, int)
        assert task_count >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — SessionPlan Integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionPlanIntegrity:
    """SessionPlan must have all required fields after build."""

    def test_session_plan_has_behavior_parameters(self, test_profile):
        """The SessionPlan built by CapabilitiesRegistry includes BehaviorParameters."""
        from auto_apply.infrastructure.registry import CapabilitiesRegistry

        registry = CapabilitiesRegistry.build(user_profile=test_profile)
        plan = registry.get_session_plan()

        assert plan.behavior is not None, (
            "SessionPlan.behavior must be a BehaviorParameters instance"
        )
        assert plan.behavior.timing is not None, (
            "BehaviorParameters.timing must be a TimingProfile instance"
        )

    def test_session_plan_is_frozen(self, test_profile):
        """SessionPlan must be immutable (frozen=True)."""
        from auto_apply.infrastructure.registry import CapabilitiesRegistry

        registry = CapabilitiesRegistry.build(user_profile=test_profile)
        plan = registry.get_session_plan()

        with pytest.raises(Exception):
            plan.max_concurrency = 99  # type: ignore[misc]
