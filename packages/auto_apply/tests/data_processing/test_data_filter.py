import pytest
from auto_apply.data_processing.data_filter import DataFilter
from auto_apply.scraping.search.search_result import SearchResult
from auto_apply.user_data.applied_jobs_manager import AppliedJobsManager
from pathlib import Path

# Pytest uses "fixtures" for setup. This is a simple one.
# The `mocker` fixture comes from the `pytest-mock` library and is essential.
# The `tmp_path` fixture is built into pytest and gives us a temporary directory.
@pytest.fixture
def mock_applied_jobs_manager(mocker, tmp_path: Path) -> AppliedJobsManager:
    """
    This is a pytest "fixture". It creates a mocked (fake) version
    of the AppliedJobsManager so our tests don't depend on a real file.
    The `mocker.patch` command intercepts the real `save` method and replaces
    it with a "spy" that does nothing.
    """
    # Create a temporary file for the manager to point to
    fake_db_path = tmp_path / "applied_jobs.json"

    # Instantiate the real manager but control its internal state
    manager = AppliedJobsManager(storage_path=fake_db_path)

    # We can manually set the internal state for our tests
    manager._applied_urls = {"https://job.com/already_applied"}

    # We don't want the `save` method to actually write a file during tests.
    # mocker.patch stops the original function from running.
    mocker.patch.object(manager, 'save', return_value=None)

    return manager


def test_filter_removes_duplicates_only():
    """
    GIVEN: A list of search results containing duplicate URLs.
    WHEN: The DataFilter processes the list.
    THEN: The final list should contain only unique job results.
    """
    # ARRANGE (GIVEN)
    raw_results = [
        SearchResult(url="https://job.com/1", title="Job A", company="C1", source="S"),
        SearchResult(url="https://job.com/2", title="Job B", company="C2", source="S"),
        SearchResult(url="https://job.com/1", title="Job A Duplicate", company="C1", source="S"),
    ]
    # For this test, we can use a simple mock that has no applied jobs.
    mock_manager = AppliedJobsManager(storage_path=Path("dummy.json"))
    mock_manager._applied_urls = set()
    data_filter = DataFilter(job_manager=mock_manager)

    # ACT (WHEN)
    filtered_results = data_filter.filter_results(raw_results)

    # ASSERT (THEN)
    assert len(filtered_results) == 2
    # Verify that the first instance of the duplicate URL was kept.
    assert filtered_results[0].url == "https://job.com/1"
    assert filtered_results[1].url == "https://job.com/2"


def test_filter_removes_applied_jobs_only(mock_applied_jobs_manager):
    """
    GIVEN: A list of unique jobs where one has already been applied to.
    WHEN: The DataFilter processes the list.
    THEN: The final list should not contain the already-applied job.
    """
    # ARRANGE (GIVEN)
    raw_results = [
        SearchResult(url="https://job.com/new_job_1", title="New Job 1", company="C1", source="S"),
        SearchResult(url="https://job.com/already_applied", title="Old Job", company="C2", source="S"),
        SearchResult(url="https://job.com/new_job_2", title="New Job 2", company="C3", source="S"),
    ]
    # We use our fixture here, which is pre-configured to know about "already_applied".
    data_filter = DataFilter(job_manager=mock_applied_jobs_manager)

    # ACT (WHEN)
    filtered_results = data_filter.filter_results(raw_results)

    # ASSERT (THEN)
    assert len(filtered_results) == 2
    final_urls = {result.url for result in filtered_results}
    assert "https://job.com/already_applied" not in final_urls
    assert "https://job.com/new_job_1" in final_urls


def test_filter_handles_mixed_list_of_duplicates_and_applied(mock_applied_jobs_manager):
    """
    GIVEN: A complex list with both duplicate URLs and already-applied jobs.
    WHEN: The DataFilter processes them.
    THEN: The final list should be correctly cleaned of both.
    """
    # ARRANGE (GIVEN)
    raw_results = [
        SearchResult(url="https://job.com/1", title="A", company="C1", source="S"),
        SearchResult(url="https://job.com/2", title="B", company="C2", source="S"),
        SearchResult(url="https://job.com/1", title="A_dup", company="C1", source="S"),         # Duplicate
        SearchResult(url="https://job.com/already_applied", title="C", company="C3", source="S"), # Already Applied
        SearchResult(url="https://job.com/3", title="D", company="C4", source="S"),
    ]
    data_filter = DataFilter(job_manager=mock_applied_jobs_manager)

    # ACT (WHEN)
    filtered_results = data_filter.filter_results(raw_results)

    # ASSERT (THEN)
    assert len(filtered_results) == 3
    final_urls = {result.url for result in filtered_results}
    assert "https://job.com/already_applied" not in final_urls
    assert "https://job.com/1" in final_urls
    assert "https://job.com/2" in final_urls
    assert "https://job.com/3" in final_urls


def test_filter_handles_empty_list(mock_applied_jobs_manager):
    """
    GIVEN: An empty list of search results.
    WHEN: The DataFilter processes it.
    THEN: It should return an empty list and not crash.
    """
    # ARRANGE (GIVEN)
    raw_results = []
    data_filter = DataFilter(job_manager=mock_applied_jobs_manager)

    # ACT (WHEN)
    filtered_results = data_filter.filter_results(raw_results)

    # ASSERT (THEN)
    assert len(filtered_results) == 0
    assert filtered_results == []


def test_filter_returns_all_when_no_filtering_needed(mock_applied_jobs_manager):
    """
    GIVEN: A clean list of new, unique jobs.
    WHEN: The DataFilter processes it.
    THEN: The original list should be returned unchanged (in content).
    """
    # ARRANGE (GIVEN)
    raw_results = [
        SearchResult(url="https://job.com/1", title="A", company="C1", source="S"),
        SearchResult(url="https://job.com/2", title="B", company="C2", source="S"),
        SearchResult(url="https://job.com/3", title="C", company="C3", source="S"),
    ]
    data_filter = DataFilter(job_manager=mock_applied_jobs_manager)

    # ACT (WHEN)
    filtered_results = data_filter.filter_results(raw_results)

    # ASSERT (THEN)
    assert len(filtered_results) == 3
    assert filtered_results == raw_results