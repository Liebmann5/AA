import pytest
from auto_apply.core.browser_factory import get_driver_adapter
from auto_apply.core.proxy_manager import ProxyManager
from auto_apply.exceptions import BrowserSetupError

# # The `mocker` fixture is essential for replacing the real factories with fakes.

REGISTRY_PATH = "auto_apply.core.browser_factory.FACTORY_REGISTRY"

def test_get_driver_adapter_selects_selenium_factory(mocker):
    mock_selenium_factory = mocker.MagicMock()
    mocker.patch.dict(REGISTRY_PATH, {"selenium": mock_selenium_factory})

    get_driver_adapter(framework="selenium", proxy_manager=None, preferred_browser="chrome")

    mock_selenium_factory.assert_called_once()
    mock_selenium_factory.return_value.get_driver.assert_called_once_with(preferred_browser="chrome")

def test_get_driver_adapter_selects_playwright_factory(mocker):
    mock_playwright_factory = mocker.MagicMock()
    mocker.patch.dict(REGISTRY_PATH, {"playwright": mock_playwright_factory})

    # We also need to ensure the selenium key doesn't exist for this test
    mocker.patch.dict(REGISTRY_PATH, {"selenium": mocker.MagicMock()}, clear=True)
    mocker.patch.dict(REGISTRY_PATH, {"playwright": mock_playwright_factory})

    get_driver_adapter(framework="playwright", preferred_browser="chromium")

    mock_playwright_factory.assert_called_once()
    mock_playwright_factory.return_value.get_driver.assert_called_once_with(preferred_browser="chromium")

def test_get_driver_adapter_is_case_insensitive(mocker):
    mock_selenium_factory = mocker.MagicMock()
    mocker.patch.dict(REGISTRY_PATH, {"selenium": mock_selenium_factory})

    get_driver_adapter(framework="SeLeNiUm")

    mock_selenium_factory.assert_called_once()

def test_get_driver_adapter_passes_proxy_manager(mocker):
    mock_selenium_factory = mocker.MagicMock()
    mocker.patch.dict(REGISTRY_PATH, {"selenium": mock_selenium_factory})
    mock_proxy_manager = mocker.create_autospec(ProxyManager, instance=True)

    get_driver_adapter(framework="selenium", proxy_manager=mock_proxy_manager)

    mock_selenium_factory.assert_called_once_with(proxy_manager=mock_proxy_manager)

def test_get_driver_adapter_propagates_exceptions_from_factory(mocker):
    error_message = "The underlying factory failed!"
    mock_selenium_factory = mocker.MagicMock()
    mock_selenium_factory.return_value.get_driver.side_effect = BrowserSetupError(error_message)
    mocker.patch.dict(REGISTRY_PATH, {"selenium": mock_selenium_factory})

    with pytest.raises(BrowserSetupError, match=error_message):
        get_driver_adapter(framework="selenium")

def test_get_driver_adapter_raises_error_for_unsupported_framework():
    """
    GIVEN: An unsupported framework name (e.g., "puppeteer").
    WHEN: `get_driver_adapter` is called.
    THEN: It should raise a `BrowserSetupError` and not call any factories.
    """
    # ARRANGE, ACT, & ASSERT
    with pytest.raises(BrowserSetupError, match="Framework 'puppeteer' is not supported"):
        get_driver_adapter(framework="puppeteer")