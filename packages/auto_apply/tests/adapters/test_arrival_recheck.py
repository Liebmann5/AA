"""Pins for "is this still the page I asked for?" as a capability of every browser.

Owner run, 2026-11-03 11:11: ``https://www.bing.com/jobs?q=...`` loaded, passed
the landing check made the instant ``get()`` returned, then moved itself by
script to Bing's home page (``/?form=REDIRERR``). The reader read 20 news
headlines as jobs; all 20 were saved and vetted.

The check lives where every page AA opens passes: ``ResilientDriver``, the
wrapper every production browser is built inside (``browser_cascade``). Any
caller, on any page (a search engine, a careers page, a posting, a form, a
next page), asks the browser it already holds; nothing is wired per engine.
The rule is the pure URL comparison ``check_landing``: no network, no DNS.

Pins marked ``_teeth`` fail on the code before this change (``945d416``).
"""

from __future__ import annotations

from types import SimpleNamespace

from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.domain.ports.browser_port import BrowserInterface
from auto_apply.infrastructure.resilient_driver import ResilientDriver

_REQUESTED = "https://www.bing.com/jobs?q=Backend+Engineer+Chicago%2C+IL"
_MOVED = "https://www.bing.com/?form=REDIRERR"

# A page the verdict cannot place (no search form, no list): the home-page
# gate does not fire on it, so only the arrival check can stop the read.
_UNPLACEABLE = (
    "<html><head><title>Search - Microsoft Bing</title></head><body>"
    + "".join(f"<div><a href='/news/{i}'><h3>Story {i}</h3></a></div>" for i in range(20))
    + "</body></html>"
)


class _InnerDriver:
    """The wrapped adapter: get() lands; the site may later move the page."""

    def __init__(self) -> None:
        self.current_url = "about:blank"
        self.title = "Search - Microsoft Bing"
        self.page_source = _UNPLACEABLE

    def get(self, url: str) -> None:
        self.current_url = url

    def move_by_script(self, url: str) -> None:
        self.current_url = url

    def execute_script(self, script, *args):
        return "complete" if "readyState" in script else None

    def find_elements(self, by, selector):
        return []

    def switch_to_default_content(self):
        return None


def _browser() -> tuple[ResilientDriver, _InnerDriver]:
    inner = _InnerDriver()
    return ResilientDriver(inner), inner


class _CountingExtractor:
    def __init__(self) -> None:
        self.mine_calls = 0

    def mine_jobs(self, source_name):
        self.mine_calls += 1
        return [SimpleNamespace(url="https://www.bing.com/news/1", title="Story")]

    def finalize_harvest(self, source_name, **_kwargs):
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


def _strategy(browser):
    fast, degradation = _CountingExtractor(), _Degradation()
    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="Bing",
        max_results=20,
        scroller=None,
        fast_extractor=fast,
        degradation_detector=degradation,
    )
    return strategy, fast, degradation


def test_every_browser_sees_a_page_that_moved_after_loading_teeth() -> None:
    browser, inner = _browser()
    browser.get(_REQUESTED)
    assert browser.confirm_arrival().on_surface is True
    inner.move_by_script(_MOVED)
    landing = browser.confirm_arrival()
    assert landing.on_surface is False
    assert landing.reason == "error-redirect"
    assert landing.requested == _REQUESTED
    assert landing.landed == _MOVED


def test_reader_reads_nothing_after_the_page_moved_teeth() -> None:
    for entry in ("execute", "run"):
        browser, inner = _browser()
        browser.get(_REQUESTED)
        inner.move_by_script(_MOVED)
        strategy, fast, degradation = _strategy(browser)
        assert getattr(strategy, entry)() == [], entry
        assert fast.mine_calls == 0, entry
        # A moved page is not a block: the engine is not benched.
        assert degradation.blocked == [], entry


def test_a_blank_page_clears_the_request_teeth() -> None:
    """A blank page between attempts is not a request to compare against."""
    browser, _inner = _browser()
    browser.get(_REQUESTED)
    browser.get("about:blank")
    assert browser.confirm_arrival() is None


def test_the_port_answers_unknown_by_default() -> None:
    """GUARD: a browser that does not track navigations says "unknown"
    (None), never "fine" and never "moved"."""
    assert BrowserInterface.confirm_arrival(SimpleNamespace()) is None


def test_reader_still_reads_when_the_page_stayed() -> None:
    """GUARD: an unmoved page is read exactly as before."""
    browser, _inner = _browser()
    browser.get(_REQUESTED)
    strategy, fast, _deg = _strategy(browser)
    strategy.execute()
    assert fast.mine_calls >= 1


def test_a_changed_path_alone_is_read_not_refused() -> None:
    """GUARD: sites canonicalise search URLs onto another path; a moved path
    on the same site is logged and read, never refused."""
    browser, inner = _browser()
    browser.get(_REQUESTED)
    inner.move_by_script("https://www.bing.com/search?q=Backend+Engineer")
    strategy, fast, _deg = _strategy(browser)
    strategy.execute()
    assert fast.mine_calls >= 1


def test_a_browser_without_the_capability_is_read_as_before() -> None:
    """GUARD: test doubles and future adapters without the method degrade to
    today's behaviour (capability detection, not an assumption)."""
    inner = _InnerDriver()
    inner.get(_REQUESTED)
    inner.move_by_script(_MOVED)
    strategy, fast, _deg = _strategy(inner)
    strategy.execute()
    assert fast.mine_calls >= 1
