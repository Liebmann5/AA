"""Unit tests for AgentOrchestrator task dispatch after the workflow migration.

These verify that each TaskType handler delegates to the correct *Workflow and
no longer performs the dedup/enqueue/publish work the workflows now own. The
orchestrator's heavy __init__ (registry, persistence, monitors) is bypassed via
__new__; only the attributes the handlers touch are set, so the tests stay
deterministic and dependency-free (unittest.mock only).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.application.agent.orchestrator import AgentOrchestrator


def _orchestrator_with_workflows(**workflows) -> AgentOrchestrator:
    """Build a bare orchestrator with only dispatch-relevant attributes set."""
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch.state_machine = MagicMock()
    orch.context = MagicMock()
    orch.task_queue = MagicMock()  # must NOT be used by the migrated handlers
    orch._workflows = workflows
    return orch


def test_handle_discovery_delegates_and_maps_query_to_title():
    discovery = MagicMock()
    discovery.run.return_value = 3
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    task = SimpleNamespace(payload={"query": "python engineer", "location": "NYC"})
    orch._handle_discovery(task)

    discovery.run.assert_called_once()
    override = discovery.run.call_args.kwargs["override_criteria"]
    assert override["title"] == "python engineer"
    assert override["location"] == "NYC"
    orch.context.update_stats.assert_called_with("discovered", 3)
    # No manual enqueue — the workflow owns VET enqueueing.
    orch.task_queue.queue_task.assert_not_called()


def test_handle_discovery_accepts_title_key_directly():
    discovery = MagicMock()
    discovery.run.return_value = 0
    orch = _orchestrator_with_workflows(DiscoveryWorkflow=discovery)

    orch._handle_discovery(SimpleNamespace(payload={"title": "data scientist"}))

    override = discovery.run.call_args.kwargs["override_criteria"]
    assert override["title"] == "data scientist"


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

    vetting.run.assert_called_once_with(job)
    orch.context.update_stats.assert_called_with("vetted", 1)
    # No manual APPLY enqueue — the workflow owns it.
    orch.task_queue.queue_task.assert_not_called()


def test_handle_vetting_failure_does_not_count_vetted():
    vetting = MagicMock()
    vetting.run.return_value = False
    orch = _orchestrator_with_workflows(VettingWorkflow=vetting)

    job = SimpleNamespace(title="Engineer", company="Acme", url="https://x")
    orch._handle_vetting(SimpleNamespace(payload=job))

    vetting.run.assert_called_once_with(job)
    orch.context.update_stats.assert_not_called()


def test_get_workflow_raises_when_unregistered():
    orch = _orchestrator_with_workflows()
    raised = False
    try:
        orch._get_workflow("DiscoveryWorkflow")
    except RuntimeError:
        raised = True
    assert raised
