"""Defines the atomic unit of work for the Agent's execution cycle.

The WorkUnit is the Typed Task Runtime Kernel's central data structure.
Every discrete action AA takes — discover, vet, apply, handle CAPTCHA —
is represented as a WorkUnit flowing through the priority queue.

Pydantic v2 with frozen=True gives us:
  - Immutable instances after construction (no accidental mutation)
  - Validated fields at construction time
  - Clean JSON serialization via model_dump_json() for SQLite persistence
  - Safe concurrent access (immutability means no shared-state races)

Phase 1 adds RESOLVE_JOB_URL as the bridge between raw URL input and
typed Job objects — preventing the AttributeError that occurs when
VET/APPLY handlers receive a URL string instead of a Job.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskType(Enum):
    """Categorizes the nature of the work required."""
    DISCOVER = "discover"               # Search for new jobs
    DISCOVER_COMPANY = "discover_company" # Scrape a specific careers page
    RESOLVE_JOB_URL = "resolve_job_url"  # Bridge: raw URL → typed Job object
    VET = "vet"                           # Analyze job against profile
    APPLY = "apply"                       # Execute application logic
    HANDLE_CAPTCHA = "handle_captcha"     # High priority interrupt


class WorkUnit(BaseModel):
    """Immutable, schema-validated task for the Agent's priority queue.

    Pydantic v2 ensures:
    - Payload type is validated at construction (programming errors surface early)
    - SQLite round-trip is safe via json.dumps(model_dump()) / model_validate()
    - Immutability prevents accidental mutation during concurrent access

    Implements __lt__ for heapq/priority queue ordering by priority.
    Lower priority number = higher urgency (1 = user action, 10 = background).
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    priority: int
    task_type: TaskType
    payload: Any
    source: str
    context_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _validate_payload_contract(self) -> "WorkUnit":
        """Enforces the TTK payload contract: no raw strings for VET/APPLY."""
        try:
            from auto_apply.domain.models.task_payloads import validate_work_unit_payload
            validate_work_unit_payload(self.task_type.value, self.payload)
        except ImportError:
            pass  # task_payloads not yet available (e.g., during initial setup)
        return self

    def __lt__(self, other: "WorkUnit") -> bool:
        """Priority queue ordering: lower number = higher urgency."""
        return self.priority < other.priority

    def to_dict(self) -> dict[str, Any]:
        """Returns a summary dict for logging. NOT the serialized form."""
        return {
            "id": self.id,
            "type": self.task_type.value,
            "priority": self.priority,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "payload_summary": str(self.payload)[:80],
        }