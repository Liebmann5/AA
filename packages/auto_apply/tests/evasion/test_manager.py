import pytest
from auto_apply.evasion.manager import get_evasion_manager
from auto_apply.config import EvasionSettings
from auto_apply.evasion.session import SessionManager

# We will mock the browser adapters and the evasion strategies to test the factory's logic.
from auto_apply.adapters.selenium_adapter import SeleniumAdapter
from auto_apply.adapters.playwright_adapter import PlaywrightAdapter
from auto_apply.evasion.strategies.selenium_strategy import SeleniumEvasionStrategy
from auto_apply.evasion.strategies.playwright_strategy import PlaywrightEvasionStrategy

# The `mocker` fixture is essential for these tests.

def test_get_evasion_manager_selects_selenium_strategy(mocker):
    """
    GIVEN: A SeleniumAdapter instance is provided as the browser.
    WHEN: `get_evasion_manager` is called.
    THEN: It should return an instance of `SeleniumEvasionStrategy`.
    """
    # ARRANGE
    # 1. Create a mock browser adapter that identifies itself as 'selenium'.
    mock_browser = mocker.create_autospec(SeleniumAdapter, instance=True)
    # We must set the `framework_name` property on the mock for the factory to read.
    type(mock_browser).framework_name = mocker.PropertyMock(return_value="selenium")

    # 2. Create dummy instances for the other arguments.
    mock_settings = EvasionSettings()
    mock_session = mocker.create_autospec(SessionManager, instance=True)

    # ACT
    evasion_manager = get_evasion_manager(mock_browser, mock_settings, mock_session)

    # ASSERT
    # Check that the returned object is an instance of the correct class.
    assert isinstance(evasion_manager, SeleniumEvasionStrategy)
    # Verify the manager was initialized with the correct arguments.
    assert evasion_manager.browser is mock_browser
    assert evasion_manager.settings is mock_settings
    assert evasion_manager.session is mock_session


def test_get_evasion_manager_selects_playwright_strategy(mocker):
    """
    GIVEN: A PlaywrightAdapter instance is provided as the browser.
    WHEN: `get_evasion_manager` is called.
    THEN: It should return an instance of `PlaywrightEvasionStrategy`.
    """
    # ARRANGE
    mock_browser = mocker.create_autospec(PlaywrightAdapter, instance=True)
    type(mock_browser).framework_name = mocker.PropertyMock(return_value="playwright")

    mock_settings = EvasionSettings()
    mock_session = mocker.create_autospec(SessionManager, instance=True)

    # ACT
    evasion_manager = get_evasion_manager(mock_browser, mock_settings, mock_session)

    # ASSERT
    assert isinstance(evasion_manager, PlaywrightEvasionStrategy)
    assert evasion_manager.browser is mock_browser


def test_get_evasion_manager_raises_error_for_unsupported_framework(mocker):
    """
    GIVEN: A browser adapter with an unknown framework_name is provided.
    WHEN: `get_evasion_manager` is called.
    THEN: It should raise a `NotImplementedError`.
    """
    # ARRANGE
    # Create a generic mock that doesn't inherit from a specific adapter,
    # but has the necessary property.
    mock_browser = mocker.Mock()
    type(mock_browser).framework_name = mocker.PropertyMock(return_value="unsupported_framework")

    mock_settings = EvasionSettings()
    mock_session = mocker.create_autospec(SessionManager, instance=True)

    # ACT & ASSERT
    with pytest.raises(NotImplementedError, match="No evasion strategy has been implemented for framework: unsupported_framework"):
        get_evasion_manager(mock_browser, mock_settings, mock_session)