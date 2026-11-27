"""A browser carried on a USB drive is a detected browser (flash-drive readiness).

Until this change detection read only installers and PATH, so a machine with
no browser installed refused to run even when ``AA_BROWSER_BINARY_PATH``
pointed at a working portable Chrome — the variable AA's own error message
recommends (measured on 8281571, open since 2026-10-01).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_apply.adapters.secondary.browser.playwright_provider import PlaywrightProvider
from auto_apply.adapters.secondary.os import detectors
from auto_apply.adapters.secondary.os.detectors import BrowserDetector


@pytest.fixture
def nothing_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_detect_windows", "_detect_macos", "_detect_linux"):
        monkeypatch.setattr(BrowserDetector, name, classmethod(lambda cls: []))
    for var in BrowserDetector.PORTABLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _exe(tmp_path: Path, name: str) -> str:
    f = tmp_path / name
    f.write_bytes(b"")
    return str(f)


def test_a_portable_chrome_is_found_on_a_machine_with_nothing_installed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nothing_installed: None) -> None:
    monkeypatch.setenv("AA_BROWSER_BINARY_PATH", _exe(tmp_path, "chrome.exe"))
    found = BrowserDetector.detect_browser_details()
    assert [b.name for b in found] == ["chrome"]
    assert found[0].path and found[0].path.endswith("chrome.exe")


def test_a_portable_firefox_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     nothing_installed: None) -> None:
    monkeypatch.setenv("AA_FIREFOX_BINARY_PATH", _exe(tmp_path, "firefox"))
    assert BrowserDetector.detect_installed_browsers() == ["firefox"]


def test_the_portable_browser_wins_over_an_installed_one_of_the_same_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nothing_installed: None) -> None:
    monkeypatch.setattr(BrowserDetector, "_detect_linux", classmethod(
        lambda cls: [detectors.DetectedBrowser("chrome", path="/usr/bin/google-chrome")]))
    monkeypatch.setattr(detectors.platform, "system", lambda: "Linux")
    portable = _exe(tmp_path, "chromium")
    monkeypatch.setenv("AA_BROWSER_BINARY_PATH", portable)
    found = BrowserDetector.detect_browser_details()
    assert [b.path for b in found] == [portable]


@pytest.mark.parametrize("value", ["", "/no/such/chrome", "notes.txt"])
def test_a_variable_that_names_no_browser_is_skipped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nothing_installed: None,
        value: str) -> None:
    if value == "notes.txt":
        value = _exe(tmp_path, value)
    monkeypatch.setenv("AA_BROWSER_BINARY_PATH", value)
    assert BrowserDetector.detect_installed_browsers() == []


@pytest.mark.parametrize(("path", "name"), [
    (r"E:\AA\browsers\chrome-win64\chrome.exe", "chrome"),
    ("/media/usb/chromium-browser", "chrome"),
    (r"E:\AA\Firefox\firefox.exe", "firefox"),
    ("msedge.exe", "edge"),
    ("/Volumes/AA/Brave Browser.app", "brave"),
    ("chrome-headless-shell", "chrome"),
    ("python.exe", None),
])
def test_the_browser_is_named_from_the_file_name_alone(path: str, name: str | None) -> None:
    assert BrowserDetector.portable_browser_name(path) == name


def test_playwright_launches_a_portable_chromium_and_never_a_portable_firefox(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chrome = _exe(tmp_path, "chrome.exe")
    monkeypatch.setenv("AA_BROWSER_BINARY_PATH", chrome)
    assert PlaywrightProvider.portable_executable("chromium") == chrome
    assert PlaywrightProvider.portable_executable("firefox") is None
    monkeypatch.setenv("AA_BROWSER_BINARY_PATH", _exe(tmp_path, "firefox.exe"))
    assert PlaywrightProvider.portable_executable("chromium") is None
