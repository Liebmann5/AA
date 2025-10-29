"""Provides reusable function decorators for enhancing application logic.

This module contains decorators that can be applied to functions or methods
to add cross-cutting functionality, such as automatic retries on failure,
without cluttering the core logic of the function itself.
"""
import logging
import time
import random

logger = logging.getLogger(__name__)

def retry(attempts: int = 3, delay_seconds: float = 5, backoff: float = 2):
    """A decorator for retrying a function if it raises an exception.

    This decorator wraps a function in a retry loop. If the wrapped function
    raises any exception, it will be caught, and the function will be called
    again after a delay. This process repeats until the function succeeds or
    the maximum number of `attempts` is reached.

    The delay between retries uses an exponential backoff strategy with added
    "jitter" (a small random variance). This is a best practice for handling
    temporary network or service unavailability, as it avoids overwhelming a
    struggling service with rapid, repeated requests.

    Example Usage:
        @retry(attempts=5, delay_seconds=2)
        def connect_to_flaky_service():
            # ... code that might raise an exception ...
            pass

    Args:
        attempts: The maximum number of times to try the function.
        delay_seconds: The initial delay between the first and second attempt.
        backoff: The multiplier for the delay. The delay for subsequent
            retries will be `delay_seconds * (backoff ** (attempt - 1))`.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            current_delay = delay_seconds
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == attempts:
                        logger.error(
                            "Function '%s' failed after %d attempts. No more retries.",
                            func.__name__, attempts
                        )
                        raise
                    wait_time = current_delay + random.uniform(0.5, 1.5)
                    logger.warning(
                        "Attempt %d/%d for function '%s' failed: %s. Retrying in %.2f seconds...",
                        attempt, attempts, func.__name__, e, wait_time
                    )
                    time.sleep(wait_time)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator