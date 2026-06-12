"""Port for accessing the capabilities registry from the application layer.

This protocol defines the minimal interface that SessionController needs
from the infrastructure's CapabilitiesRegistry.  By depending on this port
instead of the concrete class the circular dependency is removed and the
hexagonal rule (application must not import from infrastructure) is satisfied.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.models.resources import RuntimeProfile


@runtime_checkable
class RegistryPort(Protocol):
    """Contract for querying the session's runtime capabilities and configuration.

    Concrete implementation: CapabilitiesRegistry in infrastructure/registry.py.
    """

    def get_active_profile(self) -> UserProfile:
        """Return the user profile active for this session."""
        ...

    def get_runtime_profile(self) -> RuntimeProfile:
        """Return the resolved runtime profile (browser, concurrency, ...)."""
        ...

    def get_all_effective_config(self) -> dict:
        """Return a copy of the fully merged configuration dictionary."""
        ...

    def is_research_enabled(self) -> bool:
        """Return True if the user opted into research data collection."""
        ...