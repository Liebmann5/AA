"""Manages the persistent state and status of all discovered jobs.

This module provides the `JobStateManager`, a class that acts as the central
database for the entire job application workflow. It tracks the status of every
job from initial discovery through to the final application attempt, ensuring
that the process can be stopped and resumed without losing progress.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict
from enum import Enum

from ..scraping.search.search_result import SearchResult

logger = logging.getLogger(__name__)

class JobStatus(Enum):
    """Enumeration for the status of a job in the application workflow.

    Attributes:
        FOUND: The job has been discovered but no action has been taken.
        APPLICATION_IN_PROGRESS: The agent is currently attempting to apply to this job.
        APPLICATION_COMPLETED: The agent successfully submitted an application.
        APPLICATION_FAILED: The agent attempted to apply but failed.
    """
    FOUND = "found"
    APPLICATION_IN_PROGRESS = "application_in_progress"
    APPLICATION_COMPLETED = "application_completed"
    APPLICATION_FAILED = "application_failed"

class JobStateManager:
    """Handles loading, updating, and saving the state of all jobs.

    This class maintains a dictionary that maps each job's unique URL to its
    current status and metadata. Like other managers, it is designed to be
    used as a context manager to ensure that all state changes are automatically
    saved to a JSON file at the end of a session.
    """

    def __init__(self, storage_path: Path):
        """Initializes the manager with a path to its storage file.

        Args:
            storage_path: The `Path` object pointing to the JSON file that will
                be used for persistent storage.
        """
        self.storage_path = storage_path
        self.job_states: Dict[str, Dict] = {}

    def load(self) -> None:
        """Loads the job states from the JSON storage file into memory."""
        if not self.storage_path.exists():
            logger.info("Job state file not found. Starting with a fresh state.")
            return
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                self.job_states = json.load(f)
                logger.info("Loaded state for %d jobs.", len(self.job_states))
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load job state file: %s", e)

    def save(self) -> None:
        """Saves the current job states to the storage file."""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.job_states, f, indent=2)
        except IOError as e:
            logger.critical("CRITICAL: Failed to save job state file! Error: %s", e)

    def add_new_jobs(self, search_results: List[SearchResult]) -> None:
        """Adds newly found jobs to the state manager with 'FOUND' status.

        This method is idempotent; it checks if a job URL already exists in the
        database before adding it, ensuring no duplicates are created.

        Args:
            search_results: A list of `SearchResult` objects from the data filter.
        """
        new_jobs_added = 0
        for job in search_results:
            if job.url not in self.job_states:
                self.job_states[job.url] = {
                    "status": JobStatus.FOUND.value,
                    "title": job.title,
                    "company": job.company,
                    "source": job.source
                }
                new_jobs_added += 1
        if new_jobs_added > 0:
            logger.info("Added %d new jobs to the state manager.", new_jobs_added)

    def update_job_status(self, job_url: str, status: JobStatus) -> None:
        """Updates the status of a specific job in the database.

        Args:
            job_url: The unique URL of the job to update.
            status: The new `JobStatus` enum member to set for the job.
        """
        if job_url in self.job_states:
            self.job_states[job_url]['status'] = status.value
            logger.info("Updated status for job %s to %s", job_url, status.value)

    def get_jobs_to_apply_for(self) -> List[SearchResult]:
        """Retrieves all jobs that are ready to be applied to.

        This method scans the database and returns a list of all jobs that
        currently have the 'FOUND' status.

        Returns:
            A list of `SearchResult` objects for all pending jobs.
        """
        pending_jobs = []
        for url, data in self.job_states.items():
            if data['status'] == JobStatus.FOUND.value:
                pending_jobs.append(SearchResult(
                    url=url,
                    title=data['title'],
                    company=data['company'],
                    source=data['source']
                ))
        return pending_jobs

    def __enter__(self):
        """Loads the database when entering the `with` block."""
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Saves the database when exiting the `with` block."""
        self.save()