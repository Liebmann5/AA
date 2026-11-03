"""Pins for three discovery defects of the owner's live run of 2026-11-02.

Environment ``owner``: default search, providers Bing, Google and Indeed,
query "Backend Engineer", Chicago, IL.

* ``https://www.bing.com/jobs?q=...`` redirected to Bing's home page
  (``https://www.bing.com/?form=REDIRERR``) and the navigator logged it as
  "successful and validated". Observed again in environment ``cloud`` on
  2026-11-03 (404, then the same landing).
* The results reader then read the home page's 20 news cards as records.
* The run summary said "Jobs discovered: 40" for 20 unique jobs.

Each pin marked ``_teeth`` fails on the code before the fix. The new helpers
are imported inside the pins that use them, so the others fail on their own
assertions there rather than on a collection error.
"""

from __future__ import annotations

from types import SimpleNamespace

from auto_apply.adapters.secondary.discovery.strategies import (
    serp_strategy as serp_strategy_module,
)
from auto_apply.adapters.secondary.discovery.strategies.navigators import (
    DirectURLNavigation,
    ResilientNavigator,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.domain.services.page_assessment import assess_page
from auto_apply.domain.types import PageType

_REQUESTED = "https://www.bing.com/jobs?q=Backend+Engineer+Chicago%2C+IL"
_LANDED = "https://www.bing.com/?form=REDIRERR"

# The shape of Bing's home page: a search form and a carousel of news cards
# in list items. Synthetic; no page content is copied.
_BING_HOME = (
    "<html><head><title>Search - Microsoft Bing</title></head><body>"
    "<form action='/search' role='search'><input name='q' type='search'></form>"
    "<ul class='carousel'>"
    + "".join(f"<li><a href='/news/{i}'><h3>Story {i}</h3></a></li>" for i in range(20))
    + "</ul></body></html>"
)


# ── (a) a landing on a different surface is a failed navigation ─────────────


def check_landing(requested: str, landed: str):
    from auto_apply.domain.services.navigation_landing import check_landing as check

    return check(requested, landed)


def unique_new_count(payload, seen):
    from auto_apply.application.agent.event_bus import unique_new_count as count

    return count(payload, seen)


def test_bing_error_redirect_is_not_the_requested_surface_teeth() -> None:
    landing = check_landing(_REQUESTED, _LANDED)
    assert landing.on_surface is False
    assert landing.reason == "error-redirect"
    assert landing.landed == _LANDED


def test_landing_rules() -> None:
    assert check_landing(_REQUESTED, _REQUESTED).on_surface
    assert check_landing("https://www.bing.com/jobs?q=a", "https://bing.com/jobs/?q=a").on_surface
    assert check_landing("https://x.com/jobs?q=a", "https://x.com/").reason == "home-page"
    assert check_landing("https://x.com/jobs?q=a", "https://x.com/news").reason == "different-path"
    assert check_landing("https://x.com/jobs", "https://y.com/jobs").reason == "different-site"
    assert check_landing("https://x.com/jobs", "about:blank").reason == "no-page"
    assert check_landing("https://a.example.co.uk/jobs", "https://b.example.co.uk/jobs").on_surface


class _RedirectingBrowser:
    def __init__(self, landed: str) -> None:
        self._landed = landed
        self.current_url = "about:blank"
        self.gets: list[str] = []

    def get(self, url: str) -> None:
        self.gets.append(url)
        self.current_url = self._landed if url != "about:blank" else url


class _Engine:
    homepage_url = "https://www.bing.com"
    search_bar_selectors: list[str] = []
    engine_name = "bing"

    def build_search_url(self, instruction) -> str:
        return _REQUESTED


def test_direct_navigation_that_lands_elsewhere_fails_and_records_landing_teeth() -> None:
    browser = _RedirectingBrowser(_LANDED)
    strategy = DirectURLNavigation(browser)
    assert strategy.navigate(_Engine(), SimpleNamespace()) is False
    assert strategy.last_landing is not None
    assert strategy.last_landing.landed == _LANDED


def test_resilient_navigator_never_validates_a_redirected_landing_teeth(monkeypatch) -> None:
    import auto_apply.adapters.secondary.discovery.strategies.navigators as nav

    monkeypatch.setattr(nav.time, "sleep", lambda s: None)
    browser = _RedirectingBrowser(_LANDED)
    navigator = ResilientNavigator(browser, [DirectURLNavigation(browser)])
    assert navigator.navigate_with_fallback(_Engine(), SimpleNamespace(), lambda: True) is False
    assert [landing.reason for landing in navigator.landings] == ["error-redirect"]


def test_direct_navigation_on_the_requested_surface_succeeds() -> None:
    browser = _RedirectingBrowser(_REQUESTED)
    assert DirectURLNavigation(browser).navigate(_Engine(), SimpleNamespace()) is True


# ── (b) the verdict knows a home page, and discovery reads no records on it ──


def test_verdict_calls_the_bing_home_page_a_home_page_teeth() -> None:
    verdict = assess_page(url=_LANDED, title="Search - Microsoft Bing", html=_BING_HOME)
    assert verdict.kind is PageType.HOME_PAGE
    assert "family:home-page" in verdict.signals


def test_verdict_calls_a_results_list_a_results_list() -> None:
    html = _BING_HOME.replace("carousel", "results")
    verdict = assess_page(
        url="https://www.bing.com/search?q=backend+engineer", title="x", html=html
    )
    assert verdict.kind is PageType.SERP


def test_verdict_keeps_unknown_when_the_family_has_no_margin() -> None:
    verdict = assess_page(url="https://acme.example/about", title="x", html="<p>About</p>")
    assert verdict.kind is PageType.UNKNOWN


class _Browser:
    title = "Search - Microsoft Bing"
    current_url = _LANDED
    page_source = _BING_HOME

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        return None

    def switch_to_default_content(self):
        return None


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


def _strategy() -> tuple[GenericSERPStrategy, _CountingExtractor, _Degradation]:
    fast, degradation = _CountingExtractor(), _Degradation()
    strategy = GenericSERPStrategy(
        browser=_Browser(),
        search_prefs=None,
        source_tag="Bing",
        max_results=20,
        scroller=None,
        fast_extractor=fast,
        degradation_detector=degradation,
    )
    return strategy, fast, degradation


def test_discovery_reads_no_records_on_a_home_page_teeth() -> None:
    for entry in ("execute", "run"):
        strategy, fast, degradation = _strategy()
        assert getattr(strategy, entry)() == []
        assert fast.mine_calls == 0, entry
        # Not a block: the engine is not benched for the session.
        assert degradation.blocked == []
        assert strategy.last_page_kind is PageType.HOME_PAGE


def test_home_page_gate_uses_the_one_verdict(monkeypatch) -> None:
    calls: list[str] = []

    def spy(**kwargs):
        calls.append(kwargs["url"])
        return assess_page(**kwargs)

    monkeypatch.setattr(serp_strategy_module, "assess_page", spy)
    strategy, _fast, _deg = _strategy()
    strategy.execute()
    assert calls == [_LANDED]


# ── (c) "Jobs discovered" counts unique jobs ───────────────────────────────


def test_jobs_discovered_counts_unique_identities_across_passes_teeth() -> None:
    seen: set[str] = set()
    keys = [f"https://jobs.example/{i}" for i in range(20)]
    first = unique_new_count({"count": 20, "keys": keys}, seen)
    second = unique_new_count({"count": 20, "keys": keys}, seen)
    assert (first, second, first + second) == (20, 0, 20)


def test_orchestrator_counter_counts_unique_jobs_teeth() -> None:
    from auto_apply.application.agent.orchestrator import AgentOrchestrator

    counted: list[int] = []
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._discovered_keys = set()
    orchestrator.context = SimpleNamespace(
        update_stats=lambda category, count: counted.append(count)
    )
    orchestrator._session_report = SimpleNamespace(raw_results_found=0)
    payload = {"count": 20, "keys": [f"k{i}" for i in range(20)], "source": "discovery"}
    orchestrator._on_jobs_discovered(payload)
    orchestrator._on_jobs_discovered(payload)
    assert counted == [20]
    assert orchestrator._session_report.raw_results_found == 20


def test_payload_without_keys_keeps_counting_by_count() -> None:
    assert unique_new_count({"count": 3}, set()) == 3
    assert unique_new_count(None, set()) == 0
