import pytest
from auto_apply.core.selenium_factory import SeleniumFactory
from auto_apply.exceptions import BrowserSetupError

# We will be mocking the browser drivers themselves and the OS browser detector.
# Assume BrowserInterface and SeleniumAdapter are tested elsewhere.
# Assume browser_options functions are simple and don't need dedicated tests for now.

def test_factory_respects_user_preference_successfully(mocker):
    """
    GIVEN: A user prefers 'firefox'.
    WHEN: The factory gets a driver.
    THEN: It should attempt to create a Firefox driver and nothing else.
    """
    # ARRANGE
    # Mock the actual browser driver classes.
    mock_uc_chrome = mocker.patch("auto_apply.core.selenium_factory.uc.Chrome")
    mock_webdriver_firefox = mocker.patch("auto_apply.core.selenium_factory.webdriver.Firefox")

    factory = SeleniumFactory(proxy_manager=None)

    # ACT
    driver_adapter = factory.get_driver(preferred_browser="firefox")

    # ASSERT
    # 1. Assert that it tried to create a Firefox driver.
    mock_webdriver_firefox.assert_called_once()

    # 2. Assert that it did NOT try to create a Chrome driver.
    mock_uc_chrome.assert_not_called()

    # 3. Assert that it returned an adapter wrapping the driver instance.
    assert driver_adapter._driver == mock_webdriver_firefox.return_value


def test_factory_falls_back_if_preferred_browser_fails(mocker):
    """
    GIVEN: A user prefers 'edge', but it will fail to launch.
    AND: 'chrome' is detected as an installed browser.
    WHEN: The factory gets a driver.
    THEN: It should attempt 'edge' first, fail, and then successfully create 'chrome'.
    """
    # ARRANGE
    # Mock the OS detector to report that 'chrome' is available as a fallback.
    mocker.patch("auto_apply.core.selenium_factory.get_installed_browsers", return_value=["chrome"])

    # Mock the browser driver classes, making Edge fail.
    mock_webdriver_edge = mocker.patch("auto_apply.core.selenium_factory.webdriver.Edge", side_effect=Exception("Edge driver failed!"))
    mock_uc_chrome = mocker.patch("auto_apply.core.selenium_factory.uc.Chrome")

    factory = SeleniumFactory()

    # ACT
    driver_adapter = factory.get_driver(preferred_browser="edge")

    # ASSERT
    # 1. It tried to create the preferred browser.
    mock_webdriver_edge.assert_called_once()

    # 2. It then fell back and successfully created the detected browser.
    mock_uc_chrome.assert_called_once()

    # 3. The final returned adapter is for the successful browser.
    assert driver_adapter._driver == mock_uc_chrome.return_value


def test_factory_uses_detected_browsers_in_priority_order(mocker):
    """
    GIVEN: No browser preference is given.
    AND: The OS detector finds 'firefox' and 'chrome'.
    WHEN: The factory gets a driver.
    THEN: It should try 'chrome' first (due to priority) and succeed.
    """
    # ARRANGE
    # Note: `get_installed_browsers` already returns a sorted list, so we simulate that.
    mocker.patch("auto_apply.core.selenium_factory.get_installed_browsers", return_value=["chrome", "firefox"])

    mock_uc_chrome = mocker.patch("auto_apply.core.selenium_factory.uc.Chrome")
    mock_webdriver_firefox = mocker.patch("auto_apply.core.selenium_factory.webdriver.Firefox")

    factory = SeleniumFactory()

    # ACT
    driver_adapter = factory.get_driver(preferred_browser="any") # "any" is the default

    # ASSERT
    # 1. It tried the highest priority browser.
    mock_uc_chrome.assert_called_once()

    # 2. Since the first one succeeded, it never tried the second one.
    mock_webdriver_firefox.assert_not_called()

    # 3. The result is the chrome driver.
    assert driver_adapter._driver == mock_uc_chrome.return_value


def test_factory_skips_failed_detected_browser_and_tries_next(mocker):
    """
    GIVEN: No browser preference is given.
    AND: The highest priority browser ('chrome') will fail.
    AND: A lower priority browser ('firefox') is also available.
    WHEN: The factory gets a driver.
    THEN: It should attempt 'chrome', fail, and then successfully create 'firefox'.
    """
    # ARRANGE
    mocker.patch("auto_apply.core.selenium_factory.get_installed_browsers", return_value=["chrome", "firefox"])

    # Make the higher-priority browser fail.
    mock_uc_chrome = mocker.patch("auto_apply.core.selenium_factory.uc.Chrome", side_effect=Exception("Chrome failed!"))
    mock_webdriver_firefox = mocker.patch("auto_apply.core.selenium_factory.webdriver.Firefox")

    factory = SeleniumFactory()

    # ACT
    driver_adapter = factory.get_driver()

    # ASSERT
    mock_uc_chrome.assert_called_once()
    mock_webdriver_firefox.assert_called_once()
    assert driver_adapter._driver == mock_webdriver_firefox.return_value


def test_factory_raises_error_if_no_browsers_are_detected(mocker):
    """
    GIVEN: The OS detector finds no supported browsers.
    WHEN: The factory gets a driver with no preference.
    THEN: It should raise a `BrowserSetupError` immediately.
    """
    # ARRANGE
    mocker.patch("auto_apply.core.selenium_factory.get_installed_browsers", return_value=[])
    factory = SeleniumFactory()

    # ACT & ASSERT
    with pytest.raises(BrowserSetupError, match="No supported Selenium browsers found"):
        factory.get_driver()


def test_factory_raises_error_if_all_attempts_fail(mocker):
    """
    GIVEN: Both preferred and fallback browsers will fail to launch.
    WHEN: The factory gets a driver.
    THEN: It should raise a `BrowserSetupError` after all attempts are exhausted.
    """
    # ARRANGE
    mocker.patch("auto_apply.core.selenium_factory.get_installed_browsers", return_value=["firefox"])

    # Make all available drivers fail.
    mock_uc_chrome = mocker.patch("auto_apply.core.selenium_factory.uc.Chrome", side_effect=Exception("Chrome failed!"))
    mock_webdriver_firefox = mocker.patch("auto_apply.core.selenium_factory.webdriver.Firefox", side_effect=Exception("Firefox failed!"))

    factory = SeleniumFactory()

    # ACT & ASSERT
    with pytest.raises(BrowserSetupError, match="All detected Selenium browsers failed to initialize"):
        # User prefers a browser that isn't even "installed".
        factory.get_driver(preferred_browser="chrome")

    # Check that it tried both the preferred and the fallback.
    mock_uc_chrome.assert_called_once()
    mock_webdriver_firefox.assert_called_once()