
"""Multi-scroll equivalence: the native path and the tool path harvest identically.

Stage 4 is where discovery starts scrolling through
``PageActionService.scroll_to_bottom`` instead of the raw JS that lived inside
``InfiniteScrollStrategy``. Everything pinned so far tests those two pieces
*separately*: Stage 3 proved the un-injected path is byte-for-byte unchanged and
that delegation passes the tool's answer through; Stage 4's regression guard
proves the page loop, but it stubs ``_scroll_and_mine`` outright, so it never
scrolls at all.

That leaves the actual swap unproven under real scrolling. This module closes
it: the REAL harvest loop is run twice over the same scripted page — once with
the native scroller and once with the tool-backed one — and the two harvests
must agree on the jobs, their order, and how many times the page was scrolled.
"""
from types import SimpleNamespace

from unittest.mock import MagicMock, patch


def _scripted_browser(growth_steps: int):
    """A page that grows for `growth_steps` scrolls, then stops.

    Both scroll paths issue the same JS, so one script serves both and any
    divergence in how they read it shows up as a behavioural difference.
    """
    state = {"scrolls": 0}

    def _exec(script, *args):
        if "scrollTo" in script:
            state["scrolls"] += 1
            return None
        if "scrollHeight" in script:
            return 1000 * (1 + min(state["scrolls"], growth_steps))
        return None

    browser = MagicMock()
    browser.execute_script.side_effect = _exec
    browser.state = state
    return browser


def _job(n: int):
    return SimpleNamespace(url=f"https://example.com/job/{n}", title=f"Job {n}", company="Acme")


def _batches():
    """Each harvest sees the previous jobs plus two new ones, then repeats.

    Overlap exercises dedup; the tail repeat exercises the dry-scroll guard.
    """
    return [
        [_job(1), _job(2)],
        [_job(1), _job(2), _job(3), _job(4)],
        [_job(1), _job(2), _job(3), _job(4), _job(5), _job(6)],
        [_job(1), _job(2), _job(3), _job(4), _job(5), _job(6)],
        [_job(1), _job(2), _job(3), _job(4), _job(5), _job(6)],
        [_job(1), _job(2), _job(3), _job(4), _job(5), _job(6)],
    ]


def _strategy_over(browser, scroller):
    """A real GenericSERPStrategy with only its miner scripted."""
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
        GenericSERPStrategy,
    )

    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="Equivalence",
        max_results=100,
        dry_scroll_limit=3,
        inter_scroll_delay_s=0.0,
        scroller=scroller,
    )

    feed = _batches()
    calls = {"n": 0}

    def _mine_jobs(source_name=None):
        batch = feed[min(calls["n"], len(feed) - 1)]
        calls["n"] += 1
        return list(batch)

    strategy.miner = SimpleNamespace(mine_jobs=_mine_jobs)
    return strategy


def _native_scroller(browser):
    """The pre-Stage-3 path: raw JS and a plain sleep, no tool."""
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    return InfiniteScrollStrategy(browser)


def _tool_scroller(browser):
    """The live path: InfiniteScrollStrategy delegating to PageActionService."""
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )
    from auto_apply.application.services.page_action.service import PageActionService

    registry = MagicMock()
    registry.get_all_effective_config.return_value = {
        "enable_human_timing": False,
        "infinite_scroll_settle_s": 0.0,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.0,
        "settle_max_s": 0.0,
        "min_action_delay_ms": 0,
        "low_resource_mode": False,
    }
    tool = PageActionService(browser=browser, registry=registry)
    return InfiniteScrollStrategy(browser, scroller=tool, settle_s=0.0)


def _harvest(scroller_factory, growth_steps=4):
    browser = _scripted_browser(growth_steps)
    strategy = _strategy_over(browser, scroller_factory(browser))
    with patch("auto_apply.adapters.secondary.navigation.pagination.time.sleep"), patch(
        "auto_apply.adapters.secondary.discovery.strategies.serp_strategy.time.sleep"
    ):
        harvested = strategy._scroll_and_mine(strategy._scroller)
    return harvested, browser.state["scrolls"]


# ─────────────────────────────────────────────────────────────────────────────


def test_both_scroll_paths_harvest_the_same_jobs_in_the_same_order():
    """The swap is behaviour-identical across a multi-scroll harvest."""
    native, native_scrolls = _harvest(_native_scroller)
    tooled, tool_scrolls = _harvest(_tool_scroller)

    assert list(native.keys()) == list(tooled.keys()), (
        "the tool path harvested a different job order than the native path"
    )
    assert native.keys() == tooled.keys()
    assert native_scrolls == tool_scrolls, (
        f"native path scrolled {native_scrolls} times, tool path {tool_scrolls}"
    )


def test_the_harvest_really_scrolled_more_than_once():
    """Guards the guard: a single-page fixture would prove nothing here."""
    _, scrolls = _harvest(_tool_scroller)
    assert scrolls >= 3, f"fixture only scrolled {scrolls} times"


def test_both_paths_stop_on_the_same_bound():
    """Dry-scroll exhaustion is reached identically by either scroller."""
    native, _ = _harvest(_native_scroller)
    tooled, _ = _harvest(_tool_scroller)

    assert len(native) == len(tooled) == 6


def test_equivalence_holds_when_the_feed_ends_early():
    """A page that stops growing ends both harvests the same way."""
    native, native_scrolls = _harvest(_native_scroller, growth_steps=1)
    tooled, tool_scrolls = _harvest(_tool_scroller, growth_steps=1)

    assert list(native.keys()) == list(tooled.keys())
    assert native_scrolls == tool_scrolls
