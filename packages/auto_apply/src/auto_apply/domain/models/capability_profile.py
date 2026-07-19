"""Resolved capability profile — what this AA installation can actually do.

Built once at session start from hardware detection, admin policy, and user
settings. Frozen after construction. Injected into the orchestrator and all
components that need capability awareness.

The capability profile answers: "Given everything AA knows about this machine
and this user's settings, what is AA allowed to do right now?"

This is how AA avoids crashes in no-browser mode: APPLY tasks require a
browser, and the profile says no browser → reject APPLY at queue insertion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from auto_apply.domain.models.work_unit import TaskType


class ResolvedCapabilityProfile(BaseModel):
    """Frozen snapshot of what this session is capable of doing.

    Built by CapabilitiesRegistry.build_capability_profile() and injected
    into the orchestrator. Never changes during a session.
    """
    model_config = ConfigDict(frozen=True)

    # Browser capabilities
    has_browser: bool = False
    browser_framework: str | None = None   # "selenium" | "playwright" | None
    max_browser_workers: int = 1

    # NLP capabilities
    has_spacy: bool = False
    has_gpt4all: bool = False

    # Research capabilities
    has_research_consent: bool = False
    research_signals_active: bool = False

    # Resource constraints
    is_low_resource: bool = False
    max_applications_per_session: int | None = None
    max_concurrent_sources: int = 1

    @property
    def allowed_task_types(self) -> set[str]:
        """Returns the set of TaskType values allowed in this profile.

        Used by DatabaseManager.queue_task() to reject tasks that require
        unavailable capabilities. String values (not TaskType enum) to avoid
        circular imports.
        """
        allowed = {"discover", "discover_company", "resolve_job_url", "vet"}

        if self.has_browser:
            allowed.add("apply")
            allowed.add("handle_captcha")

        return allowed

    def can_run_task(self, task_type_value: str) -> bool:
        """Returns True if this profile supports the given task type."""
        return task_type_value in self.allowed_task_types

    @property
    def mode_name(self) -> str:
        """Human-readable description of the current execution mode."""
        if not self.has_browser:
            return "STATIC_ASSISTED"
        if self.is_low_resource and self.max_browser_workers <= 1:
            return "GUIDED_BROWSER"
        if self.max_browser_workers > 2:
            return "POWER_USER"
        return "STANDARD_AGENT"