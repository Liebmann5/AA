"""Provides highly optimized spherical mathematics.

This module implements the Haversine formula to calculate the great-circle
distance between two points on a sphere given their longitudes and latitudes.
"""

# Layer: application
# Depends on: (none - pure Python stdlib)

import math

from auto_apply.domain.models.location import Coordinate

__all__ = ["Coordinate", "HaversineCalculator"]


class HaversineCalculator:
    """Calculates distances over the Earth's surface."""

    # Mean radius of the Earth in miles.
    # (Use 6371.0 for Kilometers if you add metric support later).
    EARTH_RADIUS_MILES = 3958.8

    def calculate_miles(self, loc1: Coordinate, loc2: Coordinate) -> float:
        """Calculates the shortest distance between two coordinates in miles.

        Args:
            loc1 (Coordinate): The first location (e.g., User's home).
            loc2 (Coordinate): The second location (e.g., Job location).

        Returns:
            float: The distance in miles.
        """
        # Convert decimal degrees to radians
        lat1, lon1 = math.radians(loc1.latitude), math.radians(loc1.longitude)
        lat2, lon2 = math.radians(loc2.latitude), math.radians(loc2.longitude)

        # Haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2  # noqa: E501
        c = 2 * math.asin(math.sqrt(a))

        return self.EARTH_RADIUS_MILES * c