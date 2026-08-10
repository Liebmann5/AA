
"""Pins for the shared scroll primitive (Stage 3).

Scrolling had six implementations. This stage introduces the one that the
others will collapse onto: ``PageActionService.scroll_to_bottom`` — deliberately
a SINGLE step, because the loop belongs to the caller.

That split is load-bearing. ``GenericSERPStrategy._scroll_and_mine`` owns the
loop, and that loop carries the dry-scroll guard and result cap added after a
live run spent four minutes scrolling Google re-mining the same six jobs.
Folding the loop into the tool would put that fix at risk in the very stage
meant to prove scroll behaviour is unchanged.

The two pins that matter most here:

    * the **regression guard** — with nothing injected, the scroll path is
      byte-for-byte what it was, including the hardcoded-2.0 to configured-2.0
      swap being a no-op at the default;
    * the **degradation pin** — an unusable browser yields False, never an
      exception, because a scroll probe must not be able to abort discovery.
"""
import importlib
import pathlib

import pytest
from unittest.mock import MagicMock, patch

# Relocated 2026-08-07: pagination.py drives a browser through
# BrowserInterface/InteractionPort, so it is a secondary adapter, not an
# application service. Derived from the module itself rather than hardcoded,
# so the next move does not silently turn this pin into a FileNotFoundError.
def _module_source(dotted: str) -> pathlib.Path:
    """Locate a module's source file, or fail with a readable reason.

    ``module.__file__`` is ``str | None`` — None for namespace packages, which
    is exactly what an emptied-out package directory leaves behind after a
    move. Silently passing None into Path() would raise TypeError from inside
    pathlib and tell the next reader nothing.
    """
    path = importlib.import_module(dotted).__file__
    if path is None:
        raise AssertionError(
            f"{dotted} has no source file — it resolved to a namespace "
            f"package, which usually means the module was moved or deleted "
            f"and an empty directory was left behind."
        )
    return pathlib.Path(path)


PAGINATION_SRC = _module_source(
    "auto_apply.adapters.secondary.navigation.pagination"
)


def _heights(*values):
    """A browser whose scrollHeight follows a script across execute_script calls."""
    browser = MagicMock()
    seq = list(values)
    calls = []

    def _exec(script, *args):
        calls.append(script)
        if "scrollHeight" in script and script.strip().startswith("return"):
            return seq.pop(0)
        return None

    browser.execute_script.side_effect = _exec
    browser.recorded = calls
    return browser


def _tool(browser, settle=0.0):
    from auto_apply.application.services.page_action.service import PageActionService

    registry = MagicMock()
    registry.get_all_effective_config.return_value = {
        "enable_human_timing": False,
        "infinite_scroll_settle_s": settle,
        "macro_pause_min_s": 0.0,
        "macro_pause_max_s": 0.0,
        "settle_min_s": 0.0,
        "settle_max_s": 0.0,
        "min_action_delay_ms": 0,
        "low_resource_mode": False,
    }
    return PageActionService(browser=browser, registry=registry)


# ─────────────────────────────────────────────────────────────────────────────
# THE REGRESSION GUARD — default config reproduces today's behaviour exactly
# ─────────────────────────────────────────────────────────────────────────────


def test_default_config_reproduces_the_previous_scroll_behaviour_exactly():
    """No scroller injected: same JS, same order, same 2.0s wait, same result.

    This is the pin that lets the hardcoded 2.0 become a config value without
    anyone having to trust that the default matches. If the default ever drifts
    from 2.0, or the JS sequence changes, this fails.
    """
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    browser = _heights(1000, 2000)
    strategy = InfiniteScrollStrategy(browser)

    with patch(
        "auto_apply.adapters.secondary.navigation.pagination.time.sleep"
    ) as slept:
        assert strategy.next_page() is True

    slept.assert_called_once_with(2.0)
    assert browser.recorded == [
        "return document.body.scrollHeight",
        "window.scrollTo(0, document.body.scrollHeight);",
        "return document.body.scrollHeight",
    ]


def test_the_settle_default_is_the_old_literal():
    """The extracted magic number's default IS the number it replaced."""
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    assert InfiniteScrollStrategy(MagicMock())._settle_s == 2.0


def test_no_hardcoded_scroll_wait_survives_in_the_pagination_module():
    source = PAGINATION_SRC.read_text(encoding="utf-8", errors="ignore")
    assert "time.sleep(2.0)" not in source
    assert "self._settle_s" in source


def test_reaching_the_bottom_still_reports_no_growth():
    """Unchanged semantics: same height means the feed has ended."""
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    with patch("auto_apply.adapters.secondary.navigation.pagination.time.sleep"):
        assert InfiniteScrollStrategy(_heights(4200, 4200)).next_page() is False


# ─────────────────────────────────────────────────────────────────────────────
# THE DEGRADATION PIN
# ─────────────────────────────────────────────────────────────────────────────


def test_scroll_to_bottom_returns_false_on_an_unusable_browser():
    """A scroll probe must never be able to abort discovery.

    Discovery calls this inside a mining loop. An exception here would kill a
    whole search rather than ending one feed.
    """
    browser = MagicMock()
    browser.execute_script.side_effect = RuntimeError("driver gone")

    assert _tool(browser).scroll_to_bottom() is False


def test_scroll_to_bottom_returns_false_when_the_page_shrinks_or_holds():
    for before, after in ((5000, 5000), (5000, 4000)):
        assert _tool(_heights(before, after)).scroll_to_bottom() is False


# ─────────────────────────────────────────────────────────────────────────────
# The primitive itself
# ─────────────────────────────────────────────────────────────────────────────


def test_scroll_to_bottom_reports_growth():
    assert _tool(_heights(1000, 3000)).scroll_to_bottom() is True


def test_scroll_to_bottom_is_a_single_step_not_a_loop():
    """The caller owns the loop — that is where the dry-scroll guard lives."""
    browser = _heights(1000, 2000)
    _tool(browser).scroll_to_bottom()

    scrolls = [s for s in browser.recorded if "window.scrollTo" in s]
    assert len(scrolls) == 1, "the primitive scrolled more than once"


def test_the_settle_comes_from_config_not_a_literal():
    browser = _heights(1000, 2000)
    with patch(
        "auto_apply.application.services.page_action.service.time.sleep"
    ) as slept:
        _tool(browser, settle=0.75).scroll_to_bottom()

    assert 0.75 in [call.args[0] for call in slept.call_args_list]


def test_the_config_key_is_registered_and_matches_the_shipped_default():
    from auto_apply.infrastructure.registry import CapabilitiesRegistry

    yaml_text = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "resources"
        / "config"
        / "runtime_defaults.yaml"
    ).read_text(encoding="utf-8")

    assert "infinite_scroll_settle_s: 2.0" in yaml_text
    assert hasattr(CapabilitiesRegistry, "build")


# ─────────────────────────────────────────────────────────────────────────────
# Delegation, once a scroller is injected
# ─────────────────────────────────────────────────────────────────────────────


def test_an_injected_scroller_takes_over_and_no_raw_js_is_used():
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    browser = MagicMock()
    scroller = MagicMock()
    scroller.scroll_to_bottom.return_value = True

    strategy = InfiniteScrollStrategy(browser, scroller=scroller)

    assert strategy.next_page() is True
    scroller.scroll_to_bottom.assert_called_once_with()
    browser.execute_script.assert_not_called()


def test_the_injected_scrollers_answer_is_passed_through_unchanged():
    from auto_apply.adapters.secondary.navigation.pagination import (
        InfiniteScrollStrategy,
    )

    scroller = MagicMock()
    scroller.scroll_to_bottom.return_value = False

    assert InfiniteScrollStrategy(MagicMock(), scroller=scroller).next_page() is False


# ─────────────────────────────────────────────────────────────────────────────
# The runaway-scroll fix stays where it is
# ─────────────────────────────────────────────────────────────────────────────


def test_the_discovery_loop_still_owns_the_dry_scroll_guard_and_cap():
    """Guard pin: the fix that ended a four-minute Google scroll is untouched."""
    serp = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "src"
        / "auto_apply"
        / "adapters"
        / "secondary"
        / "discovery"
        / "strategies"
        / "serp_strategy.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "_scroll_and_mine" in serp
    assert "dry_scroll_limit" in serp
    assert "next_page()" in serp
