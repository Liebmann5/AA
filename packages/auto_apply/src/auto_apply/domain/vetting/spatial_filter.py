"""Enforces physical geographic constraints on job candidates.

Analyzes the job location against the user's home location and maximum
commute radius, safely handling "Remote" exceptions.
"""

import logging
import math

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.profile import UserProfile
from auto_apply.domain.ports.location_port import Coordinate, LocationRepositoryPort
from auto_apply.domain.vetting.base_filter import BaseVettingFilter

logger = logging.getLogger(__name__)


class SpatialLocationFilter(BaseVettingFilter):
    """Filters jobs based on calculated spherical distance.

    The Haversine formula runs entirely within this class; the only external
    dependency is coordinate lookups, which are delegated to the injected
    ``LocationRepositoryPort``.

    Args:
        profile: The active user profile.
        location_repo: Port for coordinate lookups, injected by infrastructure.
            Any implementation — SQLite, pgeocode, an API adapter — is
            acceptable as long as it satisfies the port contract.
    """

    _EARTH_RADIUS_MILES: float = 3958.8

    def __init__(
        self,
        profile: UserProfile,
        location_repo: LocationRepositoryPort,
    ) -> None:
        """Initialises the filter and resolves the user's home coordinates.

        Args:
            profile: The active user profile.
            location_repo: Injected coordinate-lookup port.
        """
        super().__init__(profile)
        self._location_repo = location_repo

        prefs = getattr(profile, "search_preferences", None)
        self._max_commute_miles: float = getattr(prefs, "max_commute_miles", 25.0)
        self._open_to_remote: bool = "remote" in [
            t.lower() for t in getattr(prefs, "workplace_types", [])
        ]

        personal = getattr(profile, "personal_info", None)
        city = getattr(personal, "city", "")
        state = getattr(personal, "state", "")
        user_loc_str = f"{city}, {state}".strip(", ")

        try:
            self._home_coords = self._location_repo.get_coordinates(user_loc_str)
        except Exception as e:
            logger.warning(
                "Could not resolve home coordinates | location=%s error=%s",
                user_loc_str,
                e,
            )
            self._home_coords = None

        logger.debug(
            "SpatialLocationFilter ready | home=%s coords=%s max_miles=%s remote=%s",  #max_miles=%.1f
            user_loc_str,
            self._home_coords,
            str(self._max_commute_miles),
            self._open_to_remote,
        )

    def filter(self, job: Job) -> tuple[bool, str]:
        """Determines if the job is physically reachable by the user.

        Args:
            job: The Job candidate to evaluate.

        Returns:
            ``(True, reason)`` if within commute range or remote,
            ``(False, reason)`` otherwise.
        """
        if not job.location:
            return True, "No location data provided; passing to human review."

        job_loc_lower = job.location.lower()

        if "remote" in job_loc_lower or "anywhere" in job_loc_lower:
            if self._open_to_remote:
                return True, "Valid Remote Job"
            return False, "User does not want Remote work"

        return self._distance_check(job, job_loc_lower)

    def _distance_check(self, job: Job, job_loc_lower: str) -> tuple[bool, str]:
        """Resolves job coordinates and compares against the user's commute limit.

        Falls back to string matching when either the home or job coordinates
        cannot be resolved.

        Args:
            job: The Job candidate being evaluated.
            job_loc_lower: Pre-lowercased job location string for fallback use.

        Returns:
            ``(True, reason)`` or ``(False, reason)``.
        """
        if not self._home_coords:
            return self._fallback_string_match(job_loc_lower)

        try:
            job_coords = self._location_repo.get_coordinates(job.location)
        except Exception as e:
            logger.warning(
                "Job coordinate lookup failed | location=%s error=%s",
                job.location,
                e,
            )
            job_coords = None

        if job_coords is None:
            return self._fallback_string_match(job_loc_lower)

        distance = self._haversine_miles(self._home_coords, job_coords)

        if distance <= self._max_commute_miles:
            return True, f"Within commute range ({distance:.1f} miles)"
        return False, f"Too far ({distance:.1f} miles > {self._max_commute_miles} max)"

    def _fallback_string_match(self, job_loc_lower: str) -> tuple[bool, str]:
        """Degrades to basic string matching when coordinate lookup is unavailable.

        Args:
            job_loc_lower: The lowercase job location string.

        Returns:
            ``(True, reason)`` on city-name match, ``(False, reason)`` otherwise.
        """
        personal = getattr(self.profile, "personal_info", None)
        user_city = getattr(personal, "city", "").lower()
        if user_city and user_city in job_loc_lower:
            return True, "Fallback: Text Match on city name"
        return False, f"Fallback: Text Mismatch ({job_loc_lower!r})"

    @staticmethod
    def _haversine_miles(coord_a: Coordinate, coord_b: Coordinate) -> float:
        """Calculates the great-circle distance between two coordinates in miles.

        Uses the Haversine formula. Coordinates are expressed as
        :class:`~auto_apply.domain.ports.location_port.Coordinate` instances
        with ``latitude`` and ``longitude`` in decimal degrees.

        Args:
            coord_a: Origin coordinate.
            coord_b: Destination coordinate.

        Returns:
            Distance in miles.
        """
        lat1 = math.radians(coord_a.latitude)
        lon1 = math.radians(coord_a.longitude)
        lat2 = math.radians(coord_b.latitude)
        lon2 = math.radians(coord_b.longitude)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))

        return SpatialLocationFilter._EARTH_RADIUS_MILES * c
