"""High-speed geographic entity extraction.

Utilizes the FlashText algorithm to extract known cities and states from
massive blocks of text (like Job Descriptions) in O(N) time.
"""

# Layer: application
# Depends on: domain

import logging

from flashtext import KeywordProcessor

logger = logging.getLogger(__name__)

class LocationExtractor:
    """Extracts geographic entities from text using an Aho-Corasick automaton."""

    def __init__(self, known_locations: list[str]):
        """Initializes the extractor and compiles the automaton.

        Args:
            known_locations (List[str]): A list of all cities/states to look for.
                (e.g.,["San Diego, CA", "Los Angeles, CA", "Remote"]).
        """
        self.processor = KeywordProcessor(case_sensitive=False)

        # We add the locations to the processor. When it finds a match in the
        # text, it will return the clean string we provide here.
        for loc in known_locations:
            self.processor.add_keyword(loc)

        logger.info(f"Initialized LocationExtractor with {len(known_locations)} entities.")  # noqa: E501

    def extract(self, text: str) -> set[str]:
        """Scans the text and returns all identified locations.

        Args:
            text (str): The raw job description or title.

        Returns:
            Set[str]: A unique set of found locations.
        """
        if not text:
            return set()

        # Extract keywords returns a list; we cast to Set to remove duplicates
        found = set(self.processor.extract_keywords(text))
        return found