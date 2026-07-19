"""Architectural enforcement tests for composition root wiring (BACKLOG-002)."""

import inspect

import pytest

from auto_apply.infrastructure import composition_root as cr


def test_research_collector_removed_from_composition_root():
    """Old ResearchCollector must not appear in composition root source."""
    src = inspect.getsource(cr)
    assert "ResearchCollector" not in src, (
        "ResearchCollector must be removed from composition root (BACKLOG-002)"
    )


def test_null_observer_default_in_composition_root():
    """When research is disabled, NullResearchObserver is used."""
    src = inspect.getsource(cr)
    assert "NullResearchObserver" in src, (
        "NullResearchObserver must be imported and used as default"
    )


def test_build_orchestrator_signature_unchanged():
    """Smoke check: build_orchestrator still exists."""
    assert callable(cr.build_orchestrator)


def test_discovery_workflow_accepts_research_observer():
    """DiscoveryWorkflow constructor accepts research_observer."""
    from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
    sig = inspect.signature(DiscoveryWorkflow)
    assert "research_observer" in sig.parameters
    from auto_apply.domain.ports.research_port import NullResearchObserver
    assert sig.parameters["research_observer"].default is None  # default handled in body


def test_vetting_workflow_accepts_research_observer():
    """VettingWorkflow constructor accepts research_observer."""
    from auto_apply.application.workflows.vetting_workflow import VettingWorkflow
    sig = inspect.signature(VettingWorkflow)
    assert "research_observer" in sig.parameters
    from auto_apply.domain.ports.research_port import NullResearchObserver
    assert sig.parameters["research_observer"].default is None


def test_applications_workflow_accepts_research_observer():
    """ApplicationsWorkflow constructor accepts research_observer."""
    from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow
    sig = inspect.signature(ApplicationsWorkflow)
    assert "research_observer" in sig.parameters
    from auto_apply.domain.ports.research_port import NullResearchObserver
    assert sig.parameters["research_observer"].default is None