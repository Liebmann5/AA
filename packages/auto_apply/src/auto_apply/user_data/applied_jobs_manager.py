"""Manages a persistent database of jobs that have already been applied to.

This module provides the `AppliedJobsManager`, a class that handles the
loading, checking, adding, and saving of a list of applied-to job URLs. Its
primary purpose is to prevent the agent from applying to the same job more
than once across multiple sessions.
"""
import json
import logging
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

class AppliedJobsManager:
    """Handles loading and saving a persistent set of applied-to job URLs.

    This class is designed to be used as a context manager (`with ... as ...`)
    to guarantee that the database is loaded at the start of a session and that
    any new jobs added during the session are automatically saved upon exit,
    even if errors occur.

    It uses a Python `set` for in-memory storage, which provides highly
    efficient O(1) average time complexity for checking if a job has already
    been applied to.
    """

    def __init__(self, storage_path: Path):
        """Initializes the manager with a path to its storage file.

        Args:
            storage_path: The `Path` object pointing to the JSON file that will
                be used for persistent storage.
        """
        self.storage_path = storage_path
        self._applied_urls_: Set[str] = set()

    def load(self) -> None:
        """Loads the set of applied-to URLs from the JSON storage file.

        If the storage file does not exist, it starts with an empty set. If the
        file is corrupted or cannot be read, it logs an error and proceeds with
        an empty set to ensure the application can still run.
        """
        if not self.storage_path.exists():
            logger.info("Applied jobs file not found at '%s'. Starting with an empty database.", self.storage_path)
            self._applied_urls = set()
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                urls = json.load(f)
                self._applied_urls = set(urls)
                logger.info("Successfully loaded %d applied job records.", len(self._applied_urls))
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load or parse applied jobs file. Starting fresh. Error: %s", e)
            self._applied_urls = set()

    def save(self) -> None:
        """Saves the current set of applied-to URLs to the JSON storage file.

        To write to JSON, the in-memory `set` is converted to a `list`.
        """
        logger.info("Saving %d applied job records to '%s'.", len(self._applied_urls), self.storage_path)
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(list(self._applied_urls), f, indent=2)
        except IOError as e:
            logger.critical("CRITICAL: Failed to save applied jobs file! Error: %s", e)

    def add(self, url: str) -> None:
        """Adds a new URL to the in-memory set of applied-to jobs.

        Args:
            url: The unique URL of the job that was successfully applied to.
        """
        if url not in self._applied_urls:
            self._applied_urls.add(url)
            logger.debug("Added new job to applied list: %s", url)

    def has_been_applied_to(self, url: str) -> bool:
        """Checks if a job URL is present in the database.

        This is a highly efficient O(1) lookup operation due to the use of a set.

        Args:
            url: The job URL to check.

        Returns:
            True if the URL is in the database, False otherwise.
        """
        return url in self._applied_urls

    def __enter__(self):
        """Loads the database when entering the `with` block."""
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Saves the database when exiting the `with` block."""
        self.save()