
"""Observer seams for extraction auditing.

Auditing is observation, not extraction: it records what the miner and the
Math DOM subsystem saw, and removing it must never change what they produce.
That makes it the right thing to put behind a port — the adapters that emit
audit records should not reach up into the application layer to find a logger.

Two protocols, plus null implementations that are the shipped default:

    * :class:`ExtractionObserverPort` — the audit record surface.
    * :class:`PageAuditReporterPort` — page-level state/rejection reporting.

Both nulls are silent and total: every method is a no-op, so an unwired
observer degrades to "no audit trail" rather than to an exception. Discovery
must not be able to fail because nobody was watching.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ExtractionObserverPort(Protocol):
    """Records what an extraction pass saw. Never influences the result."""

    @property
    def enabled(self) -> bool:
        """True when records are being kept, for cheap call-site gating."""
        ...

    def audit_candidate_containers(self, containers: list[Any], source: str) -> None: ...

    def audit_structural_hash_groups(self, groups: dict[str, list[Any]], source: str) -> None: ...

    def audit_extraction_attempt(self, job_data: dict[str, Any], success: bool, reason: str = "") -> None: ...

    def audit_geometry_cluster(self, cluster_text: list[str], page_title: str) -> None: ...

    def audit_validation_error(self, job_dict: dict[str, Any], error: str) -> None: ...

    def audit_final_job_list(self, jobs: list[Any], provider: str) -> None: ...

    def audit_text_extraction(self, node: Any, text: str, source: str) -> None: ...


@runtime_checkable
class PageAuditReporterPort(Protocol):
    """Reports page-level audit state. Never influences the result."""

    def log_state(self, context_label: str) -> None: ...

    def log_item_rejection(self, element: Any, reason: str, partial_data: dict[str, Any]) -> None: ...


class NullExtractionObserver:
    """Silent observer — the default when nothing is wired."""

    @property
    def enabled(self) -> bool:
        return False

    def audit_candidate_containers(self, containers: list[Any], source: str) -> None:
        return None

    def audit_structural_hash_groups(self, groups: dict[str, list[Any]], source: str) -> None:
        return None

    def audit_extraction_attempt(self, job_data: dict[str, Any], success: bool, reason: str = "") -> None:
        return None

    def audit_geometry_cluster(self, cluster_text: list[str], page_title: str) -> None:
        return None

    def audit_validation_error(self, job_dict: dict[str, Any], error: str) -> None:
        return None

    def audit_final_job_list(self, jobs: list[Any], provider: str) -> None:
        return None

    def audit_text_extraction(self, node: Any, text: str, source: str) -> None:
        return None


class NullAuditReporter:
    """Silent page reporter — the default when nothing is wired."""

    def log_state(self, context_label: str) -> None:
        return None

    def log_item_rejection(self, element: Any, reason: str, partial_data: dict[str, Any]) -> None:
        return None
