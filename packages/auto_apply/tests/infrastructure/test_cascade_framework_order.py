"""Cascade framework ordering is config-driven, deterministic, and behavior-
preserving by default; stealth-Chrome/driver mismatches are surfaced honestly.

Step 1b guards:
  * default framework_order reproduces the historical candidate list exactly
    (no regression),
  * a custom framework_order reorders the framework tier while keeping browser
    order within a framework and 'static' as the final fallback,
  * the version-mismatch detector recognizes the real undetected_chromedriver /
    Selenium signature and ignores unrelated errors.
"""
from __future__ import annotations

from auto_apply.domain.models.browser_candidates import (
    DEFAULT_FRAMEWORK_ORDER,
    build_filtered_candidates,
)
from auto_apply.infrastructure.browser_cascade import (
    _is_stealth_chrome_version_mismatch,
)

_NATIVE = {
    "playwright": ["chromium", "firefox", "webkit"],
    "camoufox": ["firefox"],
    "selenium": [],
}
_AVAIL = ["playwright", "selenium"]
_OS = ["chrome", "firefox", "edge", "brave"]


def _tuples(cands):
    return [(c.framework, c.browser_type, c.source) for c in cands]


def test_default_order_is_behavior_preserving():
    """framework_order=None must reproduce the historical candidate list exactly."""
    got = _tuples(build_filtered_candidates(_AVAIL, _OS, _NATIVE, None))
    assert got == [
        ("playwright", "chromium", "bundled"),
        ("playwright", "firefox", "bundled"),
        ("playwright", "webkit", "bundled"),
        ("selenium", "chrome", "os"),
        ("selenium", "firefox", "os"),
        ("selenium", "edge", "os"),
        ("static", "none", "none"),
    ], got


def test_explicit_default_matches_none():
    a = _tuples(build_filtered_candidates(_AVAIL, _OS, _NATIVE, None))
    b = _tuples(
        build_filtered_candidates(_AVAIL, _OS, _NATIVE, None, DEFAULT_FRAMEWORK_ORDER)
    )
    assert a == b


def test_custom_framework_order_reorders_tier_keeps_static_last():
    got = _tuples(
        build_filtered_candidates(
            _AVAIL, _OS, _NATIVE, None, framework_order=["selenium", "playwright"]
        )
    )
    assert got[-1] == ("static", "none", "none")
    assert got.index(("selenium", "chrome", "os")) < got.index(
        ("playwright", "chromium", "bundled")
    )
    # browser order within selenium is preserved
    sel = [b for f, b, _ in got if f == "selenium"]
    assert sel == ["chrome", "firefox", "edge"]


def test_unknown_framework_tolerated():
    got = _tuples(
        build_filtered_candidates(
            _AVAIL, _OS, _NATIVE, None, framework_order=["nonexistent", "selenium"]
        )
    )
    assert ("selenium", "chrome", "os") in got
    assert ("playwright", "chromium", "bundled") in got  # present-but-unlisted kept
    assert got[-1] == ("static", "none", "none")


def test_version_mismatch_detected_and_scoped():
    real = (
        "SeleniumProvider could not start 'chrome': Message: session not created: "
        "This version of ChromeDriver only supports Chrome version 151 Current "
        "browser version is 150.0.7871.125"
    )
    assert _is_stealth_chrome_version_mismatch("chrome", real) is True
    # unrelated chrome failure is NOT flagged as a version mismatch
    assert _is_stealth_chrome_version_mismatch("chrome", "connection refused") is False
    # a firefox failure is never a chrome-version mismatch
    assert _is_stealth_chrome_version_mismatch("firefox", real) is False
