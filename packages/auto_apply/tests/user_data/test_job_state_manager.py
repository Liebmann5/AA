import json
from pathlib import Path
from auto_apply.user_data.job_state_manager import JobStateManager, JobStatus
from auto_apply.scraping.search.search_result import SearchResult

# We will use tmp_path for all tests to ensure each test runs in a clean directory.

def test_load_from_existing_file(tmp_path: Path):
    """
    GIVEN: A valid job state JSON file exists.
    WHEN: The JobStateManager is initialized and loads.
    THEN: The manager's internal state dictionary should be populated correctly.
    """
    # ARRANGE
    db_file = tmp_path / "states.json"
    initial_state = {
        "https://job.com/1": {
            "status": "application_completed",
            "title": "Job A",
            "company": "C1",
            "source": "S1"
        }
    }
    db_file.write_text(json.dumps(initial_state))
    manager = JobStateManager(storage_path=db_file)

    # ACT
    manager.load()

    # ASSERT
    assert "https://job.com/1" in manager.job_states
    assert manager.job_states["https://job.com/1"]["status"] == JobStatus.APPLICATION_COMPLETED.value
    assert manager.job_states["https://job.com/1"]["title"] == "Job A"


def test_load_from_non_existent_file(tmp_path: Path):
    """
    GIVEN: The job state file does not exist.
    WHEN: The manager loads.
    THEN: It should start with an empty state and not raise an error.
    """
    # ARRANGE
    db_file = tmp_path / "non_existent.json"
    manager = JobStateManager(storage_path=db_file)

    # ACT
    manager.load()

    # ASSERT
    assert manager.job_states == {}


def test_add_new_jobs(tmp_path: Path):
    """
    GIVEN: An empty manager.
    WHEN: A list of new SearchResult objects is added.
    THEN: The new jobs should be in the state dictionary with the 'FOUND' status.
    """
    # ARRANGE
    manager = JobStateManager(storage_path=tmp_path / "db.json")
    new_jobs = [
        SearchResult(url="https://job.com/1", title="A", company="C1", source="S1"),
        SearchResult(url="https://job.com/2", title="B", company="C2", source="S2"),
    ]

    # ACT
    manager.add_new_jobs(new_jobs)

    # ASSERT
    assert len(manager.job_states) == 2
    assert manager.job_states["https://job.com/1"]["status"] == JobStatus.FOUND.value
    assert manager.job_states["https://job.com/2"]["company"] == "C2"


def test_add_new_jobs_does_not_overwrite_existing_state(tmp_path: Path):
    """
    GIVEN: A manager with a pre-existing job in a specific state.
    WHEN: A list of jobs including that existing job is passed to `add_new_jobs`.
    THEN: The existing job's state should not be reset to 'FOUND'.
    """
    # ARRANGE
    manager = JobStateManager(storage_path=tmp_path / "db.json")
    # Pre-populate the state with a job that's already in progress
    manager.job_states = {
        "https://job.com/existing": {
            "status": JobStatus.APPLICATION_IN_PROGRESS.value,
            "title": "Old Title", "company": "Old Company", "source": "S1"
        }
    }
    jobs_from_new_search = [
        SearchResult(url="https://job.com/new", title="New Job", company="C_New", source="S2"),
        SearchResult(url="https://job.com/existing", title="New Title", company="New Company", source="S2"),
    ]

    # ACT
    manager.add_new_jobs(jobs_from_new_search)

    # ASSERT
    assert len(manager.job_states) == 2
    # The new job should be added and marked as 'found'
    assert manager.job_states["https://job.com/new"]["status"] == JobStatus.FOUND.value
    # The existing job's status MUST NOT be overwritten
    assert manager.job_states["https://job.com/existing"]["status"] == JobStatus.APPLICATION_IN_PROGRESS.value


def test_update_job_status(tmp_path: Path):
    """
    GIVEN: A manager containing a job with 'FOUND' status.
    WHEN: `update_job_status` is called for that job.
    THEN: The job's status should be updated to the new status.
    """
    # ARRANGE
    manager = JobStateManager(storage_path=tmp_path / "db.json")
    job_url = "https://job.com/1"
    manager.job_states = {
        job_url: {"status": JobStatus.FOUND.value, "title": "A", "company": "C1", "source": "S1"}
    }

    # ACT
    manager.update_job_status(job_url, JobStatus.APPLICATION_COMPLETED)

    # ASSERT
    assert manager.job_states[job_url]["status"] == JobStatus.APPLICATION_COMPLETED.value


def test_get_jobs_to_apply_for(tmp_path: Path):
    """
    GIVEN: A manager with jobs in various states.
    WHEN: `get_jobs_to_apply_for` is called.
    THEN: It should return a list of SearchResult objects ONLY for jobs with 'FOUND' status.
    """
    # ARRANGE
    manager = JobStateManager(storage_path=tmp_path / "db.json")
    manager.job_states = {
        "https://job.com/found1": {"status": "found", "title": "A", "company": "C1", "source": "S1"},
        "https://job.com/inprogress": {"status": "application_in_progress", "title": "B", "company": "C2", "source": "S2"},
        "https://job.com/completed": {"status": "application_completed", "title": "C", "company": "C3", "source": "S3"},
        "https://job.com/found2": {"status": "found", "title": "D", "company": "C4", "source": "S4"},
    }

    # ACT
    jobs_to_apply = manager.get_jobs_to_apply_for()

    # ASSERT
    assert len(jobs_to_apply) == 2
    found_urls = {job.url for job in jobs_to_apply}
    assert "https://job.com/found1" in found_urls
    assert "https://job.com/found2" in found_urls
    # Check that it returns the correct type
    assert isinstance(jobs_to_apply[0], SearchResult)


def test_context_manager_integration(tmp_path: Path):
    """
    GIVEN: An existing database file.
    WHEN: The manager is used in a `with` block to add and update jobs.
    THEN: The file should be correctly loaded on entry and saved with all changes upon exit.
    """
    # ARRANGE
    db_file = tmp_path / "database.json"
    initial_state = {
        "https://job.com/initial": {"status": "found", "title": "Initial", "company": "C1", "source": "S1"}
    }
    db_file.write_text(json.dumps(initial_state))

    new_jobs_to_add = [SearchResult(url="https://job.com/new", title="New", company="C2", source="S2")]

    # ACT
    with JobStateManager(storage_path=db_file) as manager:
        # Check that loading worked
        assert "https://job.com/initial" in manager.job_states

        # Perform actions
        manager.add_new_jobs(new_jobs_to_add)
        manager.update_job_status("https://job.com/initial", JobStatus.APPLICATION_FAILED)

    # ASSERT
    # Re-read the file to ensure `save` was called correctly on exit
    final_data = json.loads(db_file.read_text())

    assert len(final_data) == 2
    assert final_data["https://job.com/initial"]["status"] == JobStatus.APPLICATION_FAILED.value
    assert final_data["https://job.com/new"]["status"] == JobStatus.FOUND.value