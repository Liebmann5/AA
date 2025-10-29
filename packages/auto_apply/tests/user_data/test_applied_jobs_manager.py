import json
from pathlib import Path
from auto_apply.user_data.applied_jobs_manager import AppliedJobsManager

# Note: We don't need pytest-mock here because we are testing the file operations,
# not mocking them away. We use pytest's `tmp_path` fixture to get a real,
# temporary directory for each test function.

def test_load_from_existing_file(tmp_path: Path):
    """
    GIVEN: A valid JSON file with a list of URLs exists.
    WHEN: The AppliedJobsManager is initialized and `load` is called.
    THEN: The manager's internal set of URLs should match the file's contents.
    """
    # ARRANGE
    db_file = tmp_path / "applied_jobs.json"
    initial_urls = ["https://job.com/1", "https://job.com/2"]
    db_file.write_text(json.dumps(initial_urls))

    manager = AppliedJobsManager(storage_path=db_file)

    # ACT
    manager.load()

    # ASSERT
    assert manager._applied_urls == set(initial_urls)
    assert len(manager._applied_urls) == 2


def test_load_from_non_existent_file(tmp_path: Path):
    """
    GIVEN: The storage file does not exist.
    WHEN: The AppliedJobsManager loads its state.
    THEN: It should start with an empty set of URLs without raising an error.
    """
    # ARRANGE
    db_file = tmp_path / "non_existent.json"
    manager = AppliedJobsManager(storage_path=db_file)

    # ACT
    manager.load()

    # ASSERT
    assert manager._applied_urls == set()


def test_load_from_corrupted_file(tmp_path: Path):
    """
    GIVEN: The storage file contains invalid JSON.
    WHEN: The AppliedJobsManager loads its state.
    THEN: It should handle the error gracefully and start with an empty set.
    """
    # ARRANGE
    db_file = tmp_path / "corrupted.json"
    db_file.write_text('["https://job.com/1", this is not valid json]')
    manager = AppliedJobsManager(storage_path=db_file)

    # ACT
    manager.load()

    # ASSERT
    assert manager._applied_urls == set()


def test_add_new_and_existing_urls(tmp_path: Path):
    """
    GIVEN: An empty AppliedJobsManager.
    WHEN: A new URL is added, and then the same URL is added again.
    THEN: The URL should be present in the set, and the set size should only increase by one.
    """
    # ARRANGE
    manager = AppliedJobsManager(storage_path=tmp_path / "dummy.json")
    manager.load() # Start with an empty set

    # ACT & ASSERT (First add)
    manager.add("https://job.com/new_url")
    assert "https://job.com/new_url" in manager._applied_urls
    assert len(manager._applied_urls) == 1

    # ACT & ASSERT (Second add of same URL)
    manager.add("https://job.com/new_url")
    assert len(manager._applied_urls) == 1 # Size should not change


def test_has_been_applied_to(tmp_path: Path):
    """
    GIVEN: A manager with a pre-loaded set of URLs.
    WHEN: `has_been_applied_to` is called with known and unknown URLs.
    THEN: It should return True for the known URL and False for the unknown one.
    """
    # ARRANGE
    manager = AppliedJobsManager(storage_path=tmp_path / "dummy.json")
    manager._applied_urls = {"https://job.com/known_url"}

    # ACT & ASSERT
    assert manager.has_been_applied_to("https://job.com/known_url") is True
    assert manager.has_been_applied_to("https://job.com/unknown_url") is False


def test_save_writes_correct_data_to_file(tmp_path: Path):
    """
    GIVEN: A manager with several URLs in its internal set.
    WHEN: The `save` method is called.
    THEN: The target file should be created and contain the correct URLs in JSON format.
    """
    # ARRANGE
    db_file = tmp_path / "output.json"
    manager = AppliedJobsManager(storage_path=db_file)
    urls_to_save = {"https://job.com/a", "https://job.com/b"}
    manager._applied_urls = urls_to_save

    # ACT
    manager.save()

    # ASSERT
    assert db_file.exists()

    # Read the data back from the file to verify its contents
    with open(db_file, 'r') as f:
        saved_data = json.load(f)

    # Compare the content, converting the list from the file back to a set for comparison
    assert set(saved_data) == urls_to_save


def test_context_manager_loads_and_saves_automatically(tmp_path: Path):
    """
    GIVEN: An existing database file and a manager instance.
    WHEN: The manager is used as a context manager (`with` block) and a URL is added.
    THEN: It should load the initial data upon entry and save the modified data upon exit.
    """
    # ARRANGE
    db_file = tmp_path / "database.json"
    initial_urls = ["https://job.com/initial"]
    db_file.write_text(json.dumps(initial_urls))

    url_to_add_in_context = "https://job.com/added_during_run"

    # ACT
    # The `with` statement automatically calls `__enter__` (which runs `load`)
    with AppliedJobsManager(storage_path=db_file) as manager:
        # Verify that loading worked
        assert "https://job.com/initial" in manager._applied_urls

        # Add a new job
        manager.add(url_to_add_in_context)
    # The `with` block has now exited, automatically calling `__exit__` (which runs `save`)

    # ASSERT
    # Load the file directly to verify that the `save` method was called correctly
    with open(db_file, 'r') as f:
        final_data = json.load(f)

    final_urls_set = set(final_data)
    assert "https://job.com/initial" in final_urls_set
    assert url_to_add_in_context in final_urls_set
    assert len(final_urls_set) == 2