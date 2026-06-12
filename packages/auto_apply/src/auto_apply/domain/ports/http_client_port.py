"""Defines the contract for making HTTP GET requests.

Implementations live in ``adapters/secondary/network/``. The default is a
stdlib ``urllib`` adapter that requires no extra dependencies. An optional
``requests``-backed adapter can be injected when the library is available and
retry logic is desirable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class HTTPResponse:
    """Immutable result of a single HTTP GET request.

    Attributes:
        status_code: HTTP status code (200, 404, etc.).
        text: Response body decoded to a Unicode string.
        url: Final URL after any server-side redirects.
    """

    status_code: int
    text: str
    url: str


@runtime_checkable
class HTTPClientPort(Protocol):
    """Minimal interface for fetching a URL and returning its content.

    Only GET is required — AA's perception path never needs to submit forms
    via raw HTTP. Callers should not assume cookies, sessions, or JavaScript
    execution are available; this is a static-fetch interface.
    """

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> HTTPResponse:
        """Fetches the given URL and returns an HTTPResponse.

        Args:
            url: Fully-qualified URL to fetch.
            headers: Optional extra request headers merged with defaults.
            timeout: Request timeout in seconds.

        Returns:
            An :class:`HTTPResponse` with status, body text, and final URL.
        """
        ...
