import pytest
from auto_apply.core.browser import BrowserManager
from auto_apply.core.browser_interface import BrowserInterface
from auto_apply.exceptions import ApplicationError

# The `mocker` fixture is essential here for creating our fake browser adapter.

def test_init_with_valid_adapter(mocker):
    """
    GIVEN: A mock object that correctly implements the BrowserInterface.
    WHEN: A BrowserManager is instantiated with this adapter.
    THEN: The manager should be created successfully without errors.
    """
    # ARRANGE
    # create_autospec creates a mock that strictly follows the interface.
    # If BrowserInterface changes, this test might fail, which is a good thing!
    mock_adapter = mocker.create_autospec(BrowserInterface, instance=True)

    # ACT & ASSERT (Assert that no exception is raised)
    try:
        manager = BrowserManager(browser_adapter=mock_adapter)
        assert manager.adapter is mock_adapter
    except TypeError:
        pytest.fail("BrowserManager raised TypeError with a valid adapter.")


def test_init_with_invalid_object_raises_typeerror():
    """
    GIVEN: An object that does NOT implement the BrowserInterface (e.g., a plain object).
    WHEN: A BrowserManager is instantiated with this invalid object.
    THEN: It should raise a TypeError.
    """
    # ARRANGE
    invalid_object = object()

    # ACT & ASSERT
    with pytest.raises(TypeError, match="must be a valid BrowserInterface adapter"):
        BrowserManager(browser_adapter=invalid_object)


def test_context_manager_enter_returns_the_adapter(mocker):
    """
    GIVEN: A BrowserManager initialized with a valid adapter.
    WHEN: The context manager is entered (the `with` statement starts).
    THEN: The value returned by the `as` clause should be the original adapter.
    """
    # ARRANGE
    mock_adapter = mocker.create_autospec(BrowserInterface, instance=True)
    manager = BrowserManager(browser_adapter=mock_adapter)

    # ACT
    with manager as browser_in_context:
        # ASSERT
        assert browser_in_context is mock_adapter


def test_context_manager_exit_calls_close_on_adapter(mocker):
    """
    GIVEN: A BrowserManager initialized with a valid adapter.
    WHEN: The context manager is exited (the `with` block finishes).
    THEN: The `close()` method on the adapter must be called exactly once.
    """
    # ARRANGE
    mock_adapter = mocker.create_autospec(BrowserInterface, instance=True)
    manager = BrowserManager(browser_adapter=mock_adapter)

    # ACT
    with manager:
        # We can even assert that `close` has NOT been called yet.
        mock_adapter.close.assert_not_called()

    # ASSERT
    # After the `with` block has finished, `__exit__` should have been called.
    mock_adapter.close.assert_called_once()


def test_context_manager_exit_handles_exceptions_during_close(mocker, caplog):
    """
    GIVEN: An adapter whose `close()` method will raise an exception.
    WHEN: The BrowserManager's context is exited.
    THEN: The manager should catch the exception, log it, and not crash.
    """
    # ARRANGE
    mock_adapter = mocker.create_autospec(BrowserInterface, instance=True)
    # Configure the mock's `close` method to have a side effect: raising an error.
    error_message = "Browser failed to shut down!"
    mock_adapter.close.side_effect = ApplicationError(error_message)

    manager = BrowserManager(browser_adapter=mock_adapter)

    # `caplog` is a pytest fixture that captures logging output.
    caplog.clear() # Clear any previous logs

    # ACT
    # We expect this `with` block to run without raising an unhandled exception.
    # If it crashes, the test will fail automatically.
    with manager:
        pass

    # ASSERT
    # 1. The `close` method was still attempted.
    mock_adapter.close.assert_called_once()

    # 2. Check that the exception was logged.
    assert len(caplog.records) > 0
    assert "An error occurred while shutting down the browser adapter." in caplog.text
    assert error_message in caplog.text