"""Provides resilience decorators for network and browser operations.

This module implements the 'Retry Pattern' with exponential backoff, allowing
the application to recover from transient failures (e.g., temporary internet loss).
"""

import logging
import random
import time
from collections.abc import Callable
from functools import wraps

logger = logging.getLogger(__name__)

def retry(
    attempts: int = 3,
    delay: float = 2.0,
    backoff: float = 1.5,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    rng: random.Random | None = None,
):
    """Decorates a function to retry upon failure.

    Args:
        attempts (int): Maximum number of runs.
        delay (float): Initial sleep time in seconds.
        backoff (float): Multiplier for delay after each failure.
        exceptions (tuple): Which exceptions trigger a retry.
        rng: Optional seeded random.Random for deterministic jitter.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for i in range(attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if i == attempts - 1:
                        logger.error(f"Function {func.__name__} failed after {attempts} attempts.")  # noqa: E501
                        raise last_exception

                    _rng = rng if rng is not None else random
                    wait = current_delay + _rng.uniform(0, 0.5)
                    logger.warning(
                        f"Retrying {func.__name__} ({i+1}/{attempts}) in {wait:.2f}s due to: {e}"  # noqa: E501
                    )
                    time.sleep(wait)
                    current_delay *= backoff
        return wrapper
    return decorator