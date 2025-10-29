import pytest
from auto_apply.scraping.adaptive_search_manager import AdaptiveSearchManager
from auto_apply.scraping.search.base_search_strategy import BaseSearchStrategy, StrategyResult
from auto_apply.scraping.search.search_result import SearchResult
from auto_apply.core.browser_interface import BrowserInterface
from pathlib import Path

# mocker is used to create fake strategies, a fake browser, and spy on the auditor.

def test_execute_succeeds_on_first_strategy(mocker):
    # ARRANGE
    mock_audit = mocker.patch("auto_apply.scraping.adaptive_search_manager.audit_and_log_state")
    mock_browser = mocker.create_autospec(BrowserInterface, instance=True)
    mock_screenshots_dir = mocker.create_autospec(Path, instance=True)
    successful_results = [SearchResult("url1", "title1", "company1", "source1")]

    # --- THE NEW, ROBUST FIX ---
    # We mock the 'name' property directly.
    mock_strategy1 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy1.search.return_value = StrategyResult(success=True, results=successful_results)
    type(mock_strategy1).name = mocker.PropertyMock(return_value="mock_strategy1")

    mock_strategy2 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    type(mock_strategy2).name = mocker.PropertyMock(return_value="mock_strategy2")

    manager = AdaptiveSearchManager(screenshots_dir=mock_screenshots_dir)
    manager.register_strategy(mock_strategy1)
    manager.register_strategy(mock_strategy2)

    # ACT
    results = manager.execute(browser=mock_browser)

    # ASSERT
    assert results == successful_results
    mock_strategy1.search.assert_called_once()
    mock_strategy2.search.assert_not_called()
    assert mock_audit.call_count == 2
    mock_audit.assert_any_call(mock_browser, "Before running mock_strategy1")
    mock_audit.assert_any_call(mock_browser, "After successful mock_strategy1")

def test_execute_falls_back_on_graceful_failure(mocker):
    # ARRANGE
    mock_audit = mocker.patch("auto_apply.scraping.adaptive_search_manager.audit_and_log_state")
    mock_browser = mocker.create_autospec(BrowserInterface, instance=True)
    mock_screenshots_dir = mocker.create_autospec(Path, instance=True)
    mock_screenshots_dir.__truediv__.return_value = "path/to/failure_mock_strategy1.png"
    successful_results = [SearchResult("url2", "title2", "company2", "source2")]

    # --- THE NEW, ROBUST FIX ---
    mock_strategy1 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy1.search.return_value = StrategyResult(success=False, failure_reason="CAPTCHA_DETECTED")
    type(mock_strategy1).name = mocker.PropertyMock(return_value="mock_strategy1")

    mock_strategy2 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy2.search.return_value = StrategyResult(success=True, results=successful_results)
    type(mock_strategy2).name = mocker.PropertyMock(return_value="mock_strategy2")

    manager = AdaptiveSearchManager(screenshots_dir=mock_screenshots_dir)
    manager.register_strategy(mock_strategy1)
    manager.register_strategy(mock_strategy2)

    # ACT
    results = manager.execute(browser=mock_browser)

    # ASSERT
    assert results == successful_results
    mock_strategy1.search.assert_called_once()
    mock_strategy2.search.assert_called_once()
    mock_browser.save_screenshot.assert_called_once_with("path/to/failure_mock_strategy1.png")

def test_execute_falls_back_on_critical_failure(mocker):
    # ARRANGE
    mock_audit = mocker.patch("auto_apply.scraping.adaptive_search_manager.audit_and_log_state")
    mock_browser = mocker.create_autospec(BrowserInterface, instance=True)
    mock_screenshots_dir = mocker.create_autospec(Path, instance=True)
    mock_screenshots_dir.__truediv__.return_value = "path/to/critical_failure_mock_strategy1.png"
    successful_results = [SearchResult("url2", "title2", "company2", "source2")]

    # --- THE NEW, ROBUST FIX ---
    mock_strategy1 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy1.search.side_effect = ValueError("Something went very wrong")
    type(mock_strategy1).name = mocker.PropertyMock(return_value="mock_strategy1")

    mock_strategy2 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy2.search.return_value = StrategyResult(success=True, results=successful_results)
    type(mock_strategy2).name = mocker.PropertyMock(return_value="mock_strategy2")

    manager = AdaptiveSearchManager(screenshots_dir=mock_screenshots_dir)
    manager.register_strategy(mock_strategy1)
    manager.register_strategy(mock_strategy2)

    # ACT
    results = manager.execute(browser=mock_browser)

    # ASSERT
    assert results == successful_results
    mock_strategy1.search.assert_called_once()
    mock_strategy2.search.assert_called_once()
    mock_browser.save_screenshot.assert_called_once_with("path/to/critical_failure_mock_strategy1.png")

def test_execute_returns_empty_when_all_strategies_fail(mocker):
    """
    GIVEN: All registered strategies will fail.
    WHEN: The manager's execute method is called.
    THEN: It should return an empty list and not raise an exception.
    """
    # ARRANGE
    mocker.patch("auto_apply.scraping.adaptive_search_manager.audit_and_log_state")
    mock_browser = mocker.create_autospec(BrowserInterface, instance=True)

    mock_screenshots_dir = mocker.create_autospec(Path, instance=True)

    mock_strategy1 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy1.search.return_value = StrategyResult(success=False)
    type(mock_strategy1).__name__ = "mock_strategy1" # Keep this for consistency

    mock_strategy2 = mocker.create_autospec(BaseSearchStrategy, instance=True)
    mock_strategy2.search.side_effect = RuntimeError("Second strategy crashed")
    type(mock_strategy2).__name__ = "mock_strategy2"

    # Pass the mock directory to the constructor
    manager = AdaptiveSearchManager(screenshots_dir=mock_screenshots_dir)
    manager.register_strategy(mock_strategy1)
    manager.register_strategy(mock_strategy2)

    # ACT
    results = manager.execute(browser=mock_browser)

    # ASSERT
    assert results == []
    mock_strategy1.search.assert_called_once()
    mock_strategy2.search.assert_called_once()
    assert mock_browser.save_screenshot.call_count == 2

    results = manager.execute(browser=mock_browser)
    assert results == []