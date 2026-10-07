"""Pins for the verified page-advance loop and its per-query wiring (call 3).

The regression guard stands: with the shipped default (``max_pages_per_query:
1``) discovery is byte-for-byte what it was before pagination existed. The
old Keyword/Arrow/Numbered strategies and the shared PaginationHandler are
retired — they matched English words, clicked the last match, verified
nothing, and one shared NumberedPagination leaked its page counter across
queries and providers.
"""
from __future__ import annotations

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.discovery.strategies import (
    serp_strategy as serp_strategy_module,
)
from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.page_advance import AdvanceOutcome
from auto_apply.domain.models.search_instruction import SearchInstruction
from auto_apply.domain.services.page_assessment import PageAssessment
from auto_apply.domain.types import PageType

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"


class _FakeAdvancer:
    """A scripted advancer: replays outcomes, then reports no-next."""

    def __init__(self, outcomes=()):
        self._outcomes = list(outcomes)
        self.calls = 0

    def advance(self):
        self.calls += 1
        if self._outcomes:
            return self._outcomes.pop(0)
        return AdvanceOutcome(False, stop_reason="no-next-control")


def _advance(method="numbered"):
    return AdvanceOutcome(True, method=method, verified=True)


def _verdict(kind):
    return PageAssessment(kind=kind, challenge="clear", signals=("stubbed",),
                          detail="stub", confidence=1.0)


def _strategy(*, max_pages=1, advancer=None, pages=None, browser=None, observer=None):
    browser = browser or MagicMock()
    browser.page_source = ""
    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="Test",
        max_results=100,
        scroller=MagicMock(),
        advancer=advancer,
        max_pages=max_pages,
        research_observer=observer,
    )
    strategy.interruption_handler = MagicMock()
    strategy._page_block_type = lambda: None  # verdict stubbed; the block
    # test restores the real method and stubs the module assess_page instead
    feed = list(pages or [{"a": "job-a"}])
    mined = {"calls": 0}

    def _mine(_scroller, **_kwargs):
        page = feed[min(mined["calls"], len(feed) - 1)]
        mined["calls"] += 1
        return dict(page)

    strategy._scroll_and_mine = _mine
    strategy.mined = mined
    return strategy


# ─────────────────────────────────────────────────────────────────────────────
# THE REGRESSION GUARD — default config is today's behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_default_ceiling_mines_once_and_never_touches_the_advancer():
    advancer = _FakeAdvancer([_advance()])
    strategy = _strategy(max_pages=1, advancer=advancer)
    strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 1
    assert advancer.calls == 0


def test_default_ceiling_preserves_jobs_and_their_order():
    page = {"u1": "job-1", "u2": "job-2", "u3": "job-3"}
    strategy = _strategy(max_pages=1, advancer=_FakeAdvancer(), pages=[page])
    result = strategy._mine_all_pages(strategy._scroller)
    assert result == page
    assert list(result.keys()) == ["u1", "u2", "u3"]


def test_the_shipped_default_is_one_page():
    yaml_text = (SRC / "resources" / "config" / "runtime_defaults.yaml").read_text(
        encoding="utf-8"
    )
    assert "max_pages_per_query: 1" in yaml_text
    assert (
        GenericSERPStrategy(browser=MagicMock(), search_prefs=None, source_tag="T")._max_pages
        == 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# THE LOOP ADVANCES, VERIFIES AND STOPS
# ─────────────────────────────────────────────────────────────────────────────


def test_advances_merges_and_stops_at_the_ceiling():
    advancer = _FakeAdvancer([_advance(), _advance(), _advance()])
    strategy = _strategy(
        max_pages=3, advancer=advancer, pages=[{"u1": "a"}, {"u2": "b"}, {"u3": "c"}]
    )
    result = strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 3
    assert result == {"u1": "a", "u2": "b", "u3": "c"}
    assert advancer.calls == 2


def test_an_unverified_no_advance_stops_and_never_re_mines():
    """TEETH: the old loop logged 'advanced to page N' and re-mined whatever
    was on screen — the same page twice, wearing a new number."""
    advancer = _FakeAdvancer([AdvanceOutcome(False, stop_reason="no-change")])
    strategy = _strategy(max_pages=5, advancer=advancer)
    result = strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 1
    assert result == {"a": "job-a"}


def test_stops_when_the_site_runs_out_of_pages():
    advancer = _FakeAdvancer([_advance()])  # second advance -> no-next
    strategy = _strategy(max_pages=5, advancer=advancer, pages=[{"u1": "a"}, {"u2": "b"}])
    result = strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 2
    assert result == {"u1": "a", "u2": "b"}


def test_the_result_cap_still_wins():
    advancer = _FakeAdvancer([_advance(), _advance()])
    strategy = _strategy(max_pages=10, advancer=advancer, pages=[{"u1": "a"}])
    strategy.max_results = 1
    strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 1
    assert advancer.calls == 0


def test_a_raising_advancer_ends_the_walk_quietly():
    advancer = MagicMock()
    advancer.advance.side_effect = RuntimeError("boom")
    strategy = _strategy(max_pages=4, advancer=advancer)
    result = strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 1
    assert result == {"a": "job-a"}


# ─────────────────────────────────────────────────────────────────────────────
# EVERY NEW PAGE IS A NEW PAGE
# ─────────────────────────────────────────────────────────────────────────────


def test_the_block_verdict_reruns_on_every_page(monkeypatch):
    """TEETH: a CAPTCHA on page 2 used to be mined as an empty harvest."""
    verdicts = [_verdict(PageType.CAPTCHA_BLOCK)]
    monkeypatch.setattr(
        serp_strategy_module, "assess_page", lambda **kw: verdicts.pop(0)
    )
    monkeypatch.setattr(
        serp_strategy_module, "browser_page_snapshot", lambda b: ("u", "t", "")
    )
    observer = MagicMock()
    observer.is_enabled = True
    advancer = _FakeAdvancer([_advance(), _advance()])
    strategy = _strategy(max_pages=3, advancer=advancer, observer=observer)
    del strategy._page_block_type  # restore the real method over the stub
    strategy._mine_all_pages(strategy._scroller)
    assert strategy.mined["calls"] == 1  # page 2 was never mined
    observation = observer.observe_discovery.call_args_list[0].args[0]
    assert observation.blocked is True
    assert observation.page_state == "captcha_block"


def test_overlays_are_dismissed_once_per_page():
    advancer = _FakeAdvancer([_advance()])
    strategy = _strategy(max_pages=2, advancer=advancer, pages=[{"u1": "a"}, {"u2": "b"}])
    strategy._mine_all_pages(strategy._scroller)
    assert strategy.interruption_handler.handle_interruptions.call_count == 1


def test_run_dismisses_overlays_on_the_first_page(monkeypatch):
    """BEHAVIOUR CHANGE, disclosed: run() previously never dismissed popups."""
    monkeypatch.setattr(
        serp_strategy_module, "assess_page", lambda **kw: _verdict(PageType.SERP)
    )
    strategy = _strategy(max_pages=1)
    strategy.run()
    strategy.interruption_handler.handle_interruptions.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE
# ─────────────────────────────────────────────────────────────────────────────


def test_a_query_summary_records_methods_pages_and_the_stop_reason():
    observer = MagicMock()
    observer.is_enabled = True
    advancer = _FakeAdvancer([_advance("numbered")])  # then no-next
    strategy = _strategy(
        max_pages=5, advancer=advancer, observer=observer,
        pages=[{"u1": "a"}, {"u2": "b"}],
    )
    strategy._mine_all_pages(strategy._scroller)
    summaries = [c.args[0] for c in observer.observe_discovery.call_args_list]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.page_index == -1
    assert summary.page_count == 2
    assert summary.advance_method == "numbered"
    assert summary.stop_reason == "no-next-control"
    assert summary.card_count == 2


def test_no_summary_row_at_the_shipped_default():
    observer = MagicMock()
    observer.is_enabled = True
    strategy = _strategy(max_pages=1, advancer=_FakeAdvancer(), observer=observer)
    strategy._mine_all_pages(strategy._scroller)
    observer.observe_discovery.assert_not_called()


def test_finalize_receives_the_page_index_and_method(monkeypatch):
    monkeypatch.setattr(
        serp_strategy_module, "assess_page", lambda **kw: _verdict(PageType.SERP)
    )
    strategy = GenericSERPStrategy(
        browser=MagicMock(), search_prefs=None, source_tag="T", max_results=100,
        scroller=MagicMock(), advancer=_FakeAdvancer([_advance("rel-next")]),
        max_pages=2,
    )
    strategy.interruption_handler = MagicMock()
    strategy._page_block_type = lambda: None
    miner = MagicMock()
    miner.mine_jobs.return_value = []
    miner.finalize_harvest.return_value = []
    strategy.miner = miner
    strategy._mine_all_pages(strategy._scroller)
    calls = miner.finalize_harvest.call_args_list
    assert calls[0].kwargs["page_index"] == 0
    assert calls[1].kwargs["page_index"] == 1
    assert calls[1].kwargs["advance_method"] == "rel-next"


def test_jobs_carry_their_page_index_and_rank():
    strategy = GenericSERPStrategy(
        browser=MagicMock(), search_prefs=None, source_tag="T", max_results=100,
        scroller=MagicMock(), advancer=_FakeAdvancer([_advance()]), max_pages=2,
    )
    strategy.interruption_handler = MagicMock()
    strategy._page_block_type = lambda: None
    j1 = Job(title="A", company="C", url="https://x/1", source="T")
    j2 = Job(title="B", company="C", url="https://x/2", source="T")
    j3 = Job(title="D", company="C", url="https://x/3", source="T")
    miner = MagicMock()
    miner.mine_jobs.side_effect = [[j1, j2]] * 4 + [[j3]] * 4
    miner.finalize_harvest.return_value = []
    strategy.miner = miner
    result = strategy._mine_all_pages(strategy._scroller)
    assert result[j1.url].metadata["page_index"] == 0
    assert result[j1.url].metadata["rank"] == 0
    assert result[j2.url].metadata["rank"] == 1
    assert result[j3.url].metadata["page_index"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# WIRING — a fresh advancer per query, never a shared one
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_name,class_name",
    [("google", "GoogleProvider"), ("bing", "BingProvider"), ("indeed", "IndeedProvider")],
)
def test_provider_requests_a_fresh_advancer_once_per_run(module_name, class_name, monkeypatch):
    module = importlib.import_module(
        f"auto_apply.adapters.secondary.discovery.providers.{module_name}"
    )
    factory = MagicMock(return_value="SENTINEL")
    scraper_instance = MagicMock()
    scraper_instance.execute.return_value = []
    scraper_instance.run.return_value = []
    scraper_cls = MagicMock(return_value=scraper_instance)
    monkeypatch.setattr(module, "GenericSERPStrategy", scraper_cls)
    provider = getattr(module, class_name)(
        browser=MagicMock(), advancer_factory=factory
    )
    provider.navigator = MagicMock()
    provider.navigator.navigate_with_fallback.return_value = True
    provider.run(SearchInstruction(title="t", location="l", workplace_type="remote"))
    factory.assert_called_once_with()
    assert scraper_cls.call_args.kwargs["advancer"] == "SENTINEL"


def test_live_constructions_pass_an_advancer_and_nothing_builds_the_handler():
    """Structural: the retired handler cannot come back, and every live
    GenericSERPStrategy construction receives advancer=."""
    offenders = []
    for path in (
        SRC / "adapters" / "secondary" / "discovery" / "providers" / "google.py",
        SRC / "adapters" / "secondary" / "discovery" / "providers" / "bing.py",
        SRC / "adapters" / "secondary" / "discovery" / "providers" / "indeed.py",
        SRC / "infrastructure" / "composition_root.py",
    ):
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "PaginationHandler" not in text, path.name
        for chunk in text.split("GenericSERPStrategy(")[1:]:
            if "advancer=" not in chunk[:600]:
                offenders.append(path.name)
    assert not offenders, sorted(set(offenders))


def test_the_retired_strategies_are_gone_and_the_feed_scroller_stays():
    source = (SRC / "adapters" / "secondary" / "navigation" / "pagination.py").read_text(
        encoding="utf-8"
    )
    for name in ("KeywordPagination", "ArrowPagination",
                 "NumberedPagination", "PaginationHandler"):
        assert f"class {name}" not in source
    assert "class InfiniteScrollStrategy" in source


# ─────────────────────────────────────────────────────────────────────────────
# JSON-LD — ruled: a JSON-LD page MAY still advance
# ─────────────────────────────────────────────────────────────────────────────


def _jsonld_page(title, url):
    return (
        '<html><script type="application/ld+json">'
        '{"@context":"http://schema.org","@type":"JobPosting","title":"' + title
        + '","hiringOrganization":{"name":"Acme"},"url":"' + url + '"}'
        "</script></html>"
    )


class _JsonLdBrowser:
    """page_source serves one JSON-LD document per extraction call."""

    def __init__(self, sources):
        self._sources = list(sources)
        self._reads = 0
        self.title = "SERP"
        self.current_url = "https://serp.example/q"

    @property
    def page_source(self):
        value = self._sources[min(self._reads, len(self._sources) - 1)]
        self._reads += 1
        return value


def test_a_json_ld_page_advances_through_the_same_ladder():
    pytest.importorskip("bs4")
    browser = _JsonLdBrowser(
        [_jsonld_page("Job One", "https://x/1"), _jsonld_page("Job Two", "https://x/2")]
    )
    advancer = _FakeAdvancer([_advance("url-template")])
    strategy = GenericSERPStrategy(
        browser=browser, search_prefs=None, source_tag="T", max_results=100,
        advancer=advancer, max_pages=2,
    )
    strategy._page_block_type = lambda: None
    jobs = strategy.execute()
    assert [j.title for j in jobs] == ["Job One", "Job Two"]
    assert advancer.calls == 1


def test_a_json_ld_page_never_advances_at_the_default():
    pytest.importorskip("bs4")
    browser = _JsonLdBrowser(
        [_jsonld_page("Job One", "https://x/1"), _jsonld_page("Job Two", "https://x/2")]
    )
    advancer = _FakeAdvancer([_advance()])
    strategy = GenericSERPStrategy(
        browser=browser, search_prefs=None, source_tag="T", max_results=100,
        advancer=advancer, max_pages=1,
    )
    strategy._page_block_type = lambda: None
    jobs = strategy.execute()
    assert [j.title for j in jobs] == ["Job One"]
    assert advancer.calls == 0
