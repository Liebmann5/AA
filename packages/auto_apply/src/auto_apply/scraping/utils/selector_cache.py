"""Provides a simple, persistent JSON-based cache for storing CSS/XPath selectors.

This module contains the `SelectorCache`, a utility class designed to improve
the performance of the heuristic scraping process. It works by saving the
successful result of a `HeuristicSelectorFinder` analysis to a local JSON file.
On subsequent runs, the scraping strategy can first attempt to use the cached
"last known good" selector, bypassing the need for a full, time-consuming
heuristic analysis of the page.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class SelectorCache:
    """A simple JSON-based cache to store and retrieve the last known good selector."""

    def __init__(self, cache_file: Path):
        """Initializes the SelectorCache.

        This loads the cache data from the specified JSON file into memory. If the
        file does not exist or is corrupted, it starts with an empty cache.

        Args:
            cache_file: The `Path` object pointing to the JSON file to be used
                for storage (e.g., `Path("cache/bing_selectors.json")`).
        """
        self.cache_path = cache_file
        self.data = self._load()

    def _load(self) -> dict:
        """Loads the cache data from the JSON file.

        This method is designed to be resilient. If the file doesn't exist or
        contains invalid JSON, it will log a warning and return an empty
        dictionary instead of crashing.

        Returns:
            A dictionary containing the cached selector data.
        """
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning(
                "Could not decode selector cache file at '%s'. It may be corrupted. Starting fresh.",
                self.cache_path
            )
            return {}

    def get_selector(self, key: str) -> (str, str):
        """Retrieves a cached selector by its key.

        Args:
            key: The unique key for the selector to retrieve (e.g., "bing_jobs_container").

        Returns:
            A tuple containing the `By` strategy and the selector string if the
            key is found, otherwise returns (None, None).
        """
        """Returns the cached selector tuple (By, value) or None."""
        if value := self.data.get(key):
            return value['by'], value['selector']
        return None, None

    def save_selector(self, key: str, by: str, selector: str) -> None:
        """Saves or updates a selector in the cache and persists it to the file.

        This method updates the in-memory cache and immediately writes the entire
        cache back to the JSON file to ensure data persistence.

        Args:
            key: The unique key for the selector to save (e.g., "bing_jobs_container").
            by: The `By` strategy used (e.g., "css selector").
            selector: The selector string itself (e.g., "div.job-list").
        """
        self.data[key] = {'by': by, 'selector': selector}
        try:
            self.cache_path.parent.mkdir(exist_ok=True, parents=True)
            with open(self.cache_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except OSError as e:
            logger.error("Failed to save selector cache to '%s': %e", self.cache_path, e)