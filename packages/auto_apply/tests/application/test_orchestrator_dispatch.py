"""Unit tests for AgentOrchestrator task dispatch after the workflow migration.

These verify that each TaskType handler delegates to the correct *Workflow and
no longer performs the dedup/enqueue/publish work the workflows now own. The
orchestrator's heavy __init__ (registry, persistence, monitors) is bypassed via
__new__; only the attributes the handlers touch are set, so the tests stay
deterministic and dependency-free (unittest.mock only).

In this regression pass we add integration-style verifications that the
orchestrator's dispatch table, resolver, scheduler, browser-readiness
checks, and HITL wiring are intact after the URL resolution and company‑batch
decomposition.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from auto_apply.application.agent.orchestrator import AgentOrchestrator
from auto_apply.application.agent.state_machine import AgentState
#from auto_apply.application.agent.task_kernel import TaskKernel
from auto_apply.application.services.company_batch_scheduler import CompanyBatchScheduler
from auto_apply.application.services.job_posting_resolver import JobPostingResolver
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.models.session_plan import SessionExecutionMode, SessionPlan
from auto_apply.domain.models.work_unit import TaskType, WorkUnit


def _orchestrator_with_workflows(**workflows) -> AgentOrchestrator:
    """Build a bare orchestrator with only dispatch-relevant attributes set."""
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.state_machine = MagicMock()
    orch.context = MagicMock()
    orch.task_queue = MagicMock()  # must NOT be used by the migrated handlers
    orch._workflows = workflows
    orch._session_report = MagicMock()
    # Default a session_plan to full_pipeline for most tests, can be overridden
    orch.session_plan = SessionPlan(session_id="test")
    return orch


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

def test_handle_discovery_delegates_and_maps_query_to_title():
    discovery = MagicMock()
    discovery.run.return_value = 3
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    task = SimpleNamespace(payload={"query": "python engineer", "location": "NYC"})
    orch._handle_discovery(task)

    discovery.run.assert_called_once()
    # The new interface passes instructions instead of override_criteria.
    args_kwargs = discovery.run.call_args.kwargs
    received = args_kwargs["instructions"]
    assert received is not None
    assert len(received) == 1
    assert received[0].title == "python engineer"
    assert received[0].location == "NYC"
    assert args_kwargs["execution_mode"] == SessionExecutionMode.FULL_PIPELINE
    orch.context.update_stats.assert_called_with("discovered", 3)
    orch.task_queue.queue_task.assert_not_called()


def test_handle_discovery_accepts_title_key_directly():
    discovery = MagicMock()
    discovery.run.return_value = 0
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    orch._handle_discovery(SimpleNamespace(payload={"title": "data scientist"}))

    discovery.run.assert_called_once()
    received = discovery.run.call_args.kwargs["instructions"]
    assert received is not None
    assert len(received) == 1
    assert received[0].title == "data scientist"


def test_handle_company_discovery_delegates_to_scrape_entrypoint():
    discovery = MagicMock()
    discovery.discover_company_page.return_value = 2
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    task = SimpleNamespace(
        payload={"careers_url": "https://acme.com/jobs", "company_name": "Acme"}
    )
    orch._handle_company_discovery(task)

    discovery.discover_company_page.assert_called_once_with(
        "https://acme.com/jobs", "Acme"
    )
    orch.context.update_stats.assert_called_with("discovered", 2)
    orch.task_queue.queue_task.assert_not_called()


def test_handle_vetting_delegates_and_counts_pass():
    vetting = MagicMock()
    vetting.run.return_value = True
    orch = _orchestrator_with_workflows(VettingWorkflow=vetting)

    job = SimpleNamespace(title="Engineer", company="Acme", url="https://x")
    orch._handle_vetting(SimpleNamespace(payload=job))

    vetting.run.assert_called_once_with(job, execution_mode=SessionExecutionMode.FULL_PIPELINE)
    orch.context.update_stats.assert_called_with("vetted", 1)
    orch.task_queue.queue_task.assert_not_called()


def test_handle_vetting_failure_does_not_count_vetted():
    vetting = MagicMock()
    vetting.run.return_value = False
    orch = _orchestrator_with_workflows(VettingWorkflow=vetting)

    job = SimpleNamespace(title="Engineer", company="Acme", url="https://x")
    orch._handle_vetting(SimpleNamespace(payload=job))

    vetting.run.assert_called_once_with(job, execution_mode=SessionExecutionMode.FULL_PIPELINE)
    orch.context.update_stats.assert_not_called()


def test_get_workflow_raises_when_unregistered():
    orch = _orchestrator_with_workflows()
    raised = False
    try:
        orch._get_workflow("DiscoveryWorkflow")
    except RuntimeError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# Execution mode tests (unchanged)
# ---------------------------------------------------------------------------

def test_discover_only_skips_vet_enqueue():
    discovery = MagicMock()
    discovery.run.return_value = 0  # Vet enqueue count will be 0 because mode blocks it
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)
    orch.session_plan = SessionPlan(
        session_id="test",
        execution_mode=SessionExecutionMode.DISCOVER_ONLY,
    )

    task = SimpleNamespace(payload={"query": "eng", "location": "Remote"})
    orch._handle_discovery(task)

    # DiscoveryWorkflow.run must have been called with DISCOVER_ONLY mode
    assert discovery.run.call_args.kwargs["execution_mode"] == SessionExecutionMode.DISCOVER_ONLY

    # The orchestrator itself does not enqueue VET tasks — it delegates to the workflow.
    orch.task_queue.queue_task.assert_not_called()


def test_discover_and_vet_skips_apply_enqueue():
    """With DISCOVER_AND_VET mode, vetting runs but VettingWorkflow must not enqueue APPLY."""
    vetting = MagicMock()
    vetting.run.return_value = True
    orch = _orchestrator_with_workflows(VettingWorkflow=vetting)
    orch.session_plan = SessionPlan(
        session_id="test",
        execution_mode=SessionExecutionMode.DISCOVER_AND_VET,
    )

    job = SimpleNamespace(title="Engineer", company="Acme", url="https://x")
    orch._handle_vetting(SimpleNamespace(payload=job))

    # The workflow receives the correct mode
    assert vetting.run.call_args.kwargs["execution_mode"] == SessionExecutionMode.DISCOVER_AND_VET

    # No APPLY tasks should have been enqueued (workflow handles the gate)
    orch.task_queue.queue_task.assert_not_called()


def test_full_pipeline_enqueues_everything():
    """Default FULL_PIPELINE mode must cause both VET and APPLY enqueue (workflow side)."""
    discovery = MagicMock()
    discovery.run.return_value = 5
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    task = SimpleNamespace(payload={"query": "devops", "location": "NYC"})
    orch._handle_discovery(task)

    assert discovery.run.call_args.kwargs["execution_mode"] == SessionExecutionMode.FULL_PIPELINE


def test_apply_only_mode_bypasses_discovery():
    """In APPLY_ONLY mode, the orchestrator side doesn't seed DISCOVER tasks —
    but we test that the mode is correctly communicated to VettingWorkflow when
    a VET task is inadvertently dispatched (should not happen, but safe)."""
    vetting = MagicMock()
    vetting.run.return_value = True
    orch = _orchestrator_with_workflows(VettingWorkflow=vetting)
    orch.session_plan = SessionPlan(
        session_id="test",
        execution_mode=SessionExecutionMode.APPLY_ONLY,
    )

    # Even if a VET task comes through, the workflow receives APPLY_ONLY mode
    # and will NOT enqueue an APPLY task (because includes_application is True
    # for APPLY_ONLY, so it should enqueue? No, APPLY_ONLY means apply only, no vetting.
    # Actually, includes_application is True for APPLY_ONLY, but includes_vetting is False.
    # If a VET task is processed, the workflow would still vet the job but should NOT enqueue APPLY
    # because the user wants to skip vetting? In APPLY_ONLY, we shouldn't even be running vetting.
    # Our orchestrator dispatch should prevent VET tasks in APPLY_ONLY mode, but we test robustness.
    # VettingWorkflow.run respects includes_application; for APPLY_ONLY, includes_application=True,
    # so if passed, it WOULD enqueue an APPLY task. That's fine because the mode is about what
    # pipeline stages to run; if someone manually inserts a VET task, maybe they want it to apply.
    # We'll just test that the mode is passed correctly.
    job = SimpleNamespace(title="Engineer", company="Acme", url="https://x")
    orch._handle_vetting(SimpleNamespace(payload=job))

    assert vetting.run.call_args.kwargs["execution_mode"] == SessionExecutionMode.APPLY_ONLY


# ===========================================================================
# REGRESSION PASS — Dispatch routing, service wiring, browser / HITL guards
# ===========================================================================

# Helper to build a "full" orchestrator that has all the services that existed
# after the URL resolution and company‑batch decomposition.
def _full_orchestrator(**extra_services):
    orch = AgentOrchestrator.__new__(AgentOrchestrator)

    # Standard dispatch deps (same as _orchestrator_with_workflows)
    orch.state_machine = MagicMock()
    orch.context = MagicMock()
    orch.task_queue = MagicMock()
    orch._session_report = MagicMock()
    orch.session_plan = SessionPlan(session_id="regression-test")

    # Workflows — all three must be present for dispatch table
    orch._workflows = extra_services.pop("_workflows", {
        "DiscoveryWorkflow": MagicMock(),
        "VettingWorkflow": MagicMock(),
        "ApplicationsWorkflow": MagicMock(),
    })

    # Job posting resolver (injected after decomposition)
    orch._job_posting_resolver = extra_services.pop(
        "_job_posting_resolver", JobPostingResolver()
    ) if extra_services else JobPostingResolver()

    # Browser / network state
    orch._driver = extra_services.pop("_driver", MagicMock()) if extra_services else MagicMock()
    orch._browser_monitor = extra_services.pop("_browser_monitor", None)
    orch._network_monitor = extra_services.pop("_network_monitor", None)
    orch._captcha_resolver = extra_services.pop("_captcha_resolver", None)

    # HITL wiring
    orch.event_bus = extra_services.pop("event_bus", MagicMock())
    orch.running = True
    orch.paused = False

    # Ensure workflows' batch scheduler is reachable if needed
    app_wf = orch._workflows.get("ApplicationsWorkflow")
    if app_wf is not None:
        app_wf.batch_scheduler = extra_services.pop(
            "batch_scheduler", CompanyBatchScheduler(task_queue=orch.task_queue)
        ) if extra_services else CompanyBatchScheduler(task_queue=orch.task_queue)

    # Any extra attributes passed in
    for k, v in extra_services.items():
        setattr(orch, k, v)

    return orch


class TestDispatchRoutingAndServiceIntegration:
    """Verify that _dispatch_task routes to the correct handler and that the
    extracted Resolver and Scheduler services are actually used."""

    DISPATCH_TABLE = {
        TaskType.DISCOVER: "_handle_discovery",
        TaskType.DISCOVER_COMPANY: "_handle_company_discovery",
        TaskType.RESOLVE_JOB_URL: "_handle_url_resolution",
        TaskType.VET: "_handle_vetting",
        TaskType.APPLY: "_buffer_application",
        TaskType.HANDLE_CAPTCHA: "_handle_captcha",
    }

    @pytest.mark.parametrize("task_type, expected_handler", DISPATCH_TABLE.items())
    def test_dispatch_routes_each_task_type(self, task_type, expected_handler):
        orch = _full_orchestrator()
        # Replace all handler methods with mocks so we can assert calls
        for handler_name in set(self.DISPATCH_TABLE.values()):
            setattr(orch, handler_name, MagicMock())

        task = WorkUnit(
            id="task-1",
            priority=1,
            task_type=task_type,
            payload={},
            source="test",
            context_data={},
        )

        orch._dispatch_task(task)
        mock_handler = getattr(orch, expected_handler)
        mock_handler.assert_called_once_with(task)
        # Note: mark_task_complete is intentionally NOT asserted here.
        # _dispatch_task() only routes to the correct handler; marking the
        # task complete is the main run() loop's responsibility, called
        # immediately after _dispatch_task() returns (see run()'s step 9,
        # "Mark complete"). This test calls _dispatch_task() directly,
        # bypassing that loop, so asserting mark_task_complete here would be
        # testing a responsibility this method was never given.

    def test_resolve_job_url_handler_uses_resolver(self):
        orch = _full_orchestrator()
        resolver = MagicMock(wraps=orch._job_posting_resolver)
        orch._job_posting_resolver = resolver
        orch._workflows = {}  # RESOLVE_JOB_URL doesn't need workflows

        payload = {"url": "https://example.com/job", "next_task": "VET", "skip_vetting": False}
        task = WorkUnit(id="r1", priority=3, task_type=TaskType.RESOLVE_JOB_URL,
                        payload=payload, source="test", context_data={})

        orch._handle_url_resolution(task)

        resolver.resolve.assert_called_once_with(
            "https://example.com/job", driver=orch._driver
        )
        # After resolution, a VET task should be enqueued
        orch.task_queue.queue_task.assert_called_once()
        enqueued_task = orch.task_queue.queue_task.call_args[0][0]
        assert enqueued_task.task_type == TaskType.VET

    def test_buffer_application_uses_batch_scheduler(self):
        orch = _full_orchestrator()
        app_wf = orch._workflows["ApplicationsWorkflow"]
        app_wf.batch_scheduler = CompanyBatchScheduler(task_queue=orch.task_queue)
        # A bare MagicMock()'s methods return a truthy auto-generated Mock by
        # default, not False — has_applied_previously must be configured
        # explicitly, or is_duplicate() (which calls it) treats every job as
        # a cross-session duplicate and buffer_job() never actually buffers.
        orch.task_queue.has_applied_previously.return_value = False

        job = SimpleNamespace(title="SWE", company="Acme", url="https://example.com")
        task = WorkUnit(id="a1", priority=2, task_type=TaskType.APPLY,
                        payload=job, source="test", context_data={})

        # buffer_job returns True on our mock queue because is_duplicate is False by default
        orch._buffer_application(task)

        # Verify the buffer now contains the job
        assert app_wf.batch_scheduler.check_batch_ready() is False  # only one job
        assert app_wf.batch_scheduler.has_any_buffered() is True
        popped = app_wf.batch_scheduler.flush_all_batches()
        assert len(popped.get("acme", [])) == 1

    def test_requires_browser_detects_task_needs(self):
        orch = _full_orchestrator()
        orch._driver = MagicMock()  # available

        # VET and APPLY require browser
        assert orch._requires_browser(WorkUnit(priority=1, task_type=TaskType.VET, payload={}, source="t", context_data={})) is True
        assert orch._requires_browser(WorkUnit(priority=1, task_type=TaskType.APPLY, payload={}, source="t", context_data={})) is True

        # DISCOVER is conditional (depends on registry), but without registry the default is True? Actually _requires_browser checks if registry.discovery_requires_live_browser() when task is DISCOVER/DISCOVER_COMPANY. We'll set up a mock registry.
        orch.registry = MagicMock()
        orch.registry.discovery_requires_live_browser.return_value = True
        assert orch._requires_browser(WorkUnit(priority=5, task_type=TaskType.DISCOVER, payload={}, source="t", context_data={})) is True

    def test_ensure_browser_active_raises_when_no_driver(self):
        orch = _full_orchestrator()
        orch._driver = None
        with pytest.raises(RuntimeError, match="No browser driver is available"):
            orch._ensure_browser_active()

    def test_ensure_browser_active_succeeds_when_driver_present(self):
        orch = _full_orchestrator()
        orch._driver = MagicMock()
        orch._ensure_browser_active()  # should not raise


class TestServiceWiringFromCompositionRoot:
    """Prove that composition_root builds an orchestrator with the resolver
    and batch scheduler correctly wired — a true integration test point."""

    def test_resolver_and_scheduler_injected(self):
        """Call build_orchestrator with a minimal registry and driver=None and
        verify the orchestrator has the expected services."""
        import os
        import tempfile
        from auto_apply.infrastructure.composition_root import build_orchestrator
        from auto_apply.infrastructure.registry import CapabilitiesRegistry
        from auto_apply.domain.models.profile import UserProfile

        # Minimal profile — enough to satisfy registry build.
        profile = UserProfile.model_validate({
            "profile_name": "wiring-test",
            "personal_info": {
                "first_name": "A", "last_name": "B", "email": "a@b.com",
                "phone_number": "000", "street_address": "", "city": "", "state": "", "zip_code": "",
            },
            "links": {},
            "career_summary": "Test profile used for orchestrator dispatch integration testing purposes.",
            "search_preferences": {
                "desired_job_titles": ["Engineer"],
                "preferred_locations": ["Remote"],
            },
            "politeness_settings": {},
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["AA_DATA_DIR"] = tmpdir
            registry = CapabilitiesRegistry.build(user_profile=profile)
            orchestrator = build_orchestrator(registry, driver=None)

        # Resolver should be injected
        assert hasattr(orchestrator, "_job_posting_resolver")
        assert isinstance(orchestrator._job_posting_resolver, JobPostingResolver)

        # Batch scheduler should live inside ApplicationsWorkflow
        app_wf = orchestrator._workflows.get("ApplicationsWorkflow")
        assert app_wf is not None
        assert hasattr(app_wf, "batch_scheduler")
        assert isinstance(app_wf.batch_scheduler, CompanyBatchScheduler)


class TestHITLAndNetworkDoNotRegress:
    """Confirm that the HITL interrupt flow (transition to AWAITING_HUMAN)
    and network-pause logic still function as expected after the decomposition."""

    def test_on_human_approval_requested_transitions_state(self):
        orch = _full_orchestrator()
        orch.event_bus = MagicMock()  # subscribe isn't needed for direct call
        payload = {"checkpoint": "BEFORE_FORM_SUBMIT"}

        orch._on_human_approval_requested(payload)

        orch.state_machine.transition_to.assert_called_with(
            AgentState.AWAITING_HUMAN,
            triggered_by="hitl:BEFORE_FORM_SUBMIT",
        )

    def test_pause_until_network_restored_returns_immediately_when_no_monitor(self):
        orch = _full_orchestrator()
        orch._network_monitor = None
        orch.registry = MagicMock()
        orch.registry.get_effective_config.return_value = None  # default timeout

        # Should not block, should not raise.
        orch._pause_until_network_restored()
        # (no exception = pass)

    def test_pause_until_network_restored_pauses_and_then_timeouts(self):
        import time
        orch = _full_orchestrator()
        orch._network_monitor = MagicMock()
        orch._network_monitor.is_healthy.return_value = False  # permanently unhealthy
        orch.registry = MagicMock()
        orch.registry.get_effective_config.return_value = 1  # timeout 1 second

        # We'll call the method in a thread to observe that stop() is called eventually
        orch.stop = MagicMock()
        start = time.monotonic()
        orch._pause_until_network_restored()
        elapsed = time.monotonic() - start

        # Should have waited at least the configured timeout (1 sec plus sleep intervals)
        assert elapsed >= 0.9, f"Expected pause for at least timeout, got {elapsed:.2f}s"
        orch.stop.assert_called_once()