"""HTTPClientPort adapter backed by stdlib urllib — zero extra dependencies.

This is the default HTTP client for worst-case environments (no ``requests``
installed). It handles redirects, decodes the response charset declared in
the Content-Type header, and returns a plain :class:`HTTPResponse`.

A ``requests``-backed adapter can be substituted via DI when retries or
connection pooling are important; this adapter is intentionally minimal.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from auto_apply.domain.ports.http_client_port import HTTPClientPort, HTTPResponse

logger = logging.getLogger(__name__)

# Realistic browser UA so sites don't serve minimal mobile pages.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",  # Avoid compressed responses without explicit handling.
}


class UrllibHTTPClient:
    """HTTPClientPort backed by Python's built-in ``urllib.request``.

    Satisfies the :class:`~auto_apply.domain.ports.http_client_port.HTTPClientPort`
    Protocol structurally — no explicit ``implements`` declaration needed.

    No external libraries required. Suitable for worst-case environments
    (library computer, 2 GB RAM, no pip access beyond stdlib).
    """

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 15.0,
    ) -> HTTPResponse:
        """Fetches *url* via a plain GET and returns the decoded response body.

        Args:
            url: Fully-qualified URL to fetch.
            headers: Optional headers merged with the default browser UA set.
            timeout: Request timeout in seconds (default 15 s).

        Returns:
            :class:`HTTPResponse` with status, decoded body, and final URL
            (after server redirects).
        """
        merged = {**_DEFAULT_HEADERS, **(headers or {})}
        req = urllib.request.Request(url, headers=merged)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                final_url: str = resp.geturl()
                charset: str = resp.headers.get_content_charset() or "utf-8"
                raw: bytes = resp.read()
                text = raw.decode(charset, errors="replace")
                logger.debug(
                    "UrllibHTTPClient.get | status=%d url=%s bytes=%d",
                    resp.status,
                    final_url,
                    len(raw),
                )
                return HTTPResponse(
                    status_code=resp.status,
                    text=text,
                    url=final_url,
                )

        except urllib.error.HTTPError as exc:
            logger.warning("HTTP error | url=%s status=%d", url, exc.code)
            return HTTPResponse(status_code=exc.code, text="", url=url)

        except Exception as exc:
            logger.warning("Request failed | url=%s error=%s", url, exc)
            return HTTPResponse(status_code=0, text="", url=url)
