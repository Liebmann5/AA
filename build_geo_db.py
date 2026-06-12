"""Provides read-only, high-speed access to the offline geographic database."""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

from auto_apply.application.services.location.haversine import Coordinate

logger = logging.getLogger(__name__)

class GeoDatabaseRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_coordinates(self, raw_location: str) -> Optional[Coordinate]:
        """Looks up coordinates, handling exact matches and ambiguous names.
        
        Args:
            raw_location (str): e.g., "London, UK", "San Francisco, CA", or just "Chicago".
        """
        if not self.db_path.exists() or not raw_location:
            return None

        # Clean the input
        parts = [p.strip() for p in raw_location.split(",")]
        city = parts[0]
        region_or_country = parts[1] if len(parts) > 1 else None

        uri = f"file:{self.db_path}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as conn:
                if region_or_country:
                    # Scenario A: We have City + State/Country (e.g., "Austin, TX")
                    # We check admin1_code (State) or country_code.
                    cursor = conn.execute(
                        """
                        SELECT latitude, longitude 
                        FROM locations 
                        WHERE city_name = ? AND (admin1_code = ? OR country_code = ?)
                        ORDER BY population DESC LIMIT 1
                        """, 
                        (city, region_or_country, region_or_country)
                    )
                else:
                    # Scenario B: Ambiguous City only (e.g., "Springfield")
                    # We rely entirely on the highest population to guess correctly.
                    cursor = conn.execute(
                        """
                        SELECT latitude, longitude 
                        FROM locations 
                        WHERE city_name = ?
                        ORDER BY population DESC LIMIT 1
                        """, 
                        (city,)
                    )
                
                row = cursor.fetchone()
                if row:
                    return Coordinate(latitude=row[0], longitude=row[1])
                return None

        except sqlite3.Error as e:
            logger.error(f"GeoDatabase query failed: {e}")
            return None