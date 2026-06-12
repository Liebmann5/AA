"""Unit tests for adapters/secondary/network/urllib_http_client.py.

urllib.request is patched so no real network I/O occurs.
"""

import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from auto_apply.adapters.secondary.network.urllib_http_client import UrllibHTTPClient

_URLOPEN = "auto_apply.adapters.secondary.network.urllib_http_client.urllib.request.urlopen"


def _fake_response(
    body: bytes = b"<html>OK</html>",
    status: int = 200,
    url: str = "https://example.com",
    charset: str = "utf-8",
) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    resp.geturl.return_value = url
    resp.read.return_value = body
    headers = MagicMock()
    headers.get_content_charset.return_value = charset
    resp.headers = headers
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Happy-path GET
# ─────────────────────────────────────────────────────────────────────────────

def test_successful_get_returns_200_and_body():
    client = UrllibHTTPClient()
    with patch(_URLOPEN, return_value=_fake_response(b"<html>Hello</html>")):
        resp = client.get("https://example.com")
    assert resp.status_code == 200
    assert "<html>Hello</html>" in resp.text


def test_get_returns_final_redirect_url():
    client = UrllibHTTPClient()
    with patch(_URLOPEN, return_value=_fake_response(url="https://final.example.com")):
        resp = client.get("https://original.example.com")
    assert resp.url == "https://final.example.com"


def test_get_decodes_charset_from_header():
    body = "Héllo".encode("latin-1")
    client = UrllibHTTPClient()
    with patch(_URLOPEN, return_value=_fake_response(body=body, charset="latin-1")):
        resp = client.get("https://example.com")
    assert "Héllo" in resp.text


def test_get_falls_back_to_utf8_when_charset_missing():
    body = "Hello".encode("utf-8")
    client = UrllibHTTPClient()
    fake = _fake_response(body=body)
    fake.headers.get_content_charset.return_value = None
    with patch(_URLOPEN, return_value=fake):
        resp = client.get("https://example.com")
    assert "Hello" in resp.text
    assert resp.status_code == 200


def test_custom_headers_are_merged():
    client = UrllibHTTPClient()
    captured = {}

    def _urlopen(req, timeout=15.0):
        captured["headers"] = dict(req.headers)
        return _fake_response()

    with patch(_URLOPEN, side_effect=_urlopen):
        client.get("https://example.com", headers={"X-Custom": "test-value"})

    # Header keys are normalised to title case by urllib.request.Request.
    assert captured["headers"].get("X-custom") == "test-value"


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────

def test_http_error_returns_error_status():
    client = UrllibHTTPClient()
    http_err = urllib.error.HTTPError(
        url="https://example.com", code=404, msg="Not Found", hdrs=None, fp=None
    )
    with patch(_URLOPEN, side_effect=http_err):
        resp = client.get("https://example.com")
    assert resp.status_code == 404
    assert resp.text == ""


def test_network_exception_returns_status_zero():
    client = UrllibHTTPClient()
    with patch(_URLOPEN, side_effect=OSError("Network unreachable")):
        resp = client.get("https://example.com")
    assert resp.status_code == 0
    assert resp.text == ""
    assert resp.url == "https://example.com"


def test_timeout_exception_returns_status_zero():
    client = UrllibHTTPClient()
    with patch(_URLOPEN, side_effect=TimeoutError("timed out")):
        resp = client.get("https://example.com", timeout=1.0)
    assert resp.status_code == 0
