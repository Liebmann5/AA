"""Defines contracts for offline geospatial calculations and lookups.

This ensures that location filtering (e.g., checking if a job is within 25 miles)
can be performed locally without leaking user data to third-party mapping APIs.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.location import Coordinate

__all__ = ["Coordinate", "LocationRepositoryPort", "DistanceCalculatorPort"]


class LocationRepositoryPort(ABC):
    """Contract for an offline geospatial database."""

    @abstractmethod
    def get_coordinates(self, location_name: str) -> Coordinate | None:
        """Looks up the latitude and longitude for a given city/state string.

        Args:
            location_name (str): The raw location string (e.g., "San Diego, CA").

        Returns:
            Optional[Coordinate]: The coordinates if found, else None.
        """
        ...

    @abstractmethod
    def extract_locations(self, text: str) -> list[str]:
        """Extracts known geographical entities from a large block of text.

        Args:
            text (str): The raw job description text.

        Returns:
            List[str]: A list of identified cities/states/countries.
        """
        ...

class DistanceCalculatorPort(ABC):
    """Contract for spherical distance mathematics."""

    @abstractmethod
    def calculate_miles(self, loc1: Coordinate, loc2: Coordinate) -> float:
        """Calculates the shortest distance over the earth's surface.

        Returns:
            float: The distance in miles.
        """
        ...
