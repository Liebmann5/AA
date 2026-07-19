"""Engine workflow orchestrators for AutoApply.

Each workflow file is a complete, standalone, readable description of one engine's
full process from entry to exit. A contributor new to the codebase can open any
workflow file and understand the entire engine without reading other files.

Workflows:
    DiscoveryWorkflow    — Find job listings, deduplicate, enqueue for vetting
    VettingWorkflow      — Score and filter jobs, enqueue approved jobs for application
    ApplicationsWorkflow — Fill and submit job application forms

Extending:
    Add a new discovery source   → implement DiscoveryProviderPort, register in composition_root
    Add a new vetting filter      → subclass BaseVettingFilter, add to filter pipeline in composition_root
    Add a new ATS handler         → add YAML to resources/ats/, register in ATSRegistry
"""
from auto_apply.application.workflows.discovery_workflow import DiscoveryWorkflow
from auto_apply.application.workflows.vetting_workflow import VettingWorkflow
from auto_apply.application.workflows.applications_workflow import ApplicationsWorkflow

__all__ = ["DiscoveryWorkflow", "VettingWorkflow", "ApplicationsWorkflow"]