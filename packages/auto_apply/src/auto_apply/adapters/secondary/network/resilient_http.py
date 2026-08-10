"""Resilient HTTP client with automatic retry and backoff.

Wraps the requests library to add:
  - Automatic retry with exponential backoff
  - 429 (Too Many Requests) detection with Retry-After header support
  - Connection drop recovery
  - Configurable timeout per request

Architecture: This is an adapter — it may use requests directly.
It must not be imported by domain or application layers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def build_resilient_session(
    total_retries: int = 3,
    backoff_factor: float = 1.5,
    timeout: int = 30,
    respect_retry_after: bool = True,
) -> requests.Session:
    """Build a requests.Session with automatic retry and backoff configured.

    Args:
        total_retries: Maximum retry attempts per request.
        backoff_factor: Seconds multiplier for exponential backoff.
                        Retry 1 waits backoff_factor seconds,
                        Retry 2 waits 2 * backoff_factor seconds, etc.
        timeout: Default request timeout in seconds.
        respect_retry_after: Whether to honor Retry-After response headers.

    Returns:
        A configured requests.Session ready for use.

    Example:
        session = build_resilient_session()
        response = session.get("https://example.com/jobs/123", timeout=30)
    """
    session = requests.Session()

    retry_strategy = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[
            429,   # Too Many Requests — the most common block
            500,   # Internal Server Error — transient ATS issues
            502,   # Bad Gateway
            503,   # Service Unavailable
            504,   # Gateway Timeout
        ],
        allowed_methods=["GET", "HEAD", "OPTIONS"],  # Never retry POST (side effects)
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Set a default timeout on the session
    # Deliberate: wraps the bound method so every call gets a default timeout.
    session.request = _patch_timeout(  # type: ignore[method-assign]
        session.request, default_timeout=timeout
    )

    if respect_retry_after:
        session.hooks["response"].append(_handle_retry_after)

    return session


def _patch_timeout(original_request, default_timeout: int):
    """Wrap session.request to inject a default timeout when none is given."""
    def patched(*args: Any, **kwargs: Any) -> requests.Response:
        if "timeout" not in kwargs:
            kwargs["timeout"] = default_timeout
        return original_request(*args, **kwargs)
    return patched


def _handle_retry_after(
    response: requests.Response, *args: Any, **kwargs: Any
) -> None:
    """Log 429 responses and honor Retry-After headers."""
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "")
        try:
            wait = float(retry_after)
        except (ValueError, TypeError):
            wait = 60.0  # Default: wait 60 seconds if header is absent or unparseable

        logger.warning(
            "Rate limited (429) by %s — cooling down for %.0f seconds",
            response.url[:60],
            wait,
        )
        time.sleep(wait)


def safe_get(
    url: str,
    session: requests.Session | None = None,
    timeout: int = 30,
    accept_status: set[int] | None = None,
) -> requests.Response | None:
    """Perform a GET request with graceful failure handling.

    Returns None on any connection error instead of raising.
    Useful for job description fetching where a 404 or timeout
    should not crash the session.

    Args:
        url: The URL to fetch.
        session: Optional session (uses a default session if None).
        timeout: Request timeout in seconds.
        accept_status: Set of HTTP status codes to treat as success.
                       Defaults to {200, 201, 206}.

    Returns:
        The Response object on success, or None on failure.
    """
    if accept_status is None:
        accept_status = {200, 201, 206}

    if session is None:
        session = build_resilient_session(total_retries=2, timeout=timeout)

    try:
        response = session.get(url, timeout=timeout)
        if response.status_code in accept_status:
            return response
        logger.debug(
            "safe_get: non-success status %d for %s",
            response.status_code,
            url[:60],
        )
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("safe_get: connection error fetching %s", url[:60])
        return None
    except requests.exceptions.Timeout:
        logger.warning(
            "safe_get: timeout after %ds fetching %s", timeout, url[:60]
        )
        return None
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "safe_get: request failed for %s: %s", url[:60], exc
        )
        return None