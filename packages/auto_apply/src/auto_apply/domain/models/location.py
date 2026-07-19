"""Domain model for geographic coordinates."""


class Coordinate:
    """A memory-efficient data structure for geographic coordinates.

    Uses __slots__ to avoid per-instance __dict__, saving memory when
    processing thousands of job locations.
    """

    __slots__ = ["latitude", "longitude"]

    def __init__(self, latitude: float, longitude: float) -> None:
        self.latitude = latitude
        self.longitude = longitude

    def __repr__(self) -> str:
        return f"Coordinate(lat={self.latitude}, lon={self.longitude})"