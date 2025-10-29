import pytest
import time
from auto_apply.utils.decorators import retry

# We use mocker to create fake functions and to control time.sleep.

def test_retry_succeeds_on_first_try(mocker):
    """
    GIVEN: A function that will succeed on its first call.
    WHEN: The function is decorated with @retry.
    THEN: The function should be called only once, return the correct value, and no delays should occur.
    """
    # ARRANGE
    # Mock time.sleep to ensure our test is fast and to verify it's not called.
    mock_sleep = mocker.patch("time.sleep")

    # Create a "spy" function that we can track.
    mock_func = mocker.Mock(return_value="success")

    # Define a function and apply our decorator to it.
    @retry(attempts=3, delay_seconds=1)
    def function_to_test():
        return mock_func()

    # ACT
    result = function_to_test()

    # ASSERT
    assert result == "success"
    mock_func.assert_called_once()
    mock_sleep.assert_not_called()


def test_retry_fails_once_then_succeeds(mocker):
    """
    GIVEN: A function that will fail on its first call but succeed on the second.
    WHEN: The function is decorated with @retry.
    THEN: The function should be called twice, a delay should occur, and the final success value should be returned.
    """
    # ARRANGE
    mock_sleep = mocker.patch("time.sleep")

    # Configure the spy to fail once, then succeed.
    mock_func = mocker.Mock(side_effect=[ValueError("Temporary network error"), "success"])

    @retry(attempts=3, delay_seconds=5, backoff=2)
    def function_to_test():
        return mock_func()

    # ACT
    result = function_to_test()

    # ASSERT
    assert result == "success"
    assert mock_func.call_count == 2

    # Check that sleep was called once after the first failure.
    mock_sleep.assert_called_once()
    # Check that it was called with a value close to the initial delay.
    # We use pytest.approx because the decorator adds random "jitter".
    assert 5.5 <= mock_sleep.call_args[0][0] <= 6.5

def test_retry_exhausts_all_attempts_and_raises_exception(mocker):
    """
    GIVEN: A function that will always fail.
    WHEN: The function is decorated with @retry(attempts=3).
    THEN: It should call the function 3 times, delay twice, and then re-raise the last exception.
    """
    # ARRANGE
    mock_sleep = mocker.patch("time.sleep")

    # This spy will always raise the same exception.
    original_exception = ConnectionError("Permanent failure")
    mock_func = mocker.Mock(side_effect=original_exception)

    @retry(attempts=3, delay_seconds=1, backoff=3)
    def function_to_test():
        return mock_func()

    # ACT & ASSERT
    # 1. Assert that the original exception is eventually re-raised.
    with pytest.raises(ConnectionError, match="Permanent failure"):
        function_to_test()

    # 2. Assert the function was called the maximum number of times.
    assert mock_func.call_count == 3

    # 3. Assert that sleep was called correctly between attempts.
    assert mock_sleep.call_count == 2 # Called after attempt 1 and attempt 2.

    # Check the exponential backoff logic.
    # First delay should be ~1 second.
    assert 1.5 <= mock_sleep.call_args_list[0][0][0] <= 2.5
    # Second delay should be initial_delay * backoff = 1 * 3 = ~3 seconds.
    assert 3.5 <= mock_sleep.call_args_list[1][0][0] <= 4.5