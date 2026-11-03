"""Pins for the arrival re-check at read time (owner run, 2026-11-03 11:11).

``https://www.bing.com/jobs?q=...`` loaded, passed the landing check made the
instant ``get()`` returned, and then moved itself by script to Bing's home
page (``/?form=REDIRERR``) within seconds. The reader then read the home
page's 20 news headlines as jobs, and all 20 were saved and vetted. The page
verdict did not stop it: on the real page it does not answer HOME_PAGE.

The fix re-checks the URL right before reading, with the same pure URL rule
(``check_landing``) the navigator applied at load time. No network, no DNS,
no page parsing.

Pins marked ``_teeth`` fail on the code before the fix (``f5392d6``).
"""

from __future__ import annotations

from types import SimpleNamespace

from auto_apply.adapters.secondary.discovery.strategies import navigators as nav
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    DirectURLNavigation,
    ResilientNavigator,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)

_REQUESTED = "https://www.bing.com/jobs?q=Backend+Engineer+Chicago%2C+IL"
_MOVED = "https://www.bing.com/?form=REDIRERR"

# A page the verdict cannot place (no search form, no list): the home-page
# gate does not fire on it, so only the arrival re-check can stop the read.
_UNPLACEABLE = (
    "<html><head><title>Search - Microsoft Bing</title></head><body>"
    + "".join(f"<div><a href='/news/{i}'><h3>Story {i}</h3></a></div>" for i in range(20))
    + "</body></html>"
)


class _MovingBrowser:
    """get() lands on the requested URL; the site later moves the page."""

    def __init__(self) -> None:
        self.current_url = "about:blank"
        self.title = "Search - Microsoft Bing"
        self.page_source = _UNPLACEABLE

    def get(self, url: str) -> None:
        self.current_url = url

    def move_by_script(self, url: str) -> None:
        self.current_url = url

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        return None

    def switch_to_default_content(self):
        return None


class _Engine:
    homepage_url = "https://www.bing.com"
    search_bar_selectors: list[str] = []
    engine_name = "bing"

    def build_search_url(self, instruction) -> str:
        return _REQUESTED


class _CountingExtractor:
    def __init__(self) -> None:
        self.mine_calls = 0

    def mine_jobs(self, source_name):
        self.mine_calls += 1
        return [SimpleNamespace(url="https://www.bing.com/news/1", title="Story")]

    def finalize_harvest(self, source_name):
        return []


class _Degradation:
    def __init__(self) -> None:
        self.blocked: list = []

    def is_benched(self, provider) -> bool:
        return False

    def evaluate_first_harvest(self, **kwargs) -> None:
        pass

    def mark_blocked(self, provider, reason) -> None:
        self.blocked.append((provider, reason))


def _navigated(monkeypatch) -> tuple[_MovingBrowser, ResilientNavigator]:
    monkeypatch.setattr(nav.time, "sleep", lambda s: None)
    browser = _MovingBrowser()
    navigator = ResilientNavigator(browser, [DirectURLNavigation(browser)])
    assert navigator.navigate_with_fallback(_Engine(), SimpleNamespace(), lambda: True)
    return browser, navigator


def _strategy(browser, arrival_check):
    fast, degradation = _CountingExtractor(), _Degradation()
    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="Bing",
        max_results=20,
        scroller=None,
        fast_extractor=fast,
        degradation_detector=degradation,
        arrival_check=arrival_check,
    )
    return strategy, fast, degradation


def test_navigator_sees_a_page_that_moved_after_loading_teeth(monkeypatch) -> None:
    browser, navigator = _navigated(monkeypatch)
    assert navigator.confirm_arrival().on_surface is True
    browser.move_by_script(_MOVED)
    landing = navigator.confirm_arrival()
    assert landing.on_surface is False
    assert landing.reason == "error-redirect"
    assert landing.requested == _REQUESTED
    assert navigator.landings[-1] == landing


def test_reader_reads_nothing_after_the_page_moved_teeth(monkeypatch) -> None:
    for entry in ("execute", "run"):
        browser, navigator = _navigated(monkeypatch)
        browser.move_by_script(_MOVED)
        strategy, fast, degradation = _strategy(browser, navigator.confirm_arrival)
        assert getattr(strategy, entry)() == [], entry
        assert fast.mine_calls == 0, entry
        # A moved page is not a block: the engine is not benched.
        assert degradation.blocked == [], entry


def test_reader_still_reads_when_the_page_stayed(monkeypatch) -> None:
    """GUARD: an unmoved page is read exactly as before."""
    browser, navigator = _navigated(monkeypatch)
    strategy, fast, _deg = _strategy(browser, navigator.confirm_arrival)
    strategy.execute()
    assert fast.mine_calls >= 1


def test_a_changed_path_alone_is_read_not_refused(monkeypatch) -> None:
    """GUARD: sites canonicalise search URLs onto another path; a moved path
    on the same site is logged and read, never refused."""
    browser, navigator = _navigated(monkeypatch)
    browser.move_by_script("https://www.bing.com/search?q=Backend+Engineer")
    strategy, fast, _deg = _strategy(browser, navigator.confirm_arrival)
    strategy.execute()
    assert fast.mine_calls >= 1


def test_no_recheck_without_a_checked_navigation() -> None:
    """GUARD: typing into a search box has no requested URL to compare."""
    navigator = ResilientNavigator(_MovingBrowser(), [])
    assert navigator.confirm_arrival() is None
