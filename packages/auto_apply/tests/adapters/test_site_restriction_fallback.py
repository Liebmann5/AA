"""Pins: a page that dropped the query's ``site:`` restriction is not read,
the typed search is tried, and an engine that drops it on every route is
not sent that restriction again; the session says so.

Owner run 2026-11-08: in AA's browser Google answered six of seven platform
searches (``site:jobs.ashbyhq.com ("Software Engineer")`` ...) with one
unrestricted page, ZipRecruiter first. AA read it, kept nothing, and the
session said only that nothing was found. The same queries typed in the
owner's browser kept the restriction.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from auto_apply.adapters.secondary.discovery.providers import google as google_module
from auto_apply.adapters.secondary.discovery.providers.google import GoogleProvider
from auto_apply.adapters.secondary.discovery.strategies import navigators as nav
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    HumanSearchNavigation,
    ResilientNavigator,
)
from auto_apply.application.services.auditing.degradation_detector import (
    SilentDegradationDetector,
)
from auto_apply.domain.events import Event
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.ports.page_understanding_port import SERPStructure

_SITE_QUERY = 'site:jobs.ashbyhq.com ("Software Engineer")'
_UNRESTRICTED = ("www.ziprecruiter.com", "www.indeed.com", "www.glassdoor.com", "www.linkedin.com")
_KEPT = ("jobs.ashbyhq.com",) * 9


class _Route:
    """A navigation route that lands on a page whose results are *hosts*."""

    def __init__(self, label: str, hosts: tuple[str, ...], page: dict, log: list) -> None:
        self.route_label, self._hosts, self._page, self._log = label, hosts, page, log
        self.last_landing = None

    @property
    def name(self) -> str:
        return self.route_label

    def navigate(self, engine, instruction) -> bool:
        self._log.append(self.route_label)
        self._page["hosts"] = self._hosts
        return True


class _Reader:
    """The page reader: the hosts of the page the last route landed on."""

    def __init__(self, page: dict) -> None:
        self._page, self.reads = page, 0

    def analyze_serp(self, context) -> SERPStructure:
        self.reads += 1
        return SERPStructure(result_hosts=tuple(self._page.get("hosts", ())))


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[Event, dict]] = []

    def publish(self, event, payload=None) -> None:
        self.published.append((event, payload))


class _SpyScraper:
    runs = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def execute(self):
        type(self).runs += 1
        return []


def _provider(monkeypatch, direct, typed, reader=True):
    monkeypatch.setattr(nav.time, "sleep", lambda s: None)
    monkeypatch.setattr(google_module, "GenericSERPStrategy", _SpyScraper)
    _SpyScraper.runs = 0
    bus = _Bus()
    detector = SilentDegradationDetector(None, event_bus=bus)
    page: dict = {}
    tried: list[str] = []
    provider = GoogleProvider(browser=MagicMock(), degradation_detector=detector)
    provider._is_page_healthy = lambda: True  # the block verdict is pinned elsewhere
    provider._engine_strategy = MagicMock()
    provider._page_understanding = _Reader(page) if reader else None
    provider.navigator = ResilientNavigator(
        MagicMock(),
        [_Route("direct URL", direct, page, tried), _Route("typed search", typed, page, tried)],
    )
    return provider, tried, bus, detector


def _site_instruction() -> SearchInstruction:
    return SearchInstruction(
        title="Software Engineer", location="Chicago, IL",
        raw_query_string=_SITE_QUERY, engine="google", platform="ashby",
    )


def test_a_dropped_restriction_is_not_read_and_the_typed_search_is_tried_teeth(monkeypatch):
    """TEETH: before, the unrestricted page passed navigation and was read."""
    provider, tried, bus, _ = _provider(monkeypatch, direct=_UNRESTRICTED * 3, typed=_KEPT)
    provider.run(_site_instruction())
    assert tried == ["direct URL", "typed search"]
    assert _SpyScraper.runs == 1, "the page that kept the restriction is read"
    assert not [e for e, _ in bus.published if e is Event.SEARCH_RESTRICTION_IGNORED]


def test_dropped_on_every_route_is_reported_once_and_not_sent_again_teeth(monkeypatch):
    """TEETH: before, nothing recorded the drop and every later search with
    the same restriction went out and came back unrestricted."""
    provider, tried, bus, detector = _provider(
        monkeypatch, direct=_UNRESTRICTED * 3, typed=_UNRESTRICTED * 2
    )
    assert provider.run(_site_instruction()) == []
    assert _SpyScraper.runs == 0, "neither unrestricted page is read"
    events = [p for e, p in bus.published if e is Event.SEARCH_RESTRICTION_IGNORED]
    assert len(events) == 1
    assert events[0]["provider"] == "google"
    assert events[0]["restriction"] == "jobs.ashbyhq.com"
    assert "direct URL: 0 of 12 results" in events[0]["detail"]
    assert "typed search: 0 of 8 results" in events[0]["detail"]
    assert detector.restriction_ignored("google", "jobs.ashbyhq.com")

    tried.clear()
    assert provider.run(_site_instruction()) == []
    assert tried == [], "the same restriction is not sent to the engine again"


def test_other_restrictions_and_plain_searches_still_run(monkeypatch):
    """Scoped to the restriction: Google kept site:boards.greenhouse.io in
    the same session it dropped the others."""
    provider, tried, _, detector = _provider(monkeypatch, direct=_KEPT, typed=_KEPT)
    detector.mark_restriction_ignored("google", "jobs.ashbyhq.com", "seen")
    greenhouse = SearchInstruction(
        title="Software Engineer", raw_query_string='site:boards.greenhouse.io ("Software Engineer")',
        engine="google", platform="greenhouse",
    )
    provider._page_understanding = _Reader({"hosts": ("boards.greenhouse.io",) * 9})
    provider.run(greenhouse)
    provider.run(SearchInstruction(title="Software Engineer", location="Chicago, IL"))
    assert tried == ["direct URL", "direct URL"]


def test_an_unproven_drop_keeps_the_page(monkeypatch):
    """Too few results, or no page reader: the page is read as before. An
    unproven drop must never throw away a page that may be real."""
    provider, tried, bus, _ = _provider(monkeypatch, direct=("elsewhere.example",) * 2, typed=_KEPT)
    provider.run(_site_instruction())
    assert tried == ["direct URL"] and _SpyScraper.runs == 1

    provider, tried, _, _ = _provider(monkeypatch, direct=_UNRESTRICTED * 3, typed=_KEPT, reader=False)
    provider.run(_site_instruction())
    assert tried == ["direct URL"] and _SpyScraper.runs == 1


def test_the_typed_search_types_a_raw_query_verbatim_teeth():
    """TEETH: the typed route appended " in <location>" to the query the
    direct URL sends: a composed site-restricted query was changed, and a
    plain one read "... jobs in Chicago, IL in Chicago, IL"."""
    typed: list[str] = []

    class _Input:
        def get_size(self):
            return (200, 30)

        def send_keys(self, *_):
            pass

    class _Action:
        def click(self, _el):
            return True

        def type_text(self, _el, text):
            typed.append(text)

    browser = MagicMock()
    browser.find_elements.return_value = [_Input()]
    engine = MagicMock()
    engine.homepage_url = "https://www.google.com/"
    engine.search_bar_selectors = ["textarea[name=q]"]
    route = HumanSearchNavigation(browser, page_action=_Action())
    nav_sleep, nav.time.sleep = nav.time.sleep, (lambda s: None)
    try:
        route.navigate(engine, _site_instruction())
        route.navigate(engine, SearchInstruction(title="Software Engineer", location="Chicago, IL"))
    finally:
        nav.time.sleep = nav_sleep
    assert typed == [_SITE_QUERY, "Software Engineer jobs in Chicago, IL"]
