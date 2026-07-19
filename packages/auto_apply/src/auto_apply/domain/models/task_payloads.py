"""Typed payload schemas for every TaskType.

The Typed Task Runtime Kernel (TTK) enforces that each TaskType maps to
exactly one payload schema. This file defines those schemas and the registry
that maps between them.

Architecture note: This module lives in domain/models/ — it has zero external
dependencies. All schemas are pure Pydantic v2 models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SearchCriteriaPayload(BaseModel):
    """Payload for DISCOVER tasks seeded from the wizard or profile."""
    model_config = ConfigDict(frozen=True)

    title: str = ""
    query: str = ""           # Alias for title (backward compat)
    location: str = ""
    workplace_type: str = "remote"

    @property
    def effective_title(self) -> str:
        """Returns title, falling back to query for backward compat."""
        return self.title or self.query


class CompanyDiscoveryPayload(BaseModel):
    """Payload for DISCOVER_COMPANY tasks."""
    model_config = ConfigDict(frozen=True)

    careers_url: str
    company_name: str = "Unknown"


class JobUrlPayload(BaseModel):
    """Payload for RESOLVE_JOB_URL tasks.

    Raw user-provided URLs flow through this task type before reaching
    VET or APPLY. This prevents the payload type mismatch that causes
    AttributeError in _handle_vetting and _buffer_application.
    """
    model_config = ConfigDict(frozen=True)

    url: str
    next_task: Literal["VET", "APPLY"] = "VET"
    skip_vetting: bool = False


class CaptchaResolutionPayload(BaseModel):
    """Payload for HANDLE_CAPTCHA interrupt tasks."""
    model_config = ConfigDict(frozen=True)

    challenge_url: str = ""
    challenge_type: str = "unknown"   # e.g., "recaptcha_v2", "hcaptcha", "slider"
    parent_task_id: str | None = None # ID of the APPLY task that was blocked
    context: dict[str, Any] = {}


# ── The Registry ──────────────────────────────────────────────────────────────

# Maps TaskType enum value (string) → allowed Python types for payload.
# This is defined as (enum_value_string → tuple[type, ...]) to avoid a circular
# import between work_unit.py and task_payloads.py.
#
# Usage:
#   from auto_apply.domain.models.task_payloads import TASK_PAYLOAD_REGISTRY
#   expected = TASK_PAYLOAD_REGISTRY.get(task.task_type.value)
#   if expected and not isinstance(task.payload, expected):
#       raise ValueError(...)

TASK_PAYLOAD_REGISTRY: dict[str, tuple[type, ...]] = {
    "discover":         (dict, SearchCriteriaPayload),
    "discover_company": (dict, CompanyDiscoveryPayload),
    "resolve_job_url":  (dict, JobUrlPayload),
    # VET and APPLY require a Job object — never a raw string
    # Job is not imported here to avoid circular imports; checked by string name
    "vet":              (),    # filled at runtime — see validate_work_unit()
    "apply":            (),    # filled at runtime — see validate_work_unit()
    "handle_captcha":   (dict, CaptchaResolutionPayload),
}


def validate_work_unit_payload(task_type_value: str, payload: Any) -> None:
    """Raises ValueError if the payload type is invalid for the given task type.

    Called by DatabaseManager.queue_task() before inserting into SQLite,
    and by WorkUnit's Pydantic validator (Phase 2) at construction time.

    Args:
        task_type_value: The string value of the TaskType enum (e.g., "vet").
        payload: The actual payload object.

    Raises:
        ValueError: If the payload type violates the contract.
    """
    # Special-case the Job-requiring task types to avoid circular imports
    if task_type_value in ("vet", "apply"):
        if isinstance(payload, str):
            raise ValueError(
                f"TaskType '{task_type_value}' requires a Job object, not a URL string. "
                f"Use TaskType.RESOLVE_JOB_URL to resolve raw URLs first. "
                f"Got: {payload[:80]!r}"
            )
        # Allow dict (job.model_dump()), Job instances, and None (for testing)
        return

    expected_types = TASK_PAYLOAD_REGISTRY.get(task_type_value)
    if not expected_types:
        return  # Unknown type — don't block; just pass through

    if payload is None:
        return  # None is allowed (some tasks have optional payloads)

    if not isinstance(payload, expected_types):
        type_names = " | ".join(t.__name__ for t in expected_types)
        raise ValueError(
            f"TaskType '{task_type_value}' requires payload of type {type_names}, "
            f"got {type(payload).__name__}: {str(payload)[:60]!r}"
        )