"""A privacy toggle must protect traffic or refuse to run — never pretend.

The defect
----------
``ApplicationConfig`` had ``use_proxies`` (a checkbox the user can turn on) but
no ``proxy_server`` field. ``BrowserCascade._build_config`` read
``getattr(app_config, "proxy_server", None)`` — always ``None`` — and passed it
to the provider, which launches direct when the proxy is ``None``. It also never
consulted ``use_proxies`` at all.

So a user who enabled proxies, believing their traffic was routed, was launched
on a direct connection with nothing to tell them. For a tool used by people
job-hunting from shared and monitored machines, that is a privacy failure, not a
missing feature — the interface made a promise the code broke.

The fix
-------
1. ``ApplicationConfig`` gains ``proxy_server: str | None = None``. Opt-in
   advanced feature, off by default.
2. ``_build_config`` honours ``use_proxies`` and passes the real endpoint.
3. Fail-closed: ``use_proxies`` on with no ``proxy_server`` raises
   ``ConfigurationError``, and the cascade re-raises it instead of swallowing it
   into "all browsers failed". The user is told, not silently exposed.

Boundary note
-------------
Proxy launch itself happens in the Selenium/Playwright provider, which needs a
real browser and is not exercised here. These tests verify the config the
cascade *builds* — the field, the toggle logic, and the fail-closed guard —
which is where the defect lived. The provider was already wired to use a
``proxy`` value when given one (selenium_provider.py); it simply never received
one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auto_apply.domain.exceptions import ConfigurationError
from auto_apply.domain.models.profile import ApplicationConfig
from auto_apply.infrastructure.browser_cascade import BrowserCascade


def _cascade(use_proxies: bool, proxy_server: str | None) -> BrowserCascade:
    registry = MagicMock()
    profile = MagicMock()
    profile.app_config = ApplicationConfig(
        use_proxies=use_proxies, proxy_server=proxy_server
    )
    registry.get_active_profile.return_value = profile
    resources = MagicMock()
    resources.headless = True
    resources.use_stealth_driver = False
    registry.get_runtime_profile.return_value = resources

    cascade = BrowserCascade.__new__(BrowserCascade)
    cascade._registry = registry
    return cascade


def test_proxy_server_field_exists() -> None:
    field = ApplicationConfig.model_fields.get("proxy_server")
    assert field is not None, (
        "ApplicationConfig has no proxy_server field, so the provider config's "
        "'proxy' is always None and use_proxies=true launches direct."
    )
    assert field.default is None, "proxy_server must default to None (feature off)."


def test_enabled_proxy_reaches_provider_config() -> None:
    cfg = _cascade(True, "10.0.0.1:8080")._build_config("chrome")
    assert cfg["proxy"] == "10.0.0.1:8080", (
        "use_proxies is on and a proxy_server is set, but the built config did "
        "not carry the proxy through to the provider."
    )


def test_enabled_proxy_without_server_fails_closed() -> None:
    """The privacy property: never launch direct when the user asked for a proxy."""
    with pytest.raises(ConfigurationError):
        _cascade(True, None)._build_config("chrome")


def test_disabled_proxy_launches_direct() -> None:
    """Proxies off means the user did not ask for protection; direct is correct."""
    cfg = _cascade(False, "10.0.0.1:8080")._build_config("chrome")
    assert cfg["proxy"] is None, (
        "use_proxies is off, so no proxy should be applied even if a server "
        "value happens to be present."
    )
