"""The scroll-and-mine harvest is a single loop with three stop conditions.

Regression guard for the runaway-scroll bug: Google/Bing used a naive loop with
no "stop when nothing new appears" guard, so on an infinite-scroll page that
never reports a bottom it looped its full budget re-mining the same items
(minutes wasted). Both provider paths now funnel through
GenericSERPStrategy._scroll_and_mine, which stops on: (1) the result cap,
(2) dry_scroll_limit consecutive scrolls with no new jobs, (3) the scroller
reporting end-of-feed. These pins prove each stop condition.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)


def _job(url, title="T", company="C"):
    return SimpleNamespace(url=url, title=title, company=company)


def _strategy(dry_scroll_limit=2, max_results=100):
    strat = GenericSERPStrategy(
        browser=MagicMock(),
        search_prefs=None,
        source_tag="Test",
        max_results=max_results,
        dry_scroll_limit=dry_scroll_limit,
        inter_scroll_delay_s=0.0,  # keep the test instant
    )
    strat.miner = MagicMock()
    return strat


def _scroller(next_returns):
    sc = MagicMock()
    sc.next_page.side_effect = list(next_returns)
    return sc


def test_stops_after_dry_scroll_limit():
    """Same jobs every scroll => stop after dry_scroll_limit dry passes."""
    strat = _strategy(dry_scroll_limit=2)
    strat.miner.mine_jobs.return_value = [_job("a"), _job("b"), _job("c")]
    scroller = _scroller([True] * 10)  # page never reports a bottom
    result = strat._scroll_and_mine(scroller)
    assert len(result) == 3
    # loop1 (3 new) -> loop2 (0 new, dry=1) -> loop3 (0 new, dry=2 => stop)
    assert strat.miner.mine_jobs.call_count == 3
    assert scroller.next_page.call_count == 2


def test_stops_at_result_cap():
    """New jobs each scroll => stop once the cap is reached."""
    strat = _strategy(dry_scroll_limit=99, max_results=5)
    batches = [[_job(f"u{i}") for i in range(0, 3)],
               [_job(f"u{i}") for i in range(3, 6)],
               [_job(f"u{i}") for i in range(6, 9)]]
    strat.miner.mine_jobs.side_effect = batches
    scroller = _scroller([True] * 10)
    result = strat._scroll_and_mine(scroller)
    assert len(result) >= 5
    # loop1 total 3 (<5), loop2 total 6 (>=5 => stop) — never reaches loop3
    assert strat.miner.mine_jobs.call_count == 2


def test_stops_when_scroller_reports_end():
    strat = _strategy(dry_scroll_limit=99)
    strat.miner.mine_jobs.return_value = [_job("a"), _job("b")]
    scroller = _scroller([False])  # bottom immediately after first harvest
    result = strat._scroll_and_mine(scroller)
    assert len(result) == 2
    assert strat.miner.mine_jobs.call_count == 1


def test_dedup_by_url_then_title_company():
    strat = _strategy(dry_scroll_limit=1)
    # duplicate url collapses; urlless jobs dedup by title|company
    strat.miner.mine_jobs.return_value = [
        _job("dup"), _job("dup"), _job(None, "X", "Co"), _job(None, "X", "Co"),
    ]
    scroller = _scroller([True, True])
    result = strat._scroll_and_mine(scroller)
    assert len(result) == 2  # one "dup", one "X|Co"
