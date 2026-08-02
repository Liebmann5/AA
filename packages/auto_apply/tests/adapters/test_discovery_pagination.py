
"""Pins for bounded pagination and injected page collaborators (Stage 4).

This is the first stage that moves live discovery, so the guard comes first:
with the shipped default (``max_pages_per_query: 1``) discovery must produce
byte-for-byte what it produced before pagination existed — same jobs, same
order, and no extra page fetches.

It is also the stage that revives four strategies which could not have worked
before. ``KeywordPagination``, ``ArrowPagination`` and ``NumberedPagination``
all call ``self._interactor.click(...)`` — the method ``InteractionExecutor``
did not have until Stage 1. That dependency is why pagination waited.
"""
import pathlib

import pytest
from unittest.mock import MagicMock

PROVIDERS = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "src"
    / "auto_apply"
    / "adapters"
    / "secondary"
    / "discovery"
    / "providers"
)


def _strategy(*, max_pages=1, paginator=None, scroller=None, pages=None):
    """A SERP strategy whose mining step is replaced by a scripted page feed."""
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
        GenericSERPStrategy,
    )

    strategy = GenericSERPStrategy(
        browser=MagicMock(),
        search_prefs=None,
        source_tag="Test",
        max_results=100,
        scroller=scroller if scroller is not None else MagicMock(),
        paginator=paginator,
        max_pages=max_pages,
    )

    feed = list(pages or [{"a": "job-a"}])
    mined = {"calls": 0}

    def _mine(_scroller):
        page = feed[min(mined["calls"], len(feed) - 1)]
        mined["calls"] += 1
        return dict(page)

    strategy._scroll_and_mine = _mine
    strategy.mined = mined
    return strategy


# ─────────────────────────────────────────────────────────────────────────────
# THE REGRESSION GUARD — default config is today's behaviour
# ─────────────────────────────────────────────────────────────────────────────


def test_the_default_ceiling_mines_exactly_one_page():
    """No second harvest, and the paginator is never touched."""
    paginator = MagicMock()
    strategy = _strategy(max_pages=1, paginator=paginator)

    strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 1
    paginator.navigate_to_next_page.assert_not_called()


def test_the_default_ceiling_preserves_jobs_and_their_order():
    """Same jobs, same order — the dict the caller receives is unchanged."""
    page = {"u1": "job-1", "u2": "job-2", "u3": "job-3"}
    strategy = _strategy(max_pages=1, paginator=MagicMock(), pages=[page])

    result = strategy._mine_all_pages(strategy._scroller)

    assert result == page
    assert list(result.keys()) == ["u1", "u2", "u3"]


def test_the_shipped_default_is_one_page():
    """Config and code agree, so nobody has to trust the default by eye."""
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
        GenericSERPStrategy,
    )

    yaml_text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")

    assert "max_pages_per_query: 1" in yaml_text
    assert (
        GenericSERPStrategy(
            browser=MagicMock(), search_prefs=None, source_tag="T"
        )._max_pages
        == 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# ABOVE ONE, IT REALLY PAGINATES — AND STOPS AT THE CEILING
# ─────────────────────────────────────────────────────────────────────────────


def test_a_higher_ceiling_walks_pages_and_merges_them():
    paginator = MagicMock()
    paginator.navigate_to_next_page.return_value = True

    strategy = _strategy(
        max_pages=3,
        paginator=paginator,
        pages=[{"u1": "a"}, {"u2": "b"}, {"u3": "c"}],
    )

    result = strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 3
    assert result == {"u1": "a", "u2": "b", "u3": "c"}


def test_pagination_stops_exactly_at_the_ceiling():
    """A page feed that never ends is bounded by the ceiling, not by luck."""
    paginator = MagicMock()
    paginator.navigate_to_next_page.return_value = True

    strategy = _strategy(max_pages=2, paginator=paginator, pages=[{"u1": "a"}])
    strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 2
    assert paginator.navigate_to_next_page.call_count == 1


def test_pagination_stops_when_the_site_runs_out_of_pages():
    paginator = MagicMock()
    paginator.navigate_to_next_page.side_effect = [True, False]

    strategy = _strategy(max_pages=5, paginator=paginator)
    strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 2


def test_pagination_stops_once_the_result_cap_is_reached():
    """The result cap still wins — the runaway-scroll lesson, applied to pages."""
    paginator = MagicMock()
    paginator.navigate_to_next_page.return_value = True

    strategy = _strategy(max_pages=10, paginator=paginator, pages=[{"u1": "a"}])
    strategy.max_results = 1

    strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# THE REVIVED STRATEGIES CLICK THROUGH THE INTERACTION TOOL
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "strategy_name",
    ["KeywordPagination", "ArrowPagination", "NumberedPagination"],
)
def test_each_revived_strategy_clicks_through_the_interaction_tool(strategy_name):
    """Every one of these called a method that did not exist until Stage 1.

    ``InteractionExecutor`` had no ``click``, so each of these strategies would
    have raised AttributeError the moment it found a Next link. That is the
    dependency that ordered this stage after the interaction beachhead.
    """
    import auto_apply.application.services.navigation.pagination as pagination

    cls = getattr(pagination, strategy_name)
    interactor = MagicMock()
    browser = MagicMock()

    element = MagicMock()
    element.is_displayed.return_value = True
    element.is_enabled.return_value = True
    element.text = "Next"
    element.get_attribute.return_value = "Next page"
    browser.find_elements.return_value = [element]
    browser.find_element.return_value = element

    strategy = cls(browser, interactor)
    strategy.next_page()

    assert interactor.click.called, (
        f"{strategy_name} did not route its click through the interaction port"
    )


def test_the_pagination_handler_delegates_to_its_strategies():
    from auto_apply.application.services.navigation.pagination import (
        PaginationHandler,
    )

    handler = PaginationHandler(MagicMock(), MagicMock())
    assert handler.strategies, "PaginationHandler has no strategies"
    assert hasattr(handler, "navigate_to_next_page")


# ─────────────────────────────────────────────────────────────────────────────
# DEGRADATION
# ─────────────────────────────────────────────────────────────────────────────


def test_a_none_scroller_mines_once_without_raising():
    """Static mode / no driver: one screenful beats a crash."""
    strategy = _strategy(max_pages=1, scroller=None, paginator=None)
    strategy._scroller = None

    assert strategy._mine_all_pages(None) == {"a": "job-a"}


def test_a_none_paginator_never_advances_and_never_raises():
    strategy = _strategy(max_pages=5, paginator=None)

    strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 1


def test_a_raising_paginator_ends_the_walk_quietly():
    """A pagination fault ends the harvest; it must not kill the search."""
    paginator = MagicMock()
    paginator.navigate_to_next_page.side_effect = RuntimeError("no next link")

    strategy = _strategy(max_pages=4, paginator=paginator)
    result = strategy._mine_all_pages(strategy._scroller)

    assert strategy.mined["calls"] == 1
    assert result == {"a": "job-a"}


# ─────────────────────────────────────────────────────────────────────────────
# INJECTION — a provider without collaborators cannot happen on the live path
# ─────────────────────────────────────────────────────────────────────────────


def test_every_provider_accepts_and_stores_the_collaborators():
    """All three engines carry them, via the shared base."""
    from auto_apply.adapters.secondary.discovery.providers.bing import BingProvider
    from auto_apply.adapters.secondary.discovery.providers.google import GoogleProvider
    from auto_apply.adapters.secondary.discovery.providers.indeed import IndeedProvider

    scroller, paginator = MagicMock(), MagicMock()

    for factory in (
        lambda: GoogleProvider(
            browser=MagicMock(), scroller=scroller, paginator=paginator, max_pages=4
        ),
        lambda: BingProvider(
            browser=MagicMock(), scroller=scroller, paginator=paginator, max_pages=4
        ),
        lambda: IndeedProvider(
            browser=MagicMock(), scroller=scroller, paginator=paginator, max_pages=4
        ),
    ):
        provider = factory()
        assert provider._scroller is scroller
        assert provider._paginator is paginator
        assert provider._max_pages == 4


def test_every_live_scraper_construction_passes_the_collaborators():
    """Structural: no construction site may quietly omit them.

    A provider built without a scroller would silently stop scrolling — the
    regression pin (1) forbids — and the failure would look like "this site
    only has six jobs" rather than like a bug. Every site that builds a
    GenericSERPStrategy on the live path is checked here.
    """
    offenders = []
    sites = [PROVIDERS / name for name in ("google.py", "bing.py", "indeed.py")]
    sites.append(
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "infrastructure"
        / "composition_root.py"
    )

    for path in sites:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for chunk in text.split("GenericSERPStrategy(")[1:]:
            head = chunk[:600]
            if "scroller=" not in head or "paginator=" not in head:
                offenders.append(path.name)

    assert not offenders, (
        f"GenericSERPStrategy is constructed without page collaborators in: "
        f"{sorted(set(offenders))}"
    )


def test_the_serp_adapter_no_longer_imports_pagination_across_the_boundary():
    """The 16 -> 15 retirement, pinned so it cannot come back."""
    serp = (
        PROVIDERS.parent
        / "strategies"
        / "serp_strategy.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "application.services.navigation.pagination" not in serp
