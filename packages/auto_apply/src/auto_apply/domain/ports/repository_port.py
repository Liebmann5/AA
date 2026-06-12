"""Defines the contract for data persistence.

This Interface Pattern ensures the application can switch between saving to
local JSON files (current implementation) and a Database (future) without
changing the business logic.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from auto_apply.domain.models.job import Job

T = TypeVar('T')


class Repository(ABC, Generic[T]):
    """Abstract base class for data access objects."""

    @abstractmethod
    def save(self, item: T) -> bool:
        """Persists a single item. Returns True if successful."""

    @abstractmethod
    def get(self, identifier: str) -> T | None:
        """Retrieves an item by its unique identifier."""

    @abstractmethod
    def get_all(self) -> list[T]:
        """Retrieves all items in the repository."""

    @abstractmethod
    def delete(self, identifier: str) -> bool:
        """Removes an item from persistence."""


class JobRepositoryPort(ABC):
    """Abstract interface for querying persisted job application history.

    Implementations live in adapters/secondary/persistence/ and translate
    these domain-level queries into whatever storage backend is in use
    (SQLite, JSON files, etc.).
    """

    @abstractmethod
    def count_applications_for_company(self, company_name: str) -> int:
        """Returns the number of completed applications submitted to a company.

        Args:
            company_name: The company to query.

        Returns:
            Count of completed applications. ``0`` if none found.
        """

    @abstractmethod
    def get_last_applied_date(self, company_name: str) -> datetime | None:
        """Returns the timestamp of the most recent completed application.

        Args:
            company_name: The company to query.

        Returns:
            Datetime of the most recent application, or ``None`` if no
            history exists for this company.
        """

    @abstractmethod
    def get_company_mandate_cooldown(self, company_name: str) -> int:
        """Returns the cooldown period scraped from the company's application page.

        Args:
            company_name: The company to query.

        Returns:
            Required cooldown in days as recorded from a previous scrape,
            or ``0`` if no mandate was ever recorded.
        """

    @abstractmethod
    def was_applied(self, url: str) -> bool:
        """Returns True if this URL was successfully applied to in any prior session.

        Args:
            url: The unique job URL to check.

        Returns:
            True if the URL appears in application history with a completed status.
        """

    @abstractmethod
    def mark_applied(self, job: "Job", session_id: str) -> None:
        """Records a completed application for the given job and session.

        Args:
            job: The Job that was applied to.
            session_id: The current session identifier, for cross-session
                correlation in reporting.
        """
