"""Defines the atomic unit of work for the Agent's execution cycle.

This module provides the `WorkUnit` class and `TaskType` enumeration.
These structures act as the universal currency within the system, allowing
heterogeneous tasks (e.g., "Scrape Google" and "Apply to LinkedIn URL")
to coexist in the same priority queue and database table.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskType(Enum):
    """Categorizes the nature of the work required."""
    DISCOVER = "discover"           # Search for new jobs
    DISCOVER_COMPANY = "discover_company" # Scrape a specific careers page
    VET = "vet"                     # Analyze job against profile
    APPLY = "apply"                 # Execute application logic
    HANDLE_CAPTCHA = "handle_captcha"     # High priority interrupt

@dataclass(order=True)
class WorkUnit:
    """Represents a discrete, transactional task for the Agent.

    This class is designed to be serialized into the SQLite database.
    It supports comparison based solely on `priority` to facilitate
    efficient heap/queue sorting.

    Attributes:
        priority (int): The execution urgency (Lower number = Higher priority).
                        e.g., 1=User Action, 10=Background Scrape.
        task_type (TaskType): The category of operation to perform.
        payload (Any): The data required to execute the task (e.g., URL string,
                       Job object, or SearchCriteria dict).
        source (str): The origin of the task (e.g., "user_input", "scraper").
        context_data (Dict): Metadata for the execution engine (e.g.,
                             "batch_id", "retry_count").
        id (str): A unique UUIDv4 string for database tracking.
        created_at (datetime): Timestamp for aging and reporting.
    """
    priority: int
    task_type: TaskType = field(compare=False)

    # Payload is excluded from comparison to prevent errors with complex objects
    payload: Any = field(compare=False)

    # "user_input" or "scraper_auto"
    source: str = field(compare=False)

    # Metadata context is mutable and excluded from comparison
    context_data: dict[str, Any] = field(default_factory=dict, compare=False)

    # Auto-generated identifiers
    id: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        """Serializes the WorkUnit for logging or inspection.

        Returns:
            Dict[str, Any]: A dictionary representation of the task.
        """
        return {
            "id": self.id,
            "type": self.task_type.value,
            "priority": self.priority,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "payload_summary": str(self.payload)[:50] # Truncate for logs
        }