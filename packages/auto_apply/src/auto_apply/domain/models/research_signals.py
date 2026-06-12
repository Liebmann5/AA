"""
Domain models for research signals used in job discovery and analysis.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SignalType(Enum):
    """Types of research signals that can be collected."""
    COMPANY_INFO = "company_info"
    ROLE_REQUIREMENTS = "role_requirements"
    COMPENSATION_RANGE = "compensation_range"
    LOCATION_DETAILS = "location_details"
    APPLICATION_PROCESS = "application_process"
    TEAM_STRUCTURE = "team_structure"
    COMPANY_CULTURE = "company_culture"
    GROWTH_INDICATORS = "growth_indicators"


class SignalConfidence(Enum):
    """Confidence levels for research signals."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERIFIED = "verified"


@dataclass(frozen=True)
class ResearchSignal:
    """A single piece of research data about a job or company."""
    signal_type: SignalType
    value: Any
    confidence: SignalConfidence
    source: str
    timestamp: datetime
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        """Validate signal data."""
        if not self.source.strip():
            raise ValueError("Signal source cannot be empty")
        if self.value is None:
            raise ValueError("Signal value cannot be None")


@dataclass(frozen=True)
class CompanySignal(ResearchSignal):
    """Research signal specific to company information."""
    company_name: str

    def __post_init__(self):
        super().__post_init__()
        if not self.company_name.strip():
            raise ValueError("Company name cannot be empty")


@dataclass(frozen=True)
class RoleSignal(ResearchSignal):
    """Research signal specific to role information."""
    job_title: str

    def __post_init__(self):
        super().__post_init__()
        if not self.job_title.strip():
            raise ValueError("Job title cannot be empty")


@dataclass(frozen=True)
class SignalCollection:
    """A collection of related research signals."""
    job_id: str
    signals: list[ResearchSignal]
    collection_timestamp: datetime

    def __post_init__(self):
        if not self.job_id.strip():
            raise ValueError("Job ID cannot be empty")
        if not self.signals:
            raise ValueError("Signal collection cannot be empty")

    def get_signals_by_type(self, signal_type: SignalType) -> list[ResearchSignal]:
        """Get all signals of a specific type."""
        return [s for s in self.signals if s.signal_type == signal_type]

    def get_highest_confidence_signal(self, signal_type: SignalType) -> ResearchSignal | None:  # noqa: E501
        """Get the highest confidence signal of a given type."""
        type_signals = self.get_signals_by_type(signal_type)
        if not type_signals:
            return None

        confidence_order = {
            SignalConfidence.VERIFIED: 4,
            SignalConfidence.HIGH: 3,
            SignalConfidence.MEDIUM: 2,
            SignalConfidence.LOW: 1
        }

        return max(type_signals, key=lambda s: confidence_order[s.confidence])
