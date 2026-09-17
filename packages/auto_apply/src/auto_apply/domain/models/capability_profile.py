"""Resolved capability profile — what this AA installation can actually do.

Built once at session start from hardware detection, admin policy, and user
settings. Frozen after construction. Injected into the orchestrator and all
components that need capability awareness.

The capability profile answers: "Given everything AA knows about this machine
and this user's settings, what is AA allowed to do right now?"

STATIC_ASSISTED is deleted (ruled 2026-09-08): a mode name with no
implementation behind it is capability built and never connected. When the
browser cascade exhausts, build_orchestrator refuses to construct a session
at all, so ``has_browser=False`` here is only ever produced by construction-
time paths (tests). The profile is honest about that instead of promising a
static mode that does not exist: an empty ``allowed_task_types``, because the
orchestrator requires a live browser for every task type.
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

        With no browser this is the empty set — deliberately. The
        orchestrator requires a live browser for DISCOVER, DISCOVER_COMPANY,
        RESOLVE_JOB_URL, VET, APPLY and HANDLE_CAPTCHA alike, so the profile
        must say "nothing runs" rather than claim a static discovery mode
        that does not exist. If a follow-up prompt ever makes one task type
        genuinely browser-free (RESOLVE_JOB_URL's stub path is the candidate),
        it must update this set AND orchestrator._requires_browser together.
        """
        if not self.has_browser:
            return set()
        return {
            "discover",
            "discover_company",
            "resolve_job_url",
            "vet",
            "apply",
            "handle_captcha",
        }

    def can_run_task(self, task_type_value: str) -> bool:
        """Returns True if this profile supports the given task type."""
        return task_type_value in self.allowed_task_types

    @property
    def mode_name(self) -> str:
        """Human-readable description of the current execution mode.

        "NO_BROWSER" is not a mode — it is the honest name for a construction
        that no production path can reach, kept so construction-time callers
        (tests) get an accurate label instead of the deleted STATIC_ASSISTED
        promise.
        """
        if not self.has_browser:
            return "NO_BROWSER"
        if self.is_low_resource and self.max_browser_workers <= 1:
            return "GUIDED_BROWSER"
        if self.max_browser_workers > 2:
            return "POWER_USER"
        return "STANDARD_AGENT"
