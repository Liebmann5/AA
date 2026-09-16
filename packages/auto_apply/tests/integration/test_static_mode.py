"""The no-browser contract: what AA does when no browser can be launched.

For years this file pinned "static mode" — a fallback that claimed AA could
run with no browser at all. That mode never existed: no discovery provider
runs without a driver, so STATIC_ASSISTED was a name with no capability
behind it. The pretence was deleted 2026-09-09 (predicate 2 / P6); this file
now pins the honest contract that replaced it:

    * has_browser=False yields an EMPTY allowed_task_types and the mode name
      NO_BROWSER on ResolvedCapabilityProfile;
    * DatabaseManager.queue_task rejects DISCOVER for the same reason it
      already rejected APPLY;
    * an explicit driver=None still builds — a construction-time sentinel the
      suite relies on (documented, and called out as an open question), while
      a cascade that actually ran and exhausted refuses startup with
      BrowserSetupError (pinned in test_interaction_tool_wiring.py and
      test_dom_readiness.py).

No browser. No internet. No API keys. Safe to run in CI.

Run:
    uv run pytest tests/integration/test_static_mode.py -v
"""

from __future__ import annotations

import os

import pytest

from auto_apply.domain.models.capability_profile import ResolvedCapabilityProfile
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.work_unit import TaskType, WorkUnit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_profile_dict() -> dict:
    """A minimal valid profile dict for building a UserProfile."""
    return {
        "profile_name": "no-browser-test-user",
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
    """A fully validated UserProfile for the no-browser tests."""
    return UserProfile.model_validate(minimal_profile_dict)


@pytest.fixture
def no_browser_capability() -> ResolvedCapabilityProfile:
    """A capability profile representing the no-browser environment.

    With no browser available, every task type must be refused — there is no
    static fallback anymore.
    """
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
# Tests — No-Browser Capability Profile
# ─────────────────────────────────────────────────────────────────────────────

class TestNoBrowserCapabilityProfile:
    """The capability profile must refuse every task type with no browser.

    The APPLY assertions hold on both the old and new trees (APPLY was never
    allowed without a browser, static or not) — they are characterization of
    the retained contract, not inversions. The DISCOVER/VET/mode-name pins
    discriminate: they fail against the pre-P6 static-mode world for exactly
    the reason their names give.
    """

    def test_apply_task_not_allowed_without_browser(self, no_browser_capability):
        """APPLY must be refused — forms cannot be filled without a browser."""
        assert "apply" not in no_browser_capability.allowed_task_types

    def test_apply_rejected_by_can_run_task(self, no_browser_capability):
        """can_run_task('apply') must return False with no browser."""
        assert no_browser_capability.can_run_task("apply") is False

    def test_discover_not_allowed_without_browser(self, no_browser_capability):
        """INVERTED: DISCOVER used to be 'allowed' in static mode.

        The fallback that supposedly ran it was never implemented — no
        discovery provider exists that runs without a driver. With no browser,
        discovery must be refused like everything else.
        """
        assert "discover" not in no_browser_capability.allowed_task_types
        assert no_browser_capability.can_run_task("discover") is False

    def test_vet_not_allowed_without_browser(self, no_browser_capability):
        """INVERTED: VET used to be 'allowed' in static mode.

        Vetting reads a live page; without a browser there is nothing to read.
        """
        assert "vet" not in no_browser_capability.allowed_task_types
        assert no_browser_capability.can_run_task("vet") is False

    def test_mode_name_is_no_browser(self, no_browser_capability):
        """The mode name reports NO_BROWSER, not the deleted STATIC_ASSISTED."""
        assert no_browser_capability.mode_name == "NO_BROWSER"

    def test_max_browser_workers_is_zero(self, no_browser_capability):
        """No browser workers available when has_browser is False."""
        assert no_browser_capability.max_browser_workers == 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — build_orchestrator with the driver=None sentinel
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildOrchestratorWithoutDriverSentinel:
    """An explicit driver=None still builds: the construction-time sentinel.

    build_orchestrator(registry, driver=None) skips the browser cascade, so
    the startup refusal does NOT fire here. That sentinel is what most of the
    suite relies on to exercise the wiring graph without a browser; the
    refusal itself is pinned separately in test_interaction_tool_wiring.py
    and test_dom_readiness.py. Whether the sentinel should exist at all is an
    open question (predicate 2) — these tests pin what it currently does, not
    what it should do.
    """

    def test_build_orchestrator_without_driver_sentinel_succeeds(
        self, test_profile, tmp_path
    ):
        """build_orchestrator(registry, driver=None) must complete without crashing."""
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
            "build_orchestrator must return a valid orchestrator when the "
            "driver=None sentinel skips the cascade"
        )

    def test_build_orchestrator_without_driver_has_workflows(
        self, test_profile, tmp_path
    ):
        """The sentinel-built orchestrator must have all three workflow keys."""
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

    def test_build_orchestrator_without_driver_session_plan_type(
        self, test_profile, tmp_path
    ):
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

class TestWorkUnitRejectionWithoutBrowser:
    """queue_task must reject both APPLY and DISCOVER when no browser exists.

    DatabaseManager is a singleton: every DB-touching test re-sets the
    capability profile before asserting, so test order cannot leak state from
    one test into another.
    """

    def test_database_manager_rejects_apply_without_browser(
        self, test_profile, tmp_path, no_browser_capability
    ):
        """APPLY WorkUnits must be rejected at queue insertion with no browser."""
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        from auto_apply.adapters.secondary.persistence.database import DatabaseManager

        db = DatabaseManager()
        db.set_capability_profile(no_browser_capability)

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

    def test_database_manager_rejects_discover_without_browser(
        self, test_profile, tmp_path, no_browser_capability
    ):
        """INVERTED: DISCOVER WorkUnits used to be queued in static mode.

        The static fallback that supposedly ran them is deleted, so the gate
        that already rejected APPLY must reject DISCOVER the same way.
        """
        os.environ["AA_DATA_DIR"] = str(tmp_path)

        from auto_apply.adapters.secondary.persistence.database import DatabaseManager

        db = DatabaseManager()
        db.set_capability_profile(no_browser_capability)

        with pytest.raises(ValueError, match="capability profile"):
            db.queue_task(WorkUnit(
                priority=5,
                task_type=TaskType.DISCOVER,
                payload={"query": "Engineer", "location": "Remote"},
                source="test",
            ))


# ─────────────────────────────────────────────────────────────────────────────
# Tests — SessionController on a machine with a working cascade
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionControllerWithWorkingCascade:
    """build_session_controller exercises the full build path on this machine.

    NOTE — environment-dependent: build_session_controller calls
    build_orchestrator(registry) with NO driver argument, so the cascade runs
    for real. On a machine with a launchable browser these tests build; on a
    machine without one they now fail on BrowserSetupError — which is the
    intended refusal. They are not environment-independent, and they are kept
    deliberately: the full user-facing boot path is exactly what should be
    exercised here.
    """

    def test_build_session_controller_succeeds(self, test_profile, tmp_path):
        """build_session_controller must succeed when the cascade can launch a browser."""
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

        # In a no-provider environment (no browser on this machine), this may
        # return 0 but must NOT raise an exception.
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
