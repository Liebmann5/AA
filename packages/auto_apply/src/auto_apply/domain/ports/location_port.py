"""Defines contracts for offline geospatial calculations and lookups.

This ensures that location filtering (e.g., checking if a job is within 25 miles)
can be performed locally without leaking user data to third-party mapping APIs.
"""

from abc import ABC, abstractmethod

from auto_apply.domain.models.location import Coordinate

__all__ = ["Coordinate", "LocationRepositoryPort", "DistanceCalculatorPort"]


class LocationRepositoryPort(ABC):
    """Contract for an offline geospatial database.

    Narrowed to coordinate lookup only. The ``extract_locations`` free-text
    method was removed: its only implementer (the flashtext-based
    ``LocationExtractor``) was deleted, nothing ever called it, and its own
    implementation's ``extract()`` did not even match the port signature.
    ``SpatialLocationFilter`` calls ``get_coordinates`` only.

    ``location_name`` accepts ``None`` because job locations are legitimately
    optional; implementations return ``None`` rather than raising.
    """

    @abstractmethod
    def get_coordinates(self, location_name: str | None) -> Coordinate | None:
        """Looks up the latitude and longitude for a given city/state string.

        Args:
            location_name (str | None): The raw location string
                (e.g., "San Diego, CA"), or None.

        Returns:
            Optional[Coordinate]: The coordinates if found, else None.
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
