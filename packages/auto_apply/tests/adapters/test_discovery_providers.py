"""Unit tests for discovery providers and the _ats_site_filters helper.

All browser I/O is mocked. Tests verify:
- GoogleProvider and BingProvider use ResilientNavigator (not bare safe_navigate).
- _ats_site_filters extracts root domains from ATSRegistry descriptors.
- _ats_site_filters falls back to the hardcoded list when no registry is given.
- find_company_career_page builds the site-filter query from the registry.
"""

from unittest.mock import MagicMock, call

import pytest

from auto_apply.adapters.secondary.discovery.providers.google import (
    GoogleProvider,
    _ats_site_filters,
)
from auto_apply.adapters.secondary.discovery.providers.bing import BingProvider
from auto_apply.domain.ports.ats_port import ATSDescriptor


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_browser() -> MagicMock:
    b = MagicMock()
    b.current_url = "https://example.com"
    return b


def _mock_context(titles=("Engineer",), locations=("Remote",)) -> MagicMock:
    prefs = MagicMock()
    prefs.desired_job_titles = list(titles)
    prefs.preferred_locations = list(locations)
    prefs.max_search_results = 50

    profile = MagicMock()
    profile.search_preferences = prefs

    ctx = MagicMock()
    ctx.profile = profile
    return ctx


def _descriptor(name: str, *patterns: str) -> ATSDescriptor:
    return ATSDescriptor(
        name=name,
        url_patterns=patterns,
        login_wall_signals=(),
        success_signals=(),
        form_root_selector="",
        submit_button_selector="",
        multi_step=False,
    )


def _mock_registry(*descriptors: ATSDescriptor) -> MagicMock:
    r = MagicMock()
    r.all_descriptors.return_value = list(descriptors)
    return r


# ─────────────────────────────────────────────────────────────────────────────
# _ats_site_filters
# ─────────────────────────────────────────────────────────────────────────────

def test_ats_site_filters_returns_fallback_when_no_registry():
    result = _ats_site_filters(None)
    assert "greenhouse.io" in result
    assert "lever.co" in result
    assert len(result) >= 3


def test_ats_site_filters_extracts_root_domain_from_wildcard_pattern():
    reg = _mock_registry(_descriptor("greenhouse", "*.greenhouse.io/jobs/*"))
    result = _ats_site_filters(reg)
    assert "greenhouse.io" in result


def test_ats_site_filters_extracts_root_domain_from_subdomain_pattern():
    reg = _mock_registry(_descriptor("lever", "jobs.lever.co/*/apply"))
    result = _ats_site_filters(reg)
    assert "lever.co" in result


def test_ats_site_filters_deduplicates_same_root_domain():
    reg = _mock_registry(
        _descriptor("greenhouse", "*.greenhouse.io/jobs/*", "boards.greenhouse.io/*/jobs/*"),
    )
    result = _ats_site_filters(reg)
    assert result.count("greenhouse.io") == 1


def test_ats_site_filters_one_domain_per_descriptor():
    reg = _mock_registry(
        _descriptor("greenhouse", "*.greenhouse.io/jobs/*"),
        _descriptor("lever", "jobs.lever.co/*"),
        _descriptor("workday", "*.workday.com/*/apply"),
    )
    result = _ats_site_filters(reg)
    assert "greenhouse.io" in result
    assert "lever.co" in result
    assert "workday.com" in result


def test_ats_site_filters_returns_fallback_when_registry_is_empty():
    reg = _mock_registry()  # zero descriptors
    result = _ats_site_filters(reg)
    assert "greenhouse.io" in result


# ─────────────────────────────────────────────────────────────────────────────
# GoogleProvider — ResilientNavigator wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_google_provider_has_navigator():
    browser = _mock_browser()
    ctx = _mock_context()
    provider = GoogleProvider(browser, ctx)
    assert hasattr(provider, "navigator")


def test_google_provider_run_uses_navigator_not_safe_navigate(monkeypatch):
    """run() should delegate navigation to self.navigator, not self.safe_navigate."""
    browser = _mock_browser()
    ctx = _mock_context(titles=["SWE"], locations=["Remote"])
    provider = GoogleProvider(browser, ctx)

    navigate_calls = []

    def fake_navigate_with_fallback(url, context_data, validator):
        navigate_calls.append(url)
        return False  # skip scraping — we just need to confirm delegation

    provider.navigator.navigate_with_fallback = fake_navigate_with_fallback
    # safe_navigate must NOT be called
    safe_navigate_calls = []
    provider.safe_navigate = lambda url: safe_navigate_calls.append(url) or True

    provider.run()

    assert len(navigate_calls) == 1
    assert safe_navigate_calls == []


def test_google_provider_skips_query_when_navigator_fails(monkeypatch):
    browser = _mock_browser()
    ctx = _mock_context(titles=["SWE"], locations=["Remote"])
    provider = GoogleProvider(browser, ctx)
    provider.navigator.navigate_with_fallback = MagicMock(return_value=False)

    jobs = provider.run()
    assert jobs == []


def test_google_provider_accepts_ats_registry():
    reg = _mock_registry(_descriptor("greenhouse", "*.greenhouse.io/jobs/*"))
    browser = _mock_browser()
    ctx = _mock_context()
    provider = GoogleProvider(browser, ctx, ats_registry=reg)
    assert provider._ats_registry is reg


# ─────────────────────────────────────────────────────────────────────────────
# GoogleProvider — find_company_career_page + registry integration
# ─────────────────────────────────────────────────────────────────────────────

def test_find_company_career_page_uses_registry_domains():
    """The search URL should include site: filters derived from the registry."""
    reg = _mock_registry(
        _descriptor("greenhouse", "*.greenhouse.io/jobs/*"),
        _descriptor("lever", "jobs.lever.co/*"),
    )
    browser = _mock_browser()
    browser.find_element.return_value = None  # no result → returns None
    ctx = _mock_context()
    provider = GoogleProvider(browser, ctx, ats_registry=reg)

    provider.find_company_career_page("Acme")

    called_url: str = browser.get.call_args[0][0]
    assert "greenhouse.io" in called_url
    assert "lever.co" in called_url


def test_find_company_career_page_fallback_without_registry():
    browser = _mock_browser()
    browser.find_element.return_value = None
    ctx = _mock_context()
    provider = GoogleProvider(browser, ctx)

    provider.find_company_career_page("Acme")

    called_url: str = browser.get.call_args[0][0]
    assert "greenhouse.io" in called_url


def test_find_company_career_page_returns_none_when_no_result():
    browser = _mock_browser()
    browser.find_element.return_value = None
    provider = GoogleProvider(browser, _mock_context())
    assert provider.find_company_career_page("Acme Corp") is None


def test_find_company_career_page_returns_none_on_exception():
    browser = _mock_browser()
    browser.get.side_effect = Exception("network error")
    provider = GoogleProvider(browser, _mock_context())
    assert provider.find_company_career_page("Acme Corp") is None


# ─────────────────────────────────────────────────────────────────────────────
# BingProvider — ResilientNavigator wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_bing_provider_has_navigator():
    browser = _mock_browser()
    ctx = _mock_context()
    provider = BingProvider(browser, ctx)
    assert hasattr(provider, "navigator")


def test_bing_provider_run_uses_navigator_not_safe_navigate():
    browser = _mock_browser()
    ctx = _mock_context(titles=["PM"], locations=["NYC"])
    provider = BingProvider(browser, ctx)

    navigate_calls = []

    def fake_navigate_with_fallback(url, context_data, validator):
        navigate_calls.append(url)
        return False

    provider.navigator.navigate_with_fallback = fake_navigate_with_fallback
    safe_navigate_calls = []
    provider.safe_navigate = lambda url: safe_navigate_calls.append(url) or True

    provider.run()

    assert len(navigate_calls) == 1
    assert safe_navigate_calls == []


def test_bing_provider_skips_query_when_navigator_fails():
    browser = _mock_browser()
    ctx = _mock_context(titles=["PM"], locations=["NYC"])
    provider = BingProvider(browser, ctx)
    provider.navigator.navigate_with_fallback = MagicMock(return_value=False)
    assert provider.run() == []


def test_bing_provider_context_data_includes_query_and_location():
    """navigate_with_fallback must receive context_data with query+location keys."""
    browser = _mock_browser()
    ctx = _mock_context(titles=["Data Scientist"], locations=["Boston"])
    provider = BingProvider(browser, ctx)

    captured = {}

    def capture(url, context_data, validator):
        captured.update(context_data)
        return False

    provider.navigator.navigate_with_fallback = capture
    provider.run()

    assert captured.get("query") == "Data Scientist"
    assert captured.get("location") == "Boston"